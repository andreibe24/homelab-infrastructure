"""Exercise the manifest's policy rules with real proxy/limiter/Redis containers.

Requires Linux, Docker, and PyYAML. Uses fake credentials and a local mock LLM;
does not access Copilot, the SOPS private key, or the Kubernetes cluster.
"""

import copy
import http.server
import json
import pathlib
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

import yaml


ROOT = pathlib.Path(__file__).resolve().parent
LIMITER = ROOT.parent / "agentgateway-ratelimit"


def load(path):
    return yaml.safe_load(path.read_text())


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MockLLM(http.server.BaseHTTPRequestHandler):
    content = "A safe answer."
    tokens = 20
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(body)
        if self.path.endswith("/responses"):
            response = {
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": body["model"],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "temperature": 1.0,
                "top_p": 1.0,
                "metadata": {},
                "text": {"format": {"type": "text"}},
                "output": [{
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": self.content, "annotations": []}],
                }],
                "usage": {"input_tokens": self.tokens - 1, "output_tokens": 1,
                          "total_tokens": self.tokens,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}},
            }
        else:
            response = {
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": self.content}}],
                "usage": {"prompt_tokens": self.tokens - 1, "completion_tokens": 1,
                          "total_tokens": self.tokens},
            }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_):
        pass


class ForumPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="forum-app-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.processes = {}
        cls.addClassCleanup(cls.stop_containers)
        directory = pathlib.Path(cls.temp.name)
        directory.chmod(0o755)
        cls.redis_port, cls.limit_port, cls.http_port, cls.gateway_port = [
            free_port() for _ in range(4)
        ]
        cls.prefix = "forum-policy-" + uuid.uuid4().hex[:8]
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

        cls.redis_spec = load(LIMITER / "agentgateway-ratelimit-redis.statefulset.yaml")
        cls.redis_container = cls.redis_spec["spec"]["template"]["spec"]["containers"][0]
        data = directory / "redis"
        data.mkdir(mode=0o777)
        data.chmod(0o777)
        cls.redis_args = [
            "--user", "999:1000", "--read-only", "--cap-drop", "ALL",
            "-v", f"{data}:/data", cls.redis_container["image"],
            *cls.redis_container["args"], "--port", str(cls.redis_port),
        ]
        cls.start("redis", cls.redis_args)
        cls.wait(lambda: cls.redis("ping") == "PONG")

        config_dir = directory / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            load(LIMITER / "agentgateway-ratelimit.configmap.yaml")["data"]["config.yaml"]
        )
        deployment = load(LIMITER / "agentgateway-ratelimit.deployment.yaml")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env = {item["name"]: item["value"] for item in container["env"]}
        env.update(REDIS_URL=f"127.0.0.1:{cls.redis_port}",
                   GRPC_PORT=str(cls.limit_port), PORT=str(cls.http_port),
                   DEBUG_PORT=str(free_port()))
        args = ["--user", "65532", "--read-only", "--cap-drop", "ALL",
                "-v", f"{config_dir}:/data/ratelimit/config:ro"]
        for key, value in env.items():
            args.extend(["-e", f"{key}={value}"])
        cls.limiter_args = [*args, container["image"]]
        cls.start("limiter", cls.limiter_args)
        cls.wait(lambda: urllib.request.urlopen(
            f"http://127.0.0.1:{cls.http_port}/healthcheck", timeout=1
        ).status == 200)

        # Native CRD fields use PascalCase enums; the proxy's local format differs.
        spec = load(ROOT / "agentgateway-client-auth.policy.yaml")["spec"]
        traffic = spec["traffic"]
        remote = traffic["rateLimit"]["global"]
        descriptors = [{
            "entries": [{"key": item["name"], "value": item["expression"]}
                        for item in desc["entries"]],
            "type": desc["unit"].lower(),
        } for desc in remote["descriptors"]]
        guards = copy.deepcopy(spec["backend"]["ai"]["promptGuard"])
        for direction in ["request", "response"]:
            for guard in guards[direction]:
                guard["scope"] = [scope[0].lower() + scope[1:] for scope in guard["scope"]]
                regex = guard["regex"]
                regex["action"] = regex["action"].lower()
                regex["rules"] = [
                    {"builtin": {"Ssn": "ssn", "CreditCard": "creditCard"}[builtin]}
                    for builtin in regex.pop("builtins")
                ] + [{"pattern": pattern} for pattern in regex.pop("matches")]
                response = guard.pop("response")
                guard["rejection"] = {"status": response["statusCode"], "body": response["message"]}
        config = {
            "config": {"adminAddr": f"127.0.0.1:{free_port()}",
                       "readinessAddr": f"127.0.0.1:{free_port()}",
                       "statsAddr": f"127.0.0.1:{free_port()}"},
            "gateways": {"default": {"port": cls.gateway_port}},
            "llm": {
                "gateways": ["default"],
                "models": [{"name": "*", "provider": "openAI", "params": {
                    "baseUrl": f"http://127.0.0.1:{cls.server.server_port}/v1",
                    "apiKey": "fake-upstream-key",
                }}],
                "policies": {
                    "apiKey": {"mode": "strict", "keys": [
                        {"key": "fake-forum-key", "metadata": {"client_id": "forum-app"}},
                        {"key": "fake-other-key", "metadata": {"client_id": "another-app"}},
                    ]},
                    "authorization": {"rules": [{"require": expression} for expression in
                        traffic["authorization"]["policy"]["matchExpressions"]]},
                    "remoteRateLimit": {"domain": remote["domain"],
                                        "failureMode": remote["failureMode"],
                                        "host": f"127.0.0.1:{cls.limit_port}",
                                        "descriptors": descriptors},
                    "guardrails": guards,
                },
            },
        }
        buffer = copy.deepcopy(traffic["buffer"])
        buffer["request"]["failureMode"] = "failClosed"
        config["policies"] = [{
            "name": {"name": "forum-app-buffer", "namespace": "default"},
            "target": {"gateway": {"gatewayName": "default", "gatewayNamespace": "default"}},
            "policy": {"buffer": buffer},
        }]
        cls.start("gateway", ["cr.agentgateway.dev/agentgateway:v1.7.0", "-c",
                              yaml.safe_dump(config)])
        cls.wait(lambda: cls.request({}, key=None)[0] == 401)

    @classmethod
    def start(cls, role, args):
        log = open(pathlib.Path(cls.temp.name) / f"{role}.log", "w+")
        name = f"{cls.prefix}-{role}"
        proc = subprocess.Popen(["docker", "run", "--rm", "--name", name,
                                 "--network", "host", *args], stdout=log, stderr=log)
        cls.processes[role] = (name, proc, log)

    @classmethod
    def stop(cls, role):
        name, proc, log = cls.processes.pop(role)
        if role == "redis" and proc.poll() is None:
            subprocess.run(["docker", "exec", name, "chmod", "-R", "a+rwX",
                            "/data/appendonlydir"], check=True, capture_output=True)
        subprocess.run(["docker", "stop", "--time", "2", name], capture_output=True)
        proc.wait(timeout=15)
        log.close()

    @classmethod
    def stop_containers(cls):
        for role in list(reversed(cls.processes)):
            cls.stop(role)

    @classmethod
    def wait(cls, ready):
        for _ in range(100):
            for _, proc, log in cls.processes.values():
                if proc.poll() is not None:
                    log.seek(0)
                    raise AssertionError(log.read())
            try:
                if ready():
                    return
            except (OSError, urllib.error.URLError, subprocess.CalledProcessError):
                pass
            time.sleep(0.1)
        raise AssertionError("Container did not become ready")

    @classmethod
    def redis(cls, *args):
        return subprocess.check_output([
            "docker", "exec", f"{cls.prefix}-redis", "redis-cli",
            "-p", str(cls.redis_port), *args,
        ], text=True, stderr=subprocess.PIPE).strip()

    @classmethod
    def request(cls, body, path="/v1/chat/completions", key="fake-forum-key"):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request(f"http://127.0.0.1:{cls.gateway_port}{path}",
                                     data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    def setUp(self):
        self.redis("flushdb")
        MockLLM.content, MockLLM.tokens = "A safe answer.", 20
        MockLLM.requests.clear()
        self.body = {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "Hello"}],
                     "max_completion_tokens": 100}

    def test_access_caps_and_sensitive_data(self):
        self.assertEqual(self.request(self.body, key=None)[0], 401)
        self.assertEqual(self.request(self.body, key="fake-other-key")[0], 403)
        for patch in [
            {"model": "other-model"}, {"max_completion_tokens": 2049},
            {"max_completion_tokens": 0}, {"max_completion_tokens": "100"},
            {"max_completion_tokens": 1.5}, {"max_completion_tokens": True},
            {"max_completion_tokens": None}, {"max_tokens": 9999},
            {"stream": True}, {"n": 2},
        ]:
            with self.subTest(patch=patch):
                self.assertEqual(self.request(self.body | patch)[0], 403)
        missing = dict(self.body)
        del missing["max_completion_tokens"]
        self.assertEqual(self.request(missing)[0], 403)
        self.assertEqual(MockLLM.requests, [])
        result = self.request(self.body)
        self.assertEqual(result[0], 200, result)
        self.assertEqual(MockLLM.requests[-1]["max_completion_tokens"], 100)
        secret_like = "-----BEGIN PRIVATE KEY-----"
        for content in [secret_like, "4111 1111 1111 1111", "123-45-6789",
                        "ghp_" + "a" * 30, "github_pat_" + "b" * 30,
                        "AKIA" + "A" * 16]:
            with self.subTest(content=content):
                blocked = self.body | {"messages": [{"role": "user", "content": content}]}
                self.assertEqual(self.request(blocked)[0], 403)
        self.assertEqual(len(MockLLM.requests), 1)
        MockLLM.content = secret_like
        status, response = self.request(self.body)
        self.assertEqual(status, 403)
        self.assertNotIn(secret_like.encode(), response)

    def test_shared_request_limit(self):
        for _ in range(10):
            self.assertEqual(self.request(self.body)[0], 200)
        self.assertEqual(self.request(self.body)[0], 429)
        self.assertEqual(len(MockLLM.requests), 10)

    def test_endpoint_caps_and_tool_arguments(self):
        body = {"model": "gpt-6-luna", "input": "Hello", "max_output_tokens": 100}
        self.assertEqual(self.request(body, path="/v1/responses")[0], 200)
        self.assertEqual(MockLLM.requests[-1]["max_output_tokens"], 100)
        body = {"model": "gpt-6-luna", "messages": self.body["messages"], "max_tokens": 100}
        self.assertEqual(self.request(body, path="/v1/messages")[0], 200)
        self.assertEqual(MockLLM.requests[-1]["max_output_tokens"], 100)
        del body["max_tokens"]
        self.assertEqual(self.request(body, path="/v1/messages")[0], 403)
        body = self.body | {"messages": [{
            "role": "assistant", "tool_calls": [{
                "id": "test", "type": "function",
                "function": {"name": "lookup",
                             "arguments": '{"key":"-----BEGIN PRIVATE KEY-----"}'},
            }],
        }]}
        before = len(MockLLM.requests)
        self.assertEqual(self.request(body)[0], 403)
        self.assertEqual(len(MockLLM.requests), before)
        oversized = self.body | {"messages": [{"role": "user", "content": "x" * 1048576}]}
        self.assertEqual(self.request(oversized)[0], 413)

    def test_token_budget_survives_redis_restart(self):
        MockLLM.tokens = 60000
        self.assertEqual(self.request(self.body)[0], 200)
        self.assertEqual(self.request(self.body)[0], 200)
        self.assertEqual(self.request(self.body)[0], 429)
        self.stop("redis")
        self.start("redis", self.redis_args)
        self.wait(lambda: self.redis("ping") == "PONG")

        def reconnected():
            status = self.request(self.body)[0]
            self.assertIn(status, [429, 500])
            return status == 429

        self.wait(reconnected)

    def test_unavailable_limiter_fails_closed(self):
        self.stop("limiter")
        try:
            self.assertEqual(self.request(self.body)[0], 500)
            self.assertEqual(MockLLM.requests, [])
        finally:
            self.start("limiter", self.limiter_args)
            self.wait(lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{self.http_port}/healthcheck", timeout=1
            ).status == 200)


if __name__ == "__main__":
    unittest.main()
