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
currently share the same upstream Copilot account, entitlements, and quota; they
do not create separate Copilot subscriptions or per-client usage limits.

Two SOPS/age-encrypted Secrets are managed in
`clusters/dev/init-manifests/secrets/`. The existing `secrets` Flux Kustomization
decrypts them using `flux-system/sops-age`. Reflector copies them from `flux-system`
to `agentgateway`; reflection is restricted to that namespace.

| Secret | Key | Purpose |
| --- | --- | --- |
| `copilot-token` | `Authorization` | A credential accepted by the Copilot API for an account with an active Copilot license (bare token or `Bearer ` prefix). |
| `agentgateway-client-keys` | `client1`, `client2`, etc. | Keys your apps use to authenticate to agentgateway, not to GitHub. |

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
`stringData.client1` for your client configuration. Commit only the encrypted files;
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
and use the `client1` value as its API key. Requests require
`Authorization: Bearer <client-api-key>`; the upstream Copilot credential is
injected separately. Choose a model ID available to the licensed account.
The Copilot backend forwards the requested model unchanged and does not grant
access to models outside the account's entitlements.

Supported endpoints are `/v1/chat/completions`, `/v1/messages`, and `/v1/responses`.
Unlike the standalone LLM configuration, this setup does not expose a generated
`/v1/models` catalog; configure model IDs explicitly in clients.

The HTTPRoute exposes only `/v1`, not the admin UI or readiness/metrics ports.
End-to-end Copilot authentication requires the real Secret and a request using an
entitled model; local configuration validation alone cannot verify the license.

See the upstream [Kubernetes Copilot example](https://github.com/agentgateway/agentgateway/tree/v1.7.0/examples/llm-copilot).

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
     client1: <existing-client-key>
     client2: <new-random-key>
   ```

   This is an example of the decrypted editor view, not content to commit as
   plaintext. SOPS encrypts the values when you save.

4. Commit and push the encrypted file. Flux decrypts it, Reflector copies it into
   `agentgateway`, and the controller updates authentication without a restart.
   Configure the new app with the same base URL and the new key as its API key.

To revoke a client's access, remove its entry with `sops edit`, then commit and
push. To rotate a key, replace its value and update that client's configuration.
These changes take effect after reconciliation; they do not revoke the upstream
Copilot credential or cancel requests already in flight.
