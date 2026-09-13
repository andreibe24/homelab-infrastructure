# homelab-infrastructure — architecture & implementation plan

GitOps repository for a single Kubernetes cluster named **`homelab`**, reconciled by
**FluxCD v2**. Everything in the cluster is expressed as Kubernetes objects / CRDs in
this repo; nothing is applied by hand.

The work is split into **6 topics**, each implemented by a dedicated agent. Topic 1
(cluster-bootstrap) is **already implemented** in this commit and defines the contract
the other five plug into: topics 2–6 currently exist as a directory plus a `PLAN.md`
brief.

---

## 1. Architecture

```
                    git push
                       │
              ┌────────▼─────────┐
              │ GitRepository    │  flux-system (created by `flux bootstrap`)
              │ flux-system      │
              └────────┬─────────┘
                       │
           Kustomization/flux-system  → path ./clusters/homelab
                       │
        ┌──────────────┴───────────────┐
        │                              │
 infrastructure.yaml               apps.yaml
        │                              │
 one or more Flux Kustomizations       │
 PER COMPONENT (wait: true),           │
 dependsOn-chained only where a        │
 genuine CRD-ordering need exists      │
 (cert-manager, linkerd,               │
 observability); the rest              │
 (actions-runner-controller,           │
 renovate) run in parallel             │
        └──────────────┬───────────────┘
                       ▼
                 Kustomization/apps  → path ./apps/homelab
```

Design rules:

- **Flux monorepo pattern**: `clusters/<cluster>/` holds only Flux `Kustomization`
  entrypoints; the actual manifests live in `infrastructure/` and `apps/` and are
  cluster-agnostic, so a second cluster is a new `clusters/<name>/` directory only.
- **Organised by component, not by resource role**: `infrastructure/<component>/`
  is a single self-contained directory owning its own `Namespace`(s), Helm
  source(s), `HelmRelease`(s) and any custom resources. A component only gets an
  internal multi-stage split (its own subdirectories, each its own Flux
  `Kustomization` chained with `dependsOn` + `wait: true`) where a custom
  resource genuinely depends on a CRD that a HelmRelease in the same component
  has not yet installed — see `infrastructure/README.md`.
- **No plaintext secrets**: SOPS-encrypted files or `SealedSecret` only. Topic 3
  makes the repo-wide choice and bootstraps the mechanism.
- **Everything pinned**: exact chart versions and image tags, so Renovate (topic 6)
  and Flux image automation (topic 4) can propose updates as commits/PRs.
- **App source vs. app manifests are separate**: source in `src/webapp/`, manifests in
  `apps/`. CI (topic 3) builds from `src/`, Flux deploys from `apps/`.

---

## 2. Directory tree

```
homelab-infrastructure/
├── PLAN.md                                 ← this file
├── README.md
├── LICENSE
├── renovate.json                           (topic 6 creates)
├── .sops.yaml                              (topic 3 creates, if SOPS is chosen)
├── .github/
│   └── workflows/                          (topic 3) lint.yaml, test.yaml, build-images.yaml
│       └── README.md
├── clusters/
│   └── homelab/                            ← TOPIC 1 (implemented)
│       ├── flux-system/                    managed by `flux bootstrap`
│       │   └── README.md                   bootstrap instructions / placeholder
│       ├── infrastructure.yaml             one or more Flux Kustomizations per component
│       └── apps.yaml                       Flux Kustomization → ./apps/homelab
├── infrastructure/                         ← organised by COMPONENT, not by resource role
│   ├── README.md                           per-component layout + internal-staging convention
│   ├── cert-manager/                       (topic 2) release/ -> issuers/
│   │   ├── README.md
│   │   ├── release/                        Namespace, HelmRepository, HelmRelease
│   │   └── issuers/                        ClusterIssuers (need cert-manager's CRDs)
│   ├── linkerd/                            (topic 2) pki/ -> release/ -> policy/
│   │   ├── README.md
│   │   ├── pki/                            Namespace/linkerd, trust anchor + identity issuer Certificates
│   │   ├── release/                        Namespace/linkerd-viz, HelmRepository, linkerd-crds/control-plane/viz HelmReleases
│   │   └── policy/                         AuthorizationPolicy / MeshTLSAuthentication
│   ├── actions-runner-controller/          (topic 3) single stage
│   │   └── README.md
│   ├── observability/                      (topic 5) release/ -> crs/
│   │   ├── README.md
│   │   ├── release/                        Namespace, HelmRepositories, kube-prometheus-stack HelmRelease
│   │   └── crs/                            ServiceMonitors, PodMonitors, PrometheusRules, AlertmanagerConfig, dashboard ConfigMap
│   ├── renovate/                           (topic 6) single stage
│   │   └── README.md
├── apps/
│   ├── README.md
│   ├── base/
│   │   └── webapp/                         (topic 4) Namespace/webapp lives here too
│   └── homelab/
│       └── kustomization.yaml              (topic 1; cluster overlay entrypoint)
├── src/                                    (topic 4 creates)
│   └── webapp/
│       ├── backend/                        Django + aioquic/Hypercorn + Dockerfile
│       └── frontend/                       Vite + nginx Dockerfile
└── development-environment/                pre-existing dev-machine docs — DO NOT TOUCH
```

