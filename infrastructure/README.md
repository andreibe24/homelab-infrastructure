# infrastructure/

Cluster-wide plumbing, applied before `apps/`. Organised **by component**, not by
resource role: each subdirectory is one self-contained thing (cert-manager,
Linkerd, actions-runner-controller, observability, Renovate) and owns everything
it needs — its own `Namespace`(s), `HelmRepository`/`OCIRepository` source(s),
`HelmRelease`(s), and any custom resources (`Certificate`, `ClusterIssuer`,
`ServiceMonitor`, `PrometheusRule`, `AuthorizationPolicy`, `NetworkPolicy`, RBAC,
`CronJob`, ...). To see everything about a component, look in one directory.

```
infrastructure/
├── cert-manager/                 release -> issuers
├── linkerd/                      pki -> release -> policy
├── actions-runner-controller/    single stage
├── observability/                release -> crs
├── renovate/                     single stage
└── namespaces/                   NOT a component -- see below
```

Each component is reconciled by one or more Flux `Kustomization` objects defined
in `clusters/homelab/infrastructure.yaml`.

## Single stage vs. two/three internal stages

A component gets **one** top-level Kustomization (its directory root, one
`kustomization.yaml`) when nothing inside it has a genuine CRD-ordering
requirement. Ordering *within* the component is then expressed with
`HelmRelease.spec.dependsOn` between its own HelmReleases (helm-controller
handles that at the Helm level, no separate Flux Kustomization needed), and
plain objects with no CRD dependency (`NetworkPolicy`, RBAC, `DaemonSet`, ...)
just ship in the same apply. `actions-runner-controller` and `renovate` are
single-stage for this reason.

A component gets an **internal two- or three-stage split** — a subdirectory per
stage, each with its own `kustomization.yaml`, each stage its own Flux
`Kustomization` with `dependsOn` + `wait: true` on the previous one — only where
a custom resource genuinely depends on a CRD that exists only after a
HelmRelease has actually **installed** (not merely been applied):

| Component | Stages | Why |
| --------- | ------ | --- |
| `cert-manager` | `release` → `issuers` | `ClusterIssuer`/`Certificate` need cert-manager's own CRDs |
| `linkerd` | `pki` → `release` → `policy` | the trust-anchor `Certificate`/`Issuer` must exist and be Ready **before** `linkerd-control-plane`'s HelmRelease (it consumes the resulting Secret as a Helm value via `valuesFrom`); `AuthorizationPolicy`/`MeshTLSAuthentication` need the Linkerd CRDs installed by that same HelmRelease, so they run **after** it |
| `observability` | `release` → `crs` | `ServiceMonitor`/`PodMonitor`/`PrometheusRule`/`AlertmanagerConfig` need the Prometheus Operator CRDs bundled in `kube-prometheus-stack` |

This is a within-component staging detail, not a repo-wide resource-role split:
every stage still lives inside its owning component's directory, and no stage is
shared across components.

## Cross-component ordering

Ordering *between* components (e.g. Linkerd must come after cert-manager) is
expressed with `dependsOn` between the top-level (or first-stage) Flux
`Kustomization` objects in `clusters/homelab/infrastructure.yaml` — see that
file's header comment for the full dependency graph. There is no shared
"namespaces-first" or "sources-first" global stage any more: each component's
`Namespace` and Helm source(s) are applied as part of that component's own
(first) stage.

Duplicating a Helm repository URL under a different `HelmRepository` name in more
than one component is fine and expected — it is the price of not having a shared
cross-cutting sources file, and it keeps each component's manifests
self-contained.

## `webapp` Namespace — owned by `apps/`, not `infrastructure/`

There is no longer a namespaces exception here. `Namespace/webapp` is declared
directly in `apps/base/webapp/namespace.yaml`, next to the manifests that use
it, following the same "a component/app owns everything it needs" convention
as every directory in `infrastructure/`. `clusters/homelab/apps.yaml`
(`Kustomization/apps`) applies it — Namespace objects are always sorted ahead
of other kinds within a Kustomization apply, so no separate stage is required.

## Rules for new/changed components

- one directory per component under `infrastructure/`, each self-contained
- pin every chart to an exact `spec.chart.spec.version` so Renovate can bump it
- no plaintext secrets, ever: use SOPS-encrypted files or `SealedSecret`
- register every new Flux `Kustomization` (and its `dependsOn`/`wait`) in
  `clusters/homelab/infrastructure.yaml`
- only split a component into stages when a real CRD-ordering requirement
  exists (see the table above); default to a single stage
