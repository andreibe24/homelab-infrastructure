# Agentgateway

The agentgateway CRDs and controller are installed with the upstream Helm charts.
Flux waits for the CRDs and controller before applying the resources in
`../agentgateway-config/`.
The existing Envoy HTTPS gateway forwards `agentgateway.localhost/v1` to an
agentgateway-managed ClusterIP proxy. Use the same HTTPS port and local CA trust
as the other `*.localhost` applications.

The native `Gateway`, `AgentgatewayBackend`, `HTTPRoute`, and `AgentgatewayPolicy`
resources configure Copilot routing and strict client API-key authentication.
`AgentgatewayParameters` keeps the managed proxy internal; Envoy remains the only
external entry point. The controller creates and manages the proxy workload and
Service.

## Credentials

There are two separate authentication steps:

```text
Your app --client API key--> agentgateway --Copilot token--> GitHub Copilot
```

The Copilot token gives the gateway access to your licensed GitHub account.
Client API keys protect the gateway from anonymous use of that account and its
quota. Give each app its own client key, not the Copilot token. All client keys
share the same upstream Copilot account and entitlements. Gateway policies impose
additional per-client limits; they do not create separate Copilot subscriptions.

Two SOPS/age-encrypted Secrets are managed in
`clusters/dev/init-manifests/secrets/`. The existing `secrets` Flux Kustomization
decrypts them using `flux-system/sops-age`. Reflector copies them from `flux-system`
to `agentgateway`; reflection is restricted to that namespace.

| Secret | Key | Purpose |
| --- | --- | --- |
| `copilot-token` | `Authorization` | A credential accepted by the Copilot API for an account with an active Copilot license (bare token or `Bearer ` prefix). |
| `agentgateway-client-keys` | `forum-app` | A JSON entry containing the app's key and trusted `client_id` metadata. |

Every entry in `agentgateway-client-keys` is an accepted client key. Never put the
upstream Copilot credential in this Secret.

A license alone is not a credential; do not assume an arbitrary GitHub PAT works.
Agentgateway does not
perform interactive login, exchange credentials, or refresh expired tokens.
Account entitlements, organization policies, quotas, and GitHub terms still apply.

### Create a least-privilege Copilot PAT

GitHub documents the following fine-grained PAT settings for Copilot authentication:

| Setting | Value |
| --- | --- |
| Token type | Fine-grained personal access token, not a classic PAT. |
| Resource owner | Your personal account with an active Copilot license, not an organization. |
| Account permissions | **Copilot Requests: Read**. |
| Repository permissions | Do not add any; no Contents, Actions, or administration permissions are needed for inference. |
| Expiration | A short, manageable lifetime; rotate the credential before it expires. |