---

## 3. Topics

| # | Topic | Writes to | Brief |
| - | ----- | --------- | ----- |
| 1 | **cluster-bootstrap** | `clusters/homelab/`, `infrastructure/README.md` | **Done.** Flux entrypoints and the per-component layout convention. |
| 2 | **linkerd-mtls** | `infrastructure/cert-manager/`, `infrastructure/linkerd/` | `infrastructure/linkerd/README.md` |
| 3 | **ci-self-hosted-runners** | `infrastructure/actions-runner-controller/`, `.github/workflows/` | `infrastructure/actions-runner-controller/README.md` |
| 4 | **cd-webapp** | `src/webapp/`, `apps/base/webapp/`, `apps/homelab/` | `apps/base/webapp/PLAN.md` |
| 5 | **observability** | `infrastructure/observability/` | `infrastructure/observability/README.md` |
| 6 | **renovate** | `renovate.json`, `infrastructure/renovate/` | `infrastructure/renovate/README.md` |

**1 — cluster-bootstrap.** Flux monorepo layout, the per-component Flux
Kustomization graph in `clusters/homelab/infrastructure.yaml`, and the
`infrastructure/README.md` convention every other topic follows: one
self-contained directory per component, split into internal stages only where a
real CRD-ordering requirement exists.

**2 — linkerd-mtls.** cert-manager (its own `release`/`issuers` stages) +
`linkerd-crds` + `linkerd-control-plane` HelmReleases, trust anchor and identity
issuer `Certificate`s, optional `linkerd-viz`. Key caveat captured in its plan:
Linkerd does not proxy UDP, so the webapp's QUIC port must skip the mesh.

**3 — ci-self-hosted-runners.** ARC `gha-runner-scale-set-controller` + runner scale
sets, GitHub App/PAT credentials via SOPS or SealedSecrets, BuildKit (or Kaniko) for
multi-arch builds, and the `.github/workflows` lint/test/build pipelines that publish
images to GHCR. This topic also owns the repo-wide secret-management decision.

**4 — cd-webapp.** Django + aioquic/Hypercorn backend (HTTP/3 over UDP) and a
Vite/nginx frontend: source skeletons with Dockerfiles, Deployments, TCP+UDP Services,
ConfigMaps, cert-manager `Certificate`, `HTTPRoute`/Ingress, and Flux
`ImageRepository`/`ImagePolicy`/`ImageUpdateAutomation` for continuous deployment.

**5 — observability.** `kube-prometheus-stack` (Prometheus, Alertmanager, Grafana),
ServiceMonitors/PodMonitors for the webapp, Linkerd and ARC, a sample Grafana
dashboard ConfigMap, and `PrometheusRule`s + `AlertmanagerConfig` routing incidents
(notably CronJob poller failures) to a Slack/webhook placeholder.

**6 — renovate.** Daily dependency updates: `renovate.json` at the repo root plus a
self-hosted `CronJob` (or the Helm chart) with RBAC and an encrypted token, scoped so
it does not fight Flux image automation over the webapp's own images.

---

## 4. Cross-topic contracts

1. **Secret mechanism** (SOPS+age vs. SealedSecrets) is decided by topic 3 first;
   topics 4, 5 and 6 follow it. SOPS additionally requires `decryption.secretRef` on
   the affected Flux Kustomizations in `clusters/homelab/infrastructure.yaml`.
2. **Namespaces**: each component declares its own `Namespace`(s) inside its own
   directory (in the earliest stage that needs them); there is no shared
   namespaces file. `apps/base/webapp` (topic 4) follows the same convention —
   `Namespace/webapp` lives in `apps/base/webapp/namespace.yaml`, applied by
   `Kustomization/apps`, not by any `infrastructure/` stage.
3. **Helm sources**: each component declares its own `HelmRepository`/
   `OCIRepository` object(s) inside its own directory. Duplicating a repository
   URL under a different `HelmRepository` name in more than one component is
   fine and expected.
4. **Stage registration**: every topic must register its component's Flux
   `Kustomization`(s) in `clusters/homelab/infrastructure.yaml`, with
   `dependsOn`/`wait: true` between internal stages where its own README
   documents a genuine CRD-ordering requirement, otherwise its manifests are
   inert.
5. **Version pinning** is mandatory for Renovate to work.
6. **Image pipeline**: topic 3 publishes → topic 4 consumes via `ImagePolicy`;
   Renovate must ignore those images.
7. **Bootstrap prerequisite**: Flux must be bootstrapped with
   `--components-extra=image-reflector-controller,image-automation-controller`
   for topic 4 (see `clusters/homelab/flux-system/README.md`).
