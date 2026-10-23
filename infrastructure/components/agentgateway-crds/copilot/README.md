# GitHub Copilot credentials

Agentgateway expects a non-expiring GitHub Copilot credential in a Kubernetes Secret named `copilot-token` in `agentgateway-system`, under the `Authorization` key. This is not an ordinary GitHub personal access token; use the credential supported by your Copilot account.

Create `copilot-token.secret.yaml` in this directory with a `Secret` containing that value in `stringData.Authorization`, then encrypt it with SOPS before committing it. Add the encrypted file to `kustomization.yaml` resources. Do not commit the plaintext credential or send it in chat. Flux decrypts SOPS files in this component using the existing `sops-age` key.

The Copilot HTTP endpoint is served by the `copilot` Gateway. Protect access to it with an appropriate network restriction or caller-authentication policy before exposing it beyond trusted clients.
