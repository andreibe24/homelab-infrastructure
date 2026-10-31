# Architecture and clusters

## Repository layout

| Path | Purpose |
| --- | --- |
| `clusters/dev/bootstrap/` | kind configuration and bootstrap for the dev cluster. |
| `clusters/dev/init-manifests/` | Flux entry point for dev, including its encrypted secrets. |
| `clusters/{dev,homelab}/imported/` | Cluster overlays for bootstrap-installed infrastructure. |
| `clusters/homelab/` | Two-node Talos bootstrap and homelab Flux entry point. |
| `apps/` | Shared application registrations and workload manifests. |
| `infrastructure/components/` | Shared infrastructure installed and managed by Flux. |
| `infrastructure/imported/` | Shared Flux definitions for bootstrap-installed infrastructure. |
| `src/` | Application source and build configuration. |
| `docs/` | Documentation and external workflow dispatcher examples. |
| `.github/workflows/` | CI and automation workflows. |

## Cluster reconciliation

`clusters/dev/bootstrap/bootstrap.sh` creates a single-node kind cluster,
installs Gateway API CRDs, Cilium and the Flux Operator, provisions the SOPS
key, and applies the FluxInstance. The script requires kind, kubectl, Helm, a
container runtime and the age key at `~/.config/sops/age/keys.txt`; read its
preflight checks before running it. It writes the kubeconfig to
`~/.kube/configs/dev-cluster.yaml`.

The dev FluxInstance syncs `clusters/dev/init-manifests/`. Its Flux
Kustomizations reconcile `clusters/dev/imported/`,
`infrastructure/components/`, `apps/`, and dev secrets. Apps depend on the
two infrastructure roots; individual Flux Kustomizations can add their own
dependencies. The imported root and its existing components disable pruning,
whereas apps and ordinary infrastructure use pruning.

Dev also reconciles a cluster-specific Keycloak operator and instance for
Grafana and Campfire sign-in. Its operator and CRDs are not pruned, and its
namespace is protected from Flux pruning. Homelab does not inherit this
identity deployment or its credentials; see [Keycloak](components/keycloak.md).

Homelab is a planned single control-plane, single worker Talos cluster; the
repository cannot provision its hardware without operator-supplied addresses and
disks. Its Flux entry point adopts a Talos-specific Cilium overlay and the
shared Flux Operator. Shared infrastructure and apps are defined but suspended
until storage, secrets, gateway and networking are ready. The existing gateway
allowlist is not registered. See [homelab bootstrap](homelab-talos.md).
Once enabled, shared roots affect both clusters; use cluster-specific
selection or overlays for divergent settings.

Both cluster imported roots build on `infrastructure/imported/`. Cilium shares
its chart, release, network policy and common Helm values there; each cluster
adds its own overrides from `infrastructure/imported/cilium/custom-values/<cluster>.yaml`.
The shared ConfigMap contains both non-secret overrides, while each cluster's
Cilium overlay in `infrastructure/imported/overlays/cilium/` selects only its
own key. Dev uses the kind API endpoint, while
homelab uses the operator-supplied API address and Talos-specific cgroup and
capability settings. Both bootstraps apply common values first and their
cluster overrides second, matching Flux.

## Network policies

Application and infrastructure Kustomizations install namespace ingress
policies alongside workloads. Application pods accept traffic from their own
namespace, the gateway and monitoring namespaces, and, for the database
application, the PostgreSQL operator. Infrastructure pods accept ingress from
cluster namespaces. These are namespace-level baselines, not per-port or
per-workload isolation; egress remains unrestricted except for the existing
agentgateway rate-limiter and Dragonfly policies. Their pods are excluded from
the broader agentgateway baseline because NetworkPolicies are additive.
Flux's bootstrap configuration enables its own generated policies; no broader
policy is added to `flux-system`.

The development gateway uses `hostNetwork`: standard NetworkPolicy cannot
reliably select host-network traffic by namespace. The single-node kind setup
relies on Cilium allowing traffic from the local node, including gateway
traffic and kubelet probes. Reassess host and remote-node traffic before
deploying this configuration on multiple nodes or a different CNI.

## Dependency updates

Renovate pins container image digests in Kubernetes manifests (including the
kind cluster configuration), Kustomize image overrides, Dockerfiles, GitHub
Actions, GitLab CI, and Flux HelmRelease values and Kustomizations. Flux
OCIRepository resources belong in dedicated `*.ocirepository.yaml` files,
separate from `*.helmrelease.yaml` and `*.ks.yaml`; OCI chart/artifact tags and
bootstrap chart versions are not container images and must remain tag-based.
Renovate also updates the Dragonfly operator's remote Kustomize manifest by its
GitHub tag, without pinning it to a commit digest.
Talos and Kubernetes bootstrap versions use release tags and require manual
review and upgrades, not automerge; see [homelab bootstrap](homelab-talos.md).
This is a risk-management choice, not a Renovate or Talos requirement. Talos
and Kubernetes PRs change future bootstrap defaults, not running nodes; Cilium
and Flux Operator chart PRs also change live Flux releases. Manual review helps
check compatibility and plan recovery before those critical upgrades.

The daily Renovate workflow requires a GitHub App installed on this repository
with **Contents: Read and write** and **Pull requests: Read and write**
permissions. Add its ID and private key as repository secrets named
`RENOVATE_APP_ID` and `RENOVATE_APP_PRIVATE_KEY`. The workflow also supports
manual runs from `main`.
