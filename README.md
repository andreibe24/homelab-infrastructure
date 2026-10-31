# homelab-infrastructure

TODO

Renovate pins container image digests in Kubernetes manifests (including the
kind cluster configuration), Kustomize image overrides, Dockerfiles, GitHub
Actions, GitLab CI, and Flux HelmRelease values and Kustomizations. Keep Flux
OCIRepository resources in dedicated
`*.ocirepository.yaml` files, separate from `*.helmrelease.yaml` and `*.ks.yaml`
files: their OCI chart/artifact tags and bootstrap chart versions are not
container images and must remain tag-based. Renovate also updates the
Dragonfly operator's remote Kustomize manifest by its GitHub tag, without
pinning it to a commit digest.

## Network policies

Each application and infrastructure component Kustomization installs its
namespace's ingress policy alongside its workloads. Application pods accept
traffic from their own namespace, the gateway and monitoring namespaces, and,
for the database application, the PostgreSQL operator. Infrastructure pods
accept ingress from cluster namespaces. These are namespace-level baselines, not per-port or
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
