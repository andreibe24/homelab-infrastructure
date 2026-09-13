# infrastructure/

Cluster-wide plumbing, applied before `apps/`. Four Flux Kustomizations defined in
`clusters/homelab/infrastructure.yaml` reconcile these directories in order:

| Stage              | Path                        | Owner                | Contents |
| ------------------ | --------------------------- | -------------------- | -------- |
| `infra-namespaces` | `infrastructure/namespaces` | cluster-bootstrap    | every shared `Namespace` (with mesh-injection annotations) |
| `infra-sources`    | `infrastructure/sources`    | cluster-bootstrap    | shared `HelmRepository` (HTTP + OCI) objects in `flux-system` |
| `infra-controllers`| `infrastructure/controllers`| topics 2, 3, 5, 6    | operator installs, mostly `HelmRelease` |
| `infra-configs`    | `infrastructure/configs`    | topics 2, 3, 5, 6    | CRs that need those operators/CRDs to exist |

Rules for topic agents:

- one subdirectory per topic, each with its own `kustomization.yaml`
- register the subdirectory in the stage `kustomization.yaml` (entries are pre-listed
  as comments)
- never add a `Namespace` object — edit `infrastructure/namespaces/namespaces.yaml`
- never add a private `HelmRepository` — edit `infrastructure/sources/helm-repositories.yaml`
- no plaintext secrets, ever: use SOPS-encrypted files or `SealedSecret`
- pin every chart to an exact `spec.chart.spec.version` so Renovate (topic 6) can bump it
