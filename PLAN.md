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
 infra-namespaces                      │
        ▼                              │
 infra-sources                         │
        ▼                              │
 infra-controllers  (HelmReleases, wait: true)
        ▼                              │
 infra-configs      (CRs needing those CRDs)
        └──────────────┬───────────────┘
                       ▼
                 Kustomization/apps  → path ./apps/homelab
```

Design rules:

- **Flux monorepo pattern**: `clusters/<cluster>/` holds only Flux `Kustomization`
  entrypoints; the actual manifests live in `infrastructure/` and `apps/` and are
  cluster-agnostic, so a second cluster is a new `clusters/<name>/` directory only.
- **Ordered layers via `dependsOn` + `wait: true`**: namespaces → sources →
  controllers → configs → apps. This is what guarantees CRDs (Linkerd, ARC,
  Prometheus Operator, cert-manager) exist before any custom resource is applied.
- **Shared objects are centralised**: all `Namespace` objects live in
  `infrastructure/namespaces/`, all `HelmRepository` objects in
  `infrastructure/sources/`. Topic agents edit those shared files rather than
  creating duplicates, which avoids ownership conflicts and pruning surprises.
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
│       ├── infrastructure.yaml             4 ordered Flux Kustomizations
│       └── apps.yaml                       Flux Kustomization → ./apps/homelab
├── infrastructure/                         ← TOPIC 1 skeleton, topics 2/3/5/6 fill in
│   ├── README.md
│   ├── namespaces/                         (topic 1, implemented)
│   │   ├── namespaces.yaml
│   │   └── kustomization.yaml
│   ├── sources/                            (topic 1, implemented)
│   │   ├── helm-repositories.yaml
│   │   ├── oci-repositories.yaml
│   │   └── kustomization.yaml
│   ├── controllers/
│   │   ├── kustomization.yaml              (topic 1; entries pre-listed as comments)
│   │   ├── cert-manager/PLAN.md            (topic 2)
│   │   ├── linkerd/PLAN.md                 (topic 2)
│   │   ├── actions-runner-controller/PLAN.md (topic 3)
│   │   ├── observability/PLAN.md           (topic 5)
│   │   └── renovate/PLAN.md                (topic 6)
│   └── configs/
│       ├── kustomization.yaml              (topic 1; entries pre-listed as comments)
│       ├── linkerd/                        (topic 2 creates)
│       ├── actions-runner-controller/      (topic 3 creates)
│       ├── observability/                  (topic 5 creates)
│       └── renovate/                       (topic 6 creates)
├── apps/
│   ├── README.md
│   ├── base/
│   │   └── webapp/PLAN.md                  (topic 4)
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
| 1 | **cluster-bootstrap** | `clusters/homelab/`, `infrastructure/{namespaces,sources}`, stage `kustomization.yaml` files, `apps/homelab/` | **Done.** Flux entrypoints, layer ordering, shared namespaces and Helm sources. |
| 2 | **linkerd-mtls** | `infrastructure/controllers/{cert-manager,linkerd}/`, `infrastructure/configs/linkerd/` | `infrastructure/controllers/linkerd/PLAN.md` |
| 3 | **ci-self-hosted-runners** | `infrastructure/controllers/actions-runner-controller/`, `infrastructure/configs/actions-runner-controller/`, `.github/workflows/` | `infrastructure/controllers/actions-runner-controller/PLAN.md` |
| 4 | **cd-webapp** | `src/webapp/`, `apps/base/webapp/`, `apps/homelab/` | `apps/base/webapp/PLAN.md` |
| 5 | **observability** | `infrastructure/controllers/observability/`, `infrastructure/configs/observability/` | `infrastructure/controllers/observability/PLAN.md` |
| 6 | **renovate** | `renovate.json`, `infrastructure/configs/renovate/` (and/or `controllers/renovate/`) | `infrastructure/controllers/renovate/PLAN.md` |

**1 — cluster-bootstrap.** Flux monorepo layout, the four ordered infrastructure
Kustomizations plus the apps Kustomization, all shared namespaces (with mesh
injection annotations pre-set) and all shared `HelmRepository`/OCI sources.

**2 — linkerd-mtls.** cert-manager + `linkerd-crds` + `linkerd-control-plane`
HelmReleases, trust anchor and identity issuer `Certificate`s, optional `linkerd-viz`.
Key caveat captured in its plan: Linkerd does not proxy UDP, so the webapp's QUIC port
must skip the mesh.

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
2. **Namespaces**: only `infrastructure/namespaces/namespaces.yaml` may declare them.
3. **Helm sources**: only `infrastructure/sources/` may declare them.
4. **Stage registration**: every topic must uncomment its directory in
   `infrastructure/controllers/kustomization.yaml` and/or
   `infrastructure/configs/kustomization.yaml`, otherwise its manifests are inert.
5. **Version pinning** is mandatory for Renovate to work.
6. **Image pipeline**: topic 3 publishes → topic 4 consumes via `ImagePolicy`;
   Renovate must ignore those images.
7. **Bootstrap prerequisite**: Flux must be bootstrapped with
   `--components-extra=image-reflector-controller,image-automation-controller`
   for topic 4 (see `clusters/homelab/flux-system/README.md`).