[Create a PAT with Copilot Requests preselected](https://github.com/settings/personal-access-tokens/new?user_copilot_requests=read).
These settings are documented in
[GitHub's Copilot authentication guidance](https://github.github.com/gh-aw/reference/auth/#copilot_github_token).
That guidance covers Copilot CLI authentication, not a guarantee of compatibility
with agentgateway's direct Copilot API integration. Compatibility still needs an
end-to-end request through this deployment. Do not grant broader permissions if
authentication fails.

Store the issued token only in `stringData.Authorization` using SOPS as described
below. Never paste it into chat, shell arguments, or plaintext Git files.

### Store and rotate credentials

The Copilot token is an encrypted placeholder and must be replaced before use.
The client key is randomly generated. With the age private key available to SOPS,
edit the encrypted files from the repository root:

```sh
sops edit clusters/dev/init-manifests/secrets/copilot-token.secret.yaml
sops edit clusters/dev/init-manifests/secrets/agentgateway-client-keys.secret.yaml
```

Set `stringData.Authorization` to the real Copilot credential. Read or replace
the `key` inside `stringData.forum-app` for your client configuration. Commit only the encrypted files;
never commit decrypted values or the age private key. The controller watches the
reflected Secrets and updates the proxy configuration without restarting it.
Commit and push encrypted changes so Flux can reconcile them. To revoke the
upstream Copilot credential, also revoke it at its issuer.

If you provisioned `agentgateway-credentials` for the previous standalone setup,
re-provision the same values into the two Secrets above. The native configuration
does not use the old Secret.

## Configure a client

Configure an OpenAI-compatible client with base URL
`https://agentgateway.localhost/v1` (include your gateway's HTTPS port if needed)
and use the `key` inside the `forum-app` entry as its API key. Requests require
`Authorization: Bearer <client-api-key>`; the upstream Copilot credential is
injected separately. Choose a model ID available to the licensed account.
The Copilot backend forwards the requested model unchanged and does not grant
access to models outside the account's entitlements. `forum-app` may request only
`gpt-6-luna`; this model must also be available to the Copilot account.

Supported endpoints are `/v1/chat/completions`, `/v1/messages`, and `/v1/responses`.
Unlike the standalone LLM configuration, this setup does not expose a generated
`/v1/models` catalog; configure model IDs explicitly in clients.

The HTTPRoute exposes only `/v1`, not the admin UI or readiness/metrics ports.
End-to-end Copilot authentication requires the real Secret and a request using an
entitled model; local configuration validation alone cannot verify the license.

See the upstream [Kubernetes Copilot example](https://github.com/agentgateway/agentgateway/tree/v1.7.0/examples/llm-copilot).

## forum-app policies

The existing client key is preserved; only the Secret entry name and its format
change. In the decrypted SOPS editor, it now looks like:

```yaml
stringData:
  forum-app: '{"key":"<existing-client-key>","metadata":{"client_id":"forum-app"}}'
```

`client_id` is read from the authenticated Secret entry, not a caller-supplied
header. Authentication, authorization, rate limits, and guardrails are kept in
`../agentgateway-config/agentgateway-client-auth.policy.yaml` to avoid overlapping
policies overwriting one another.

| Control | forum-app setting |
| --- | --- |
| Model access | Only `gpt-6-luna`, via POST to the three supported endpoints. |
| Request rate | 10 requests/minute, shared across proxy replicas. |
| Token budget | 100,000 combined input/output tokens per UTC day, shared across replicas. |
| Output size | A positive integer output limit of at most 2,048 is required; missing, invalid, or oversized limits are rejected with 403. Multiple completions (`n > 1`) are rejected. |
| Sensitive-data checks | Reject credit card numbers, US SSNs, GitHub token patterns, AWS access-key IDs, and private-key headers in prompts, responses, and tool arguments. |

Use the output-limit field appropriate to the endpoint:

| Endpoint | Required field |
| --- | --- |
| `/v1/chat/completions` | `max_completion_tokens` |
| `/v1/responses` | `max_output_tokens` |
| `/v1/messages` | `max_tokens` |

For example, the Responses request body can be:

```json
{"model":"gpt-6-luna","input":"Explain HTTP caching.","max_output_tokens":2048,"stream":false}
```

Streaming requests are rejected for this client so the gateway can inspect the
complete response, including tool arguments, before releasing it. Regex checks
are limited pattern detection, not comprehensive PII detection, content
moderation, or prompt-injection protection; false positives and evasions are
possible. Emails and phone numbers are not blocked by these rules.
Request bodies are buffered up to 1MiB; larger bodies are rejected with 413.

The separate `../agentgateway-ratelimit/` component runs the Envoy rate-limit
service and Redis. Redis uses a 1Gi persistent volume from the cluster's default
StorageClass, append-only persistence with synchronous fsync, and no key eviction.
A default provisioner or a matching pre-provisioned PV is required. NetworkPolicies
restrict access to the proxy -> limiter -> Redis chain. Both services stay
internal and run without root privileges or Kubernetes API credentials.
This is a single-instance homelab deployment, not a highly available quota store.
Rate-limit service errors fail closed, blocking requests rather than bypassing
limits. Losing the Redis volume loses the counters.

Limits return 429 when exhausted. Token usage is charged after a response, so
in-flight requests can overshoot the budget; this is not a hard billing ceiling.
Accounting depends on provider-reported usage. Guard-blocked requests can consume
request quota, and generated responses can consume token budget even if blocked.
These LLM token counters are not GitHub premium-request or billing counters.

### Local policy checks

On Linux with Docker and PyYAML available, run from the repository root:

```sh
python3 infrastructure/components/agentgateway-config/forum-app.test.py -v
```

These checks translate the CRD rules to the proxy's standalone format and exercise
them against real proxy, rate-limit, and Redis containers with a mock LLM and fake
keys. They cover endpoint/output restrictions, sensitive-data checks, shared
quotas, Redis restart persistence, and fail-closed behavior. They do not verify
Kubernetes reconciliation, NetworkPolicy enforcement, or Copilot credentials.

## Add another client

1. Generate a new client key locally:

   ```sh
   openssl rand -hex 32
   ```

2. Open the encrypted client Secret:

   ```sh
   sops edit clusters/dev/init-manifests/secrets/agentgateway-client-keys.secret.yaml
   ```

3. Keep the existing entries and add a new entry under `stringData`. Each entry's
   name identifies the key for administration; its value is the API key:

   ```yaml
   stringData:
     forum-app: '{"key":"<existing-client-key>","metadata":{"client_id":"forum-app"}}'
     another-app: '{"key":"<new-random-key>","metadata":{"client_id":"another-app"}}'
   ```

   This is an example of the decrypted editor view, not content to commit as
   plaintext. SOPS encrypts the values when you save.

4. Explicitly allow the new `client_id` and its models in the authorization policy,
   and add its `client_requests` and `client_tokens` quotas to
   `../agentgateway-ratelimit/agentgateway-ratelimit.configmap.yaml`. New client IDs
   are denied by default; adding a Secret entry alone does not grant access.

5. Commit and push the encrypted file and policy changes. Flux decrypts it, Reflector copies it into
   `agentgateway`, and the controller updates authentication without a restart.
   Configure the new app with the same base URL and the new key as its API key.

To revoke a client's access, remove its entry with `sops edit`, then commit and
push. To rotate a key, replace its value and update that client's configuration.
These changes take effect after reconciliation; they do not revoke the upstream
Copilot credential or cancel requests already in flight.
