# Secrets

Never commit plaintext credentials, decrypted secret manifests, age private
keys, or local credential files. Kubernetes `data` is only base64 encoding,
not encryption. SOPS encrypts values in `data` and `stringData`; other fields,
including metadata, remain visible, so do not put secret values there.

## Development cluster

Encrypted Kubernetes Secrets are stored in
`clusters/dev/init-manifests/secrets/*.secret.yaml` and listed in that
directory's `kustomization.yaml`. The dev `secrets` Flux Kustomization points
there and decrypts with the `sops-age` Secret in `flux-system`. Some secrets
are reflected into other namespaces; inspect existing annotations and restrict
reflection to the namespaces that need them.

The dev bootstrap reads `~/.config/sops/age/keys.txt` and creates
`flux-system/sops-age` from it. The private key must correspond to the public
recipient in `.sops.yaml` and be provisioned securely outside Git. Do not
generate a replacement key for existing encrypted files unless their recipients
are deliberately rotated.

From the repository root, edit an existing encrypted secret with:

```sh
sops edit clusters/dev/init-manifests/secrets/alertmanager-slack.secret.yaml
```

For a new secret, create the manifest securely, encrypt it with SOPS using the
repository rule before staging it, and register it in the dev secrets
Kustomization. Avoid printing values or leaving plaintext temporary files.
Review the staged diff to ensure `data`/`stringData` values are encrypted
before committing. Flux only reconciles the encrypted files after they are
committed and synced.

```sh
sops --encrypt --in-place clusters/dev/init-manifests/secrets/my-app.secret.yaml
```

Replace `my-app` with the actual name. The initial file is plaintext until
encryption succeeds; keep it private and never stage it before verifying the
result. To inspect an encrypted file locally, `sops --decrypt` outputs the
plaintext, so avoid logs and shared terminals.

## Homelab and recipient isolation

Homelab has no configured secrets reconciliation or age key in this repository
yet, and its Talos bootstrap does not reuse dev secrets. The existing `.sops.yaml` rule matches **all** `*.secret.yaml` paths even
though its recipient is labeled for dev. Placing a homelab secret under a new
directory would therefore encrypt it to the dev recipient, not a separate
homelab key.

Before adding homelab secrets, establish secure key provisioning, define
ordered path-specific SOPS rules with the appropriate
recipients, and configure a homelab secrets directory, Kustomization and Flux
decryption reference. Verify the selected recipient and ensure existing dev
secrets remain decryptable. Do not commit keys or reuse dev credentials merely
to make the new cluster work. GitHub Actions and external dispatcher credentials
are managed in their respective secret stores, not in Kubernetes manifests.

For a new recipient, generate an age key in a secure location using
`age-keygen -o <private-key-file>` and use only its public recipient in the
SOPS rule. Back up the private key securely and provision it to the intended
cluster without committing it.

Generated Talos machine configurations, talosconfig and kubeconfig contain
cluster credentials. Store and back them up outside the repository with
restricted permissions; see [homelab-talos.md](homelab-talos.md).
