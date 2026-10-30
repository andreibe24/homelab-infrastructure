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

### Use a credential accepted by the direct Copilot API

The deployed endpoint rejects personal access tokens with
`Personal Access Tokens are not supported for this endpoint`. A fine-grained PAT
with **Copilot Requests: Read** is not usable here; adding repository permissions
or switching to a broader PAT will not fix that rejection. Copilot CLI PAT
authentication guidance does not establish support for this direct API.

The [upstream Kubernetes example](https://github.com/agentgateway/agentgateway/tree/v1.7.0/examples/llm-copilot)
requires the same credential as standalone Copilot, provisioned separately.
Standalone authentication can read credentials written by Copilot editor sign-in
or GitHub CLI OAuth login, but issuer, scopes, account entitlement, and endpoint
compatibility still matter. A successful CLI login alone is not proof that its
credential works with this endpoint.

Use the tools' normal interactive sign-in flow, review the requested access, and
confirm that the resulting credential is accepted by the direct API. Do not
request broader permissions to bypass a token-type rejection. Agentgateway does
not perform credential exchange or renewal for the Kubernetes Secret.

Store an accepted credential only in `stringData.Authorization` using SOPS as
described below. Never paste it into chat, shell arguments, or plaintext Git files.
Revoke the rejected PAT if it was created solely for this deployment.

### GitHub CLI OAuth procedure

GitHub CLI browser OAuth was verified end-to-end with this deployment:
`/v1/responses`, model `gpt-6-luna`, and the HTTPS test script returned HTTP 200.
This confirms the tested credential/account combination, not arbitrary OAuth tokens.

1. Sign in with the account that has the Copilot license:

   ```sh
   gh auth login --hostname github.com --web
   gh auth status
   ```

   Use browser OAuth, not `--with-token`. Review the requested permissions.
   `GH_TOKEN` and `GITHUB_TOKEN` can override stored credentials; ensure neither
   supplies the rejected PAT. Check the active account before exporting a token.
   Prefer the OS credential store; do not request `--insecure-storage`.

2. With the age private key available, run this Bash pipeline from the repository
   root. It transfers the credential into SOPS without printing it or placing it
   in process arguments:

   ```bash
   (
     set -euo pipefail
     gh auth token --hostname github.com |
       python3 -c '
   import json, sys
   token = sys.stdin.read().strip()
   if not token:
       raise SystemExit("No GitHub credential returned")
   json.dump(token, sys.stdout)
   ' |
       sops set --value-stdin \
         clusters/dev/init-manifests/secrets/copilot-token.secret.yaml \
         '["stringData"]["Authorization"]'
   )
   ```

   Do not run with shell tracing (`set -x`), print the token, or save it to a
   plaintext temporary file.

3. Commit and push only the encrypted Secret change. Wait for Flux and Reflector
   reconciliation, then run:

   ```sh
   python3 infrastructure/components/agentgateway-config/forum-app.test.py --live
   ```

   Live mode requires Python and kubectl, not Docker or PyYAML. It uses
   `https://agentgateway.localhost:8443/v1/responses` and disables TLS verification
   for the local development certificate (equivalent to `curl -k`).
   HTTP 200 with an assistant response
   confirms the full path; Flux readiness alone does not confirm authentication.
   It also checks missing/invalid client keys, model and output-limit restrictions,
   streaming/multiple-completion rejection, the 1MiB request limit, and synthetic
   sensitive-data patterns including tool arguments. It exits nonzero on failure
   without printing response bodies or credentials.

   Pause other traffic using `forum-app` and ensure daily token quota is available.
   The script waits for a new minute before quota-dependent checks to avoid
   interference from earlier runs. The default checks consume request quota and
   make one real inference request. To additionally test the shared
   10-requests/minute ceiling:

   ```sh
   python3 infrastructure/components/agentgateway-config/forum-app.test.py --live --rate-limit
   ```

   This waits for the next minute, then sends ten guard-rejected requests and
   expects the eleventh to return 429. These probes should not reach Copilot,
   but leave the shared request quota exhausted until the next minute.
   Live daily-budget exhaustion, response-guard checks, and outage injection are
   intentionally excluded; use the isolated `forum-app.test.py` suite instead.

### OAuth lifetime and permission limits

There is no fixed lifetime established by the successful inference request.
Traditional non-expiring OAuth tokens remain usable until revoked; GitHub
automatically revokes OAuth tokens unused for one year and can revoke them for
other security reasons. Newer GitHub CLI authentication flows can also issue
expiring credentials depending on CLI, host, and OAuth app configuration.
Do not assume the credential is permanent or that all OAuth tokens expire after
the same interval.

The Secret stores only a snapshot of the access token, not a refresh token or a
running GitHub CLI session. CLI refresh on your workstation does not refresh the
cluster's copy. Repeat the export, encrypted commit, and reconciliation after
rotation, expiration, or reauthentication. Adopt a manual rotation schedule
(for example, every 30-90 days); this is an operational policy, not an expiry
enforced by GitHub.

GitHub CLI OAuth is not full account administration by default, but its minimum
scopes are still broad: `repo`, `read:org`, and `gist`. In particular, `repo`
includes read/write access to repositories the account can access. GitHub CLI
does not support removing these minimum scopes, so this procedure cannot produce
a Copilot-only or repository-read-only token.

Inspect the active token's granted scopes without displaying its value:

```sh
gh api --hostname github.com --include user |
  grep -i '^x-oauth-scopes:'
```

To remove additional grants, reset to the CLI defaults:

```sh
gh auth refresh --hostname github.com --reset-scopes
```

This still retains the broad minimum scopes. Re-export the resulting token to
SOPS and repeat the inference test; do not assume changes to local credentials
updated the deployed Secret or revoked previously exported tokens.

Gateway policies constrain gateway callers, not the underlying OAuth token.
Someone who steals that token can bypass those policies and exercise its GitHub
permissions directly. Avoid authorizing unnecessary organization access and
consider a separately licensed account with no sensitive repository access,
subject to GitHub's account and subscription policies. A Copilot-only alternative
requires a separately verified authentication flow; the rejected PAT is not one.

To revoke the OAuth grant, use GitHub Settings -> Applications -> Authorized
OAuth Apps -> GitHub CLI. Revocation affects other CLI sessions using that grant;
removing a local login or deleting the Kubernetes Secret is not issuer-side
revocation.

References: [GitHub CLI login](https://cli.github.com/manual/gh_auth_login),
[scope management](https://cli.github.com/manual/gh_auth_refresh),
[OAuth scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps),
and [token expiration and revocation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/token-expiration-and-revocation).

### Store and rotate credentials

The Copilot token was initially an encrypted placeholder; replace it before use
unless a working credential has already been provisioned.
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

Use `/v1/responses` with this Copilot backend. Although the route and policy also
permit `/v1/chat/completions` and `/v1/messages`, the v1.7.0 Copilot provider accepts
only OpenAI Responses format and rejects conversions from those other formats.
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
| Model access | Only `gpt-6-luna`, via POST; use `/v1/responses` with Copilot. |
| Request rate | 10 requests/minute, shared across proxy replicas. |
| Token budget | 100,000 combined input/output tokens per UTC day, shared across replicas. |
| Output size | A positive integer output limit of at most 2,048 is required; missing, invalid, or oversized limits are rejected with 403. Multiple completions (`n > 1`) are rejected. |
| Sensitive-data checks | Reject credit card numbers, US SSNs, GitHub token patterns, AWS access-key IDs, and private-key headers in prompts, responses, and tool arguments. |

The policy validates these endpoint-specific output-limit fields; only the
Responses endpoint is usable with the current Copilot provider:

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
service and an operator-managed Dragonfly instance using the Redis protocol.
Dragonfly uses a 1Gi persistent volume from the cluster's default StorageClass,
snapshots every minute, and no cache-mode eviction. This is not Redis AOF:
an abrupt restart can lose updates since the last successful snapshot.
A default provisioner or a matching pre-provisioned PV is required. NetworkPolicies
restrict access to the proxy -> limiter -> Dragonfly chain, with Dragonfly's
admin port accessible only to the operator in `redis-operator`. Both services stay
internal and run without root privileges or Kubernetes API credentials.
This is a single-instance homelab deployment, not a highly available quota store.
Rate-limit service errors fail closed, blocking requests rather than bypassing
limits. Losing the Dragonfly volume loses the counters.

The Redis-to-Dragonfly cutover intentionally starts fresh minute/day counters.
Flux removes the old Redis StatefulSet and Service; its retained PVC is not
reused or deleted by this configuration. Expect requests to fail closed while
the new store starts and the limiter reconnects. Remove the old PVC manually
only after confirming the new store is healthy. This change does not migrate data.

Limits return 429 when exhausted. Token usage is charged after a response, so
in-flight requests can overshoot the budget; this is not a hard billing ceiling.
Accounting depends on provider-reported usage. Guard-blocked requests can consume
request quota, and generated responses can consume token budget even if blocked.
These LLM token counters are not GitHub premium-request or billing counters.

### Local policy checks

The single `forum-app.test.py` entry point supports isolated checks by default
and deployed HTTPS checks with `--live` as described above. Live mode accepts
`--url https://host:port/v1/responses` to override the endpoint.

On Linux with Docker and PyYAML available, run from the repository root:

```sh
python3 infrastructure/components/agentgateway-config/forum-app.test.py -v
```

These checks translate the CRD rules to the proxy's standalone format and exercise
them against real proxy, rate-limit, and Dragonfly containers with a mock LLM and fake
keys. They cover endpoint/output restrictions, sensitive-data checks, shared
quotas, recovery from a completed Dragonfly snapshot, and fail-closed behavior.
They do not verify
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
