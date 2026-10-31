# Repository instructions for AI agents

Read [docs/README.md](docs/README.md) and the relevant guides before changing
this repository. Keep user-facing documentation under `docs/` and update its
index when adding or moving a guide. `README.md` is the short repository entry
point; this file is the root agent-instruction entry point.

- Use [docs/adding-components.md](docs/adding-components.md) for directory
  structure, file names, registration, dependencies, and the distinct procedures
  for `apps/`, `infrastructure/components/`, and `infrastructure/imported/`.
  Inspect neighboring manifests before adding resources; preserve their Flux
  reconciliation, namespace, network policy, and prune behavior.
- `clusters/dev` is the configured kind cluster. `clusters/homelab` is not yet
  bootstrapped. The three top-level Kustomizations are currently shared inputs:
  adding to one affects every cluster that reconciles it. Consider both clusters
  and explicitly scope cluster-specific changes; do not assume homelab already
  uses the dev bootstrap, secrets, networking, or settings. See
  [docs/architecture.md](docs/architecture.md).
- Follow [docs/secrets.md](docs/secrets.md). Dev encrypted manifests live in
  `clusters/dev/init-manifests/secrets/` and are listed in its `kustomization.yaml`.
  Never commit plaintext secret values or private keys. Do not use the dev age
  recipient for homelab by default; the current SOPS rule matches all
  `*.secret.yaml` paths and must be revised before introducing a separate
  homelab recipient.
- Keep Flux `OCIRepository`, `HelmRelease`, and Flux `Kustomization` resources
  in separate `*.ocirepository.yaml`, `*.helmrelease.yaml`, and `*.ks.yaml`
  files. Keep OCI chart tags tag-based; image digest pinning is handled by
  Renovate. Follow existing resource-specific naming and local exceptions.
- When creating a pull request, use a Conventional Commit title:
  `<type>(<optional-scope>): <description>`, for example `docs: organize guides`
  or `feat(webapp): add search`. Add `!` before the colon for breaking changes.
  Choose the type that describes the change; squash-merged titles affect
  application versioning.
- Validate changed Kustomizations and relevant checks in
  `.github/workflows/lint-infrastructure.yaml`; account for remote dependencies
  and explicitly report checks that cannot be run.
