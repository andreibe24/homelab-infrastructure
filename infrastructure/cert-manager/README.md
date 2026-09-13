# cert-manager

Installed because it is a hard prerequisite for the Linkerd trust anchor and for
the auto-rotating identity issuer certificate (see `../linkerd/`).

This component is split into two internal stages because `ClusterIssuer`/
`Certificate` objects need cert-manager's own CRDs to already be registered —
a genuine bootstrap-ordering requirement, not a cosmetic split:

| Stage | Path | Flux Kustomization | Contents |
| ----- | ---- | ------------------- | -------- |
| release | `release/` | `cert-manager-release` | `Namespace/cert-manager`, `HelmRepository/jetstack`, `HelmRelease/cert-manager` (chart `v1.21.2`) |
| issuers | `issuers/` | `cert-manager-issuers` (`dependsOn: cert-manager-release`, `wait: true`) | shared `ClusterIssuer`s + the homelab root CA `Certificate` |

Linkerd's trust anchor + identity issuer `Certificate`/`Issuer` objects live in
`../linkerd/pki/`, not here — they belong to the linkerd component now.

Notes:

- CRDs are installed by the chart (`crds.enabled: true`, `crds.keep: true`), so a
  chart uninstall never garbage-collects the cluster's `Certificate`/`Issuer`
  objects.
- `startupapicheck` stays enabled: Flux only marks `cert-manager-release` Ready
  once the admission webhook actually answers, which is what keeps
  `cert-manager-issuers` and `linkerd-pki` (both `dependsOn` this release) from
  racing the webhook.
- cert-manager is deliberately **not** mesh-injected — it is a layer below the
  mesh; injecting it would create a bootstrap cycle.
- Other components must reuse `ClusterIssuer/homelab-ca` or
  `ClusterIssuer/selfsigned` rather than installing a second PKI.

See `../linkerd/README.md` for the full mTLS story.
