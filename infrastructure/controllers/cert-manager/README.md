# cert-manager

Installed by the **linkerd-mtls** topic because it is a hard prerequisite for the
Linkerd trust anchor and for the auto-rotating identity issuer certificate.

| Object | Where |
| ------ | ----- |
| `HelmRelease/cert-manager` (chart `v1.21.2`, repo `jetstack`) | `helmrelease.yaml` |
| Shared `ClusterIssuer`s for the rest of the cluster | `../../configs/cert-manager/` |
| Linkerd trust anchor + identity issuer | `../../configs/linkerd/pki/` |

Notes:

- CRDs are installed by the chart (`crds.enabled: true`, `crds.keep: true`), so a
  chart uninstall never garbage-collects the cluster's `Certificate`/`Issuer`
  objects.
- `startupapicheck` stays enabled: Flux only marks the release Ready once the
  admission webhook actually answers, which is what keeps the `linkerd-pki`
  Flux Kustomization from racing it.
- cert-manager is deliberately **not** mesh-injected — it is a layer below the
  mesh; injecting it would create a bootstrap cycle.
- Other topics must reuse `ClusterIssuer/homelab-ca` or `ClusterIssuer/selfsigned`
  rather than installing a second PKI.

See `../linkerd/README.md` for the full mTLS story.
