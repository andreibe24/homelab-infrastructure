# actions-runner-controller (topic 3 — ci-self-hosted-runners)

Ephemeral GitHub Actions runners inside the `homelab` cluster, driven by
**ARC's runner-scale-set generation** (`gha-runner-scale-set-controller` +
`gha-runner-scale-set`), with a rootless **BuildKit** sidecar for multi-arch
image builds.

| | |
| --- | --- |
| Controller chart | `oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller` `0.14.2` |
| Runner chart | `oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set` `0.14.2` |
| Namespaces | `arc-systems` (controller + listener), `arc-runners` (runner/build pods) — declared in `./namespaces.yaml` |
| Runner labels | `self-hosted`, `homelab-runners`, `linux`, `x64` |
| Auth | GitHub App (preferred) or PAT, in Secret `arc-github-app` (namespace `arc-runners`) |
| Container mode | `kubernetes` (container hooks) + rootless buildkitd sidecar |
| Scope | **one repository**, not the org, not the enterprise |

Chart versions are pinned deliberately; verify against the
[ARC releases](https://github.com/actions/actions-runner-controller/releases) and
let Renovate (topic 6) propose the bumps.

## Files

Everything this component owns is applied in one Flux Kustomization (single
stage — no CRD-dependent custom resources here, see `../README.md`):

```
infrastructure/actions-runner-controller/
├── namespaces.yaml                    arc-systems, arc-runners
├── helm-repositories.yaml             OCI chart source + bitnami-labs (sealed-secrets, unused for now)
├── helmrelease-controller.yaml        ARC controller (arc-systems)
├── helmrelease-runner-scale-set.yaml  scale set "homelab-runners" (arc-runners)
├── github-app-secret.stub.yaml        PLACEHOLDER — encrypt before committing
├── networkpolicy.yaml                 default-deny + egress-only allowances
├── rbac.yaml                          least-privilege Role/RoleBinding examples
├── binfmt-daemonset.yaml              QEMU handlers for arm64 emulation
├── kustomization.yaml
└── README.md                          (this file)

.github/workflows/                     lint.yaml, test.yaml, build-images.yaml
```

## Architecture

```
                    GitHub                                    homelab cluster
  ┌───────────────────────────────────┐        ┌──────────────────────────────────────────────┐
  │ repo andreibe24/homelab-infra...  │        │ ns arc-systems                               │
  │                                   │        │  ┌────────────────────────────────────────┐  │
  │  Actions service / job queue      │        │  │ gha-runner-scale-set-controller        │  │
  │  (scale-set "homelab-runners")    │        │  │  watches AutoscalingRunnerSet CRs      │  │
  │                                   │        │  └───────────────┬────────────────────────┘  │
  │                                   │        │                  │ creates                   │
  │                                   │        │  ┌───────────────▼────────────────────────┐  │
  │                                   │◀───────┼──┤ AutoscalingListener pod                │  │
  │   ① long-poll HTTPS (outbound     │  TLS   │  │  - reads Secret arc-github-app         │  │
  │      only, 443)                   │───────▶│  │  - mints an installation token (<1h)   │  │
  │   ② "1 job queued"                │        │  │  - asks for a JIT runner config        │  │
  └───────────────────────────────────┘        │  └───────────────┬────────────────────────┘  │
                                               │                  │ EphemeralRunner CR        │
                                               ├──────────────────┼───────────────────────────┤
                                               │ ns arc-runners   ▼                           │
                                               │  ┌────────────────────────────────────────┐  │
                                               │  │ runner pod  (ONE job, then deleted)    │  │
                                               │  │  ┌──────────────┐  ┌─────────────────┐ │  │
                                               │  │  │ runner       │  │ buildkitd       │ │  │
                                               │  │  │ run.sh       │──┤ rootless        │ │  │
                                               │  │  │ --ephemeral  │  │ tcp://127.0.0.1 │ │  │
                                               │  │  │ JIT config   │  │        :1234    │ │  │
                                               │  │  └──────┬───────┘  └────────┬────────┘ │  │
                                               │  │         │ k8s hooks         │          │  │
                                               │  └─────────┼───────────────────┼──────────┘  │
                                               │            ▼                   │             │
                                               │  ┌────────────────────┐        │             │
                                               │  │ job container pod  │        │             │
                                               │  │ (python/node image)│        │             │
                                               │  └────────────────────┘        │             │
                                               │     NetworkPolicy: egress only ▼             │
                                               └──────────────────────────┬───────────────────┘
                                                                          │ 443
                                                                          ▼
                                                       ghcr.io  (multi-arch manifest list)
                                                                          │
                                                                          ▼
                                                Flux ImagePolicy (topic 4) → cluster deploy
```

Traffic is **outbound only**: GitHub never connects into the homelab. The listener
holds an HTTPS long-poll open; when a job is queued, GitHub answers that request.
No inbound port, no VPN, no exposed webhook.

## Why `containerMode: kubernetes` + BuildKit (and not dind)

| | `dind` | `kubernetes` + rootless BuildKit **(chosen)** |
| --- | --- | --- |
| Privileges | `privileged: true` Docker daemon in every runner pod — a container escape is a node compromise | no privileged container anywhere; buildkitd runs as uid 1000 with `Unconfined` seccomp/AppArmor only (needed for nested user namespaces), not as root on the host |
| Docker socket | `/var/run/docker.sock` shared inside the pod; any workflow step can drive the daemon | no socket at all; buildx talks to buildkitd over `tcp://127.0.0.1:1234`, which is not reachable outside the pod |
| Job isolation | all `container:` jobs share one daemon | each `container:`/`services:` job is a separate pod created through the Kubernetes API by the runner's container hooks, subject to the same NetworkPolicy |
| Multi-arch | needs `docker buildx` + binfmt inside the privileged daemon | binfmt handlers registered once per node by a small DaemonSet; builders stay unprivileged |
| Cache | daemon-local, dies with the pod anyway | registry cache (`cache-to: type=registry`) survives pod deletion without keeping state on a node |
| Cost | one more privileged surface per job | one PVC per job (`kubernetesModeWorkVolumeClaim`), needs RWO storage |

Trade-offs accepted: job container images must be **glibc**-based (ARC injects its
own Node binary into the job pod, so `alpine` breaks), and emulated `arm64` builds
are several times slower than native ones. If that becomes painful, add an arm64
node and a second scale set instead of a bigger QEMU.

## Threat model: registration tokens vs. stolen `.credentials`

The classic, VM-style self-hosted runner works like this: you use a PAT with admin
rights on the repo to fetch a **registration token** (valid ~1 hour), run
`config.sh`, and the runner writes a **`.credentials`** file containing an OAuth
runner identity (a keypair + client id). That file:

* **does not expire** and is bound to nothing — not the hardware, not the IP.
  Copy it elsewhere, start the runner binary there, and GitHub's token service
  happily issues fresh OAuth tokens for it;
* lets the thief sit in your job queue as your runner, racing the real one for any
  job dispatched to matching labels (`self-hosted`, `linux`, …);
* exposes, for every job it wins: the checked-out code, **every `secrets.*` the
  workflow puts in the environment**, and whatever rights the runner's host user
  has (in the setup described in `development-environment/todo.md`: passwordless
  `sudo nginx -s reload` and write access to `/websites/my-website`);
* lets the thief execute whatever the next triggered workflow says — which is
  catastrophic if untrusted PRs can run on that runner.

What a stolen `.credentials` **cannot** do: push code, open PRs, change repo
settings, trigger workflows on demand, reach other repos/orgs, or read past jobs'
secrets. It is a *runner* identity, not an account identity.

The short-lived registration token is not the problem — its 1-hour lifetime is
exactly the point. The problem is the **long-lived artifact it produces**.

### How this deployment removes that artifact

* **Nothing is registered ahead of time, and no runner config is persisted.**
  The `AutoscalingListener` in `arc-systems` authenticates to GitHub with the
  GitHub App in `arc-github-app`, and for each queued job it requests a
  **just-in-time (JIT) runner configuration**. The JIT config is handed to a
  brand-new pod as a single-use, short-lived value; `config.sh` never runs, and no
  `.credentials` file is ever written to persistent storage.
* **`--ephemeral`, one job per pod.** After the job, the EphemeralRunner CR is
  deleted, the pod and its `emptyDir`/ephemeral PVC are destroyed, and the JIT
  identity is invalid. There is no file left to steal, and nothing to copy to
  another machine.
* **`minRunners: 0`.** When the queue is empty, zero runner pods exist, so the
  steady-state credential footprint is *zero*.
* **The App credential never enters a runner pod.** Only the controller/listener
  in `arc-systems` mounts `arc-github-app`; runner pods in `arc-runners` cannot
  read it (different namespace, no RBAC on secrets outside the chart's own
  hook-managed ones).
* **GitHub App > PAT.** Installation tokens expire in ≤1 hour and are scoped to
  the single installed repository with the minimum permission set
  (Administration: read & write — required to mint runner registration tokens —
  plus Metadata: read). A PAT, by contrast, carries its owner's rights across
  every repo they can reach and usually never expires. The App's private key is
  rotatable from the GitHub UI without touching any user account.
* **Repo-scoped, not org-scoped.** `githubConfigUrl` points at one repository, so
  even a fully compromised runner cannot pick up jobs from other repositories.

### The remaining risks, and what mitigates them here

| Risk | Mitigation in this repo |
| --- | --- |
| Untrusted PR code executing on a self-hosted runner | every PR-triggered job carries `if: github.event.pull_request.head.repo.full_name == github.repository`; keep *Require approval for all outside collaborators* enabled in repo settings; fork PRs simply do not run |
| Secrets exposed to a hostile job | `lint.yaml`/`test.yaml` reference **no** `secrets.*` and run with `permissions: contents: read`; the only writable token lives in `build-images.yaml`, which cannot be triggered by a PR |
| Long-lived registry PAT for pushes | not used — `GITHUB_TOKEN` with `packages: write`, job-scoped and short-lived, written to a `tmpfs` `DOCKER_CONFIG` that dies with the pod |
| Whoever edits a workflow file gets code execution | protect `.github/workflows/**` with CODEOWNERS + required review; treat workflow changes as privileged changes |
| Lateral movement from a runner into the LAN/cluster | `networkpolicy.yaml`: default-deny ingress, egress restricted to DNS, the API server and public-internet 443/80 with all RFC1918/CGNAT/link-local ranges excluded |
| Privilege escalation from a build | no privileged containers, no docker socket, `allowPrivilegeEscalation: false`, all capabilities dropped on the runner container |
| Over-broad cluster rights | `rbac.yaml` grants read-only verbs, namespaced, no `secrets`, no wildcards — and CD is done by Flux *pulling*, not by CI pushing |

For true domain-level egress (`github.com`, `ghcr.io` and nothing else), replace
the internet `ipBlock` rule with a Cilium `CiliumNetworkPolicy` using `toFQDNs`;
vanilla `NetworkPolicy` cannot express DNS names.

## Credentials: what you must do once

`arc-github-app` is **not** in git as plaintext — `github-app-secret.stub.yaml` is
a placeholder and is intentionally excluded from `kustomization.yaml`.

1. Create a GitHub App (owner = your account), permissions
   *Administration: read & write* + *Metadata: read*, install it on this
   repository only, generate a private key.
2. Encrypt the values with the repo-wide secret mechanism — **SOPS + age is the
   recommended default** (no extra controller; Flux decrypts natively via
   `decryption.secretRef` on `Kustomization/actions-runner-controller`), with
   sealed-secrets as the alternative. Full step-by-step instructions are in the
   header of `github-app-secret.stub.yaml`.
3. Add the encrypted file to `kustomization.yaml`.

Until that Secret exists, `HelmRelease/homelab-runners` stays not-Ready, which —
because `Kustomization/actions-runner-controller` uses `wait: true` — also holds
back `Kustomization/apps` (see `clusters/homelab/apps.yaml`). Either finish step
2 before pushing, or create the Secret out of band once
(`kubectl -n arc-runners create secret generic arc-github-app …`) so the
cluster converges while the GitOps path is being set up.

## Operating

```bash
# controller + listener
kubectl -n arc-systems get pods
kubectl -n arc-systems logs deploy/arc-gha-rs-controller

# the scale set and its runners
kubectl -n arc-runners get autoscalingrunnerset,ephemeralrunner,pods
kubectl -n arc-runners logs <runner-pod> -c buildkitd

# is the scale set registered with GitHub?
kubectl -n arc-runners get autoscalingrunnerset homelab-runners \
  -o jsonpath='{.status}' | jq
```

Verify the multi-arch path after a build:

```bash
docker buildx imagetools inspect ghcr.io/<owner>/webapp-backend:<tag>
# must list linux/amd64 and linux/arm64
```

## Interfaces with other topics

* **Topic 4 (cd-webapp)** consumes `ghcr.io/<owner>/webapp-{backend,frontend}`;
  tag contract and the matching `ImagePolicy` snippet are in
  [`.github/workflows/README.md`](../../../.github/workflows/README.md).
* **Topic 5 (observability)** can scrape the controller and listener metrics
  (`:8080/metrics`, enabled in `helmrelease-controller.yaml`) with a
  `ServiceMonitor` and alert on failed/stuck ephemeral runners.
* **Topic 6 (renovate)** bumps the two ARC chart versions, the runner image, the
  BuildKit image and the pinned actions — but must ignore the webapp images,
  which Flux image automation owns.
