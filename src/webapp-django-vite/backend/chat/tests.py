import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import (
    Client,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)

from .llm import GatewayError, generate
from .management.commands.mcp_server import StaticTokenVerifier, create_server
from .models import ChatMessage


class ChatApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "campfire-user", None, "S0mething-private-and-strong"
        )

    def test_anonymous_users_cannot_read_messages(self):
        response = self.client.get("/api/messages/")

        self.assertEqual(response.status_code, 401)

    def test_user_can_register_and_view_their_session(self):
        response = self.client.post(
            "/api/register/",
            data=json.dumps(
                {
                    "username": "new-camper",
                    "password": "S0mething-private-and-strong",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["username"], "new-camper")
        self.assertEqual(self.client.get("/api/me/").json()["username"], "new-camper")

    def test_registration_rejects_non_string_credentials(self):
        response = self.client.post(
            "/api/register/",
            data=json.dumps({"username": 42, "password": "strong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_authenticated_user_can_post_and_read_messages(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "Hello, everyone!"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        history = self.client.get("/api/messages/").json()["messages"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["username"], self.user.username)
        self.assertEqual(history[0]["content"], "Hello, everyone!")

    def test_message_length_is_limited(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "x" * 2001}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_post_requests_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            "/api/messages/post/",
            data=json.dumps({"content": "Hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)


class ForumToolTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("camper")
        self.client.force_login(self.user)

    def run_tool(self, name, arguments=None):
        return self.client.post(
            f"/api/tools/{name}/",
            data=json.dumps({} if arguments is None else arguments),
            content_type="application/json",
        )

    def test_tools_require_login_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/tools/").status_code, 401)
        self.assertEqual(self.run_tool("recent_messages").status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(
            client.post("/api/tools/summarize_forum/", data="{}",
                        content_type="application/json").status_code,
            403,
        )

    def test_recent_messages_returns_latest_twenty_in_chronological_order(self):
        ChatMessage.objects.bulk_create(
            ChatMessage(author=self.user, content=f"Message {i}") for i in range(25)
        )
        response = self.run_tool("recent_messages")
        self.assertEqual(response.status_code, 200)
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 20)
        self.assertEqual(messages[0]["content"], "Message 5")
        self.assertEqual(messages[-1]["content"], "Message 24")

    @patch("chat.tools.generate", return_value="A short summary.")
    def test_summary_uses_shared_forum_context_without_posting(self, generate):
        ChatMessage.objects.create(author=self.user, content="Let's learn Django.")
        response = self.run_tool("summarize_forum")
        self.assertEqual(response.json(), {"text": "A short summary."})
        context = generate.call_args.args[1]
        self.assertEqual(context["messages"][0]["content"], "Let's learn Django.")
        self.assertEqual(ChatMessage.objects.count(), 1)

    @patch("chat.tools.generate")
    def test_empty_summary_and_invalid_arguments_do_not_call_gateway(self, generate):
        for name, arguments in [
            ("summarize_forum", {}),
            ("draft_reply", {"idea": " "}),
            ("draft_reply", {"idea": "x" * 2001}),
            ("draft_reply", {"idea": 42}),
            ("draft_reply", {"idea": "Hello", "extra": True}),
            ("recent_messages", []),
            ("unknown", {}),
        ]:
            with self.subTest(name=name, arguments=arguments):
                self.assertEqual(self.run_tool(name, arguments).status_code, 400)
        generate.assert_not_called()

    @patch("chat.tools.generate", return_value="Hello from Campfire.")
    def test_draft_is_private_and_never_automatically_published(self, generate):
        response = self.run_tool("draft_reply", {"idea": "  Say hello  "})
        self.assertEqual(response.json(), {"text": "Hello from Campfire."})
        self.assertEqual(generate.call_args.args[1]["idea"], "Say hello")
        self.assertFalse(ChatMessage.objects.exists())

    @patch("chat.tools.generate", side_effect=GatewayError("Quota reached.", 429))
    def test_gateway_errors_are_visible_to_the_user(self, generate):
        response = self.run_tool("draft_reply", {"idea": "Hello"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"error": "Quota reached."})


class AskCampfireTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("camper")
        self.client.force_login(self.user)

    def ask(self, data):
        return self.client.post(
            "/api/ask/", data=json.dumps(data), content_type="application/json"
        )

    def test_requires_authentication_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.ask({"question": "Django?"}).status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(
            "/api/ask/", data='{"question":"Django?"}',
            content_type="application/json",
        ).status_code, 403)

    @patch("chat.rag.urlopen")
    def test_forwards_question_to_rag_service_and_returns_sources(self, urlopen):
        result = {
            "text": "The group discussed deployment [17].",
            "sources": [
                {
                    "id": 17,
                    "username": "camper",
                    "content": "We deployed Django with Helm.",
                    "createdAt": "2026-10-30T12:00:00+00:00",
                }
            ],
        }
        urlopen.return_value = BytesIO(json.dumps(result).encode())
        response = self.ask({"question": "  How did we deploy it?  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://webapp-django-vite-rag:8080/ask")
        self.assertEqual(json.loads(request.data), {"question": "How did we deploy it?"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 60)

    @patch("chat.rag.urlopen")
    def test_invalid_questions_do_not_call_rag_service(self, urlopen):
        for data in [
            {}, {"question": ""}, {"question": " "}, {"question": 123},
            {"question": "x" * 1001},
            {"question": "Django", "extra": True}, [],
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.ask(data).status_code, 400)
        urlopen.assert_not_called()

    @patch("chat.rag.urlopen")
    def test_rag_service_errors_are_reported(self, urlopen):
        urlopen.side_effect = HTTPError(
            "http://rag.test/ask", 429, "quota", {}, None
        )
        response = self.ask({"question": "Django"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json(),
            {"error": "Campfire search is unavailable. Please try again."},
        )

    @patch("chat.rag.urlopen")
    def test_invalid_rag_response_is_reported(self, urlopen):
        urlopen.return_value = BytesIO(b'{"text": "answer", "sources": "invalid"}')
        response = self.ask({"question": "Django"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(), {"error": "Campfire search returned an invalid response."}
        )


@override_settings(
    AGENTGATEWAY_BASE_URL="http://gateway.test/v1",
    AGENTGATEWAY_API_KEY="fake-forum-key",
    AGENTGATEWAY_CLIENT_CREDENTIALS="",
)
class GatewayTests(SimpleTestCase):
    def gateway_response(self, result):
        return BytesIO(json.dumps(result).encode())

    @patch("chat.llm.urlopen")
    def test_responses_api_matches_forum_app_policy(self, urlopen):
        urlopen.return_value = self.gateway_response({
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "A safe answer."}],
            }],
        })
        self.assertEqual(generate("Be concise.", {"idea": "Hello"}), "A safe answer.")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://gateway.test/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-forum-key")
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["store"])
        self.assertGreater(payload["max_output_tokens"], 0)
        self.assertLessEqual(payload["max_output_tokens"], 2048)
        self.assertEqual(json.loads(payload["input"]), {"idea": "Hello"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    @override_settings(
        AGENTGATEWAY_API_KEY="",
        AGENTGATEWAY_CLIENT_CREDENTIALS=json.dumps({
            "key": "reflected-key", "metadata": {"client_id": "forum-app"},
        }),
    )
    @patch("chat.llm.urlopen")
    def test_reflected_json_secret_supplies_the_forum_app_key(self, urlopen):
        urlopen.side_effect = URLError("unavailable")
        with self.assertRaises(GatewayError):
            generate("Be concise.", {})
        self.assertEqual(
            urlopen.call_args.args[0].get_header("Authorization"),
            "Bearer reflected-key",
        )

    @override_settings(AGENTGATEWAY_API_KEY="")
    @patch("chat.llm.urlopen")
    def test_missing_or_wrong_identity_fails_before_network_request(self, urlopen):
        for credentials in [
            "", "not-json", "[]",
            '{"key":"wrong-client","metadata":{"client_id":"another-app"}}',
            '{"key":"empty-metadata","metadata":null}',
        ]:
            with self.subTest(credentials=credentials), self.settings(
                AGENTGATEWAY_CLIENT_CREDENTIALS=credentials
            ), self.assertRaises(GatewayError):
                generate("Be concise.", {})
        urlopen.assert_not_called()

    @patch("chat.llm.urlopen")
    def test_upstream_errors_are_safe_and_actionable(self, urlopen):
        for code, expected in [(403, 403), (429, 429), (401, 503), (500, 503)]:
            with self.subTest(code=code):
                urlopen.side_effect = HTTPError(
                    "http://gateway.test", code, "sensitive upstream body", {}, None
                )
                with self.assertRaises(GatewayError) as raised:
                    generate("Be concise.", {})
                self.assertEqual(raised.exception.status, expected)
                self.assertNotIn("sensitive upstream body", str(raised.exception))

    @patch("chat.llm.urlopen")
    def test_connection_and_timeout_failures_are_reported(self, urlopen):
        for error in [URLError("unavailable"), TimeoutError(), ConnectionResetError()]:
            with self.subTest(error=type(error).__name__):
                urlopen.side_effect = error
                with self.assertRaises(GatewayError) as raised:
                    generate("Be concise.", {})
                self.assertEqual(raised.exception.status, 503)

    @patch("chat.llm.urlopen")
    def test_malformed_empty_and_incomplete_responses_are_reported(self, urlopen):
        for result in [
            {}, [], {"status": "completed", "output": []},
            {"status": "incomplete", "output": []},
            {"status": "completed", "output": [{"type": "message", "content": None}]},
        ]:
            with self.subTest(result=result):
                urlopen.return_value = self.gateway_response(result)
                with self.assertRaises(GatewayError) as raised:
                    generate("Be concise.", {})
                self.assertEqual(raised.exception.status, 502)
        urlopen.return_value = BytesIO(b"not-json")
        with self.assertRaises(GatewayError):
            generate("Be concise.", {})


class McpTests(TransactionTestCase):
    def test_sdk_discovers_and_executes_shared_tools(self):
        user = get_user_model().objects.create_user("mcp-camper")
        ChatMessage.objects.create(author=user, content="Hello from the forum.")
        server = create_server()
        tools = async_to_sync(server.list_tools)()
        self.assertEqual(
            {tool.name for tool in tools},
            {"recent_messages", "summarize_forum", "draft_reply"},
        )
        result = async_to_sync(server.call_tool)("recent_messages", {})
        self.assertIn("Hello from the forum.", str(result))
        with patch("chat.tools.generate", return_value="A shared summary.") as generate:
            result = async_to_sync(server.call_tool)("summarize_forum", {})
        self.assertIn("A shared summary.", str(result))
        self.assertEqual(
            generate.call_args.args[1]["messages"][0]["content"],
            "Hello from the forum.",
        )

    def test_command_requires_an_active_forum_user(self):
        with self.assertRaises(CommandError):
            call_command("mcp_server", username="missing")
        user = get_user_model().objects.create_user("disabled", is_active=False)
        with self.assertRaises(CommandError):
            call_command("mcp_server", username=user.username)

    def test_http_transport_requires_a_bearer_token(self):
        with self.assertRaises(CommandError):
            call_command("mcp_server", transport="streamable-http")

    def test_http_bearer_token_is_compared_without_timing_shortcuts(self):
        verifier = StaticTokenVerifier("secret-token")
        self.assertEqual(
            async_to_sync(verifier.verify_token)("secret-token").client_id,
            "campfire-operator",
        )
        self.assertIsNone(async_to_sync(verifier.verify_token)("wrong-token"))
