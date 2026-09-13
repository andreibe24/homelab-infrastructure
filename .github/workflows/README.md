# .github/workflows/

CI pipelines for this monorepo. Every job runs **in-cluster**, on the ephemeral
GitHub Actions runners provided by actions-runner-controller — there is no
GitHub-hosted minute usage and no long-lived VM runner.

Infrastructure side of the story (ARC charts, BuildKit sidecar, network policy,
threat model):
[`infrastructure/actions-runner-controller/README.md`](../../infrastructure/actions-runner-controller/README.md).

## Pipelines

| Workflow | Triggers | Jobs | Where it runs |
| -------- | -------- | ---- | ------------- |
| `lint.yaml` | push to `main`, PR to `main`, manual | `manifests` (yamllint + `kustomize build` + kubeconform), `backend` (ruff check / ruff format / `manage.py check --deploy`), `frontend` (eslint + `tsc --noEmit`) | job containers (`python:3.13-slim`, `node:22-bookworm-slim`) launched as sibling pods by ARC's kubernetes hooks |
| `test.yaml` | push to `main`, PR to `main`, manual | `backend` (pytest + coverage, incl. the aioquic/HTTP-3 smoke test), `frontend` (vitest + production `vite build`) | same |
| `build-images.yaml` | push to `main`, tags `v*.*.*`, manual | matrix `backend` / `frontend`: multi-arch buildx build + push to GHCR | **directly in the runner pod**, so that the rootless BuildKit sidecar on `tcp://127.0.0.1:1234` is reachable |

`runs-on: [self-hosted, homelab-runners]` in every job. Those labels come from
`scaleSetLabels` on the `gha-runner-scale-set` HelmRelease; a job matches when its
`runs-on` labels are a subset of `[self-hosted, homelab-runners, linux, x64]`.

## Image contract (feeds topic 4 / Flux CD)

`build-images.yaml` pushes:

```
ghcr.io/<owner>/webapp-backend
ghcr.io/<owner>/webapp-frontend
```

with the tags

| Tag pattern | When | Purpose |
| ----------- | ---- | ------- |
| `main-<YYYYMMDDHHmmss>-<short-sha>` | pushes to `main` | **sortable**, this is what Flux `ImagePolicy` selects on |
| `sha-<short-sha>` | every build | human lookup / rollback |
| `<major>.<minor>.<patch>` and `<major>.<minor>` | tags `v*.*.*` | releases |
| `buildcache` | every build | BuildKit registry cache, *not* a runnable image |

Flux side (owned by topic 4):

```yaml
filterTags:
  pattern: '^main-(?P<ts>\d+)-[0-9a-f]+$'
  extract: '$ts'
policy:
  numerical:
    order: asc
```

Renovate (topic 6) must ignore these two images — Flux image automation owns them.

## Multi-arch builds without Docker

```
step (runner pod)                    buildkitd sidecar (same pod, rootless)
  docker/setup-buildx-action  ──────▶  --driver remote, tcp://127.0.0.1:1234
  docker/build-push-action    ──────▶  linux/amd64  : native
                                       linux/arm64  : QEMU, via the binfmt
                                                      handlers registered on the
                                                      node by the binfmt DaemonSet
                                              │
                                              └──▶ push to ghcr.io (credentials
                                                   read from $DOCKER_CONFIG)
```

No Docker daemon, no `docker.sock`, no privileged container. `docker/login-action`
is *not* used because there is no Docker CLI in a kubernetes-mode runner pod; the
workflow writes `$DOCKER_CONFIG/config.json` itself from the job's `GITHUB_TOKEN`.

## Security rules these files follow

1. **No `secrets.*` on untrusted input.** `lint.yaml` and `test.yaml` reference no
   secrets at all and run with `permissions: contents: read`.
2. **Fork PRs never touch the self-hosted pool.** Every PR-triggered job carries
   `if: github.event.pull_request.head.repo.full_name == github.repository`.
   Keep the repository setting *Actions → Fork pull request workflows from
   outside collaborators → Require approval for all outside collaborators* on top
   of it.
3. **The only writable token lives in `build-images.yaml`**, which cannot be
   triggered by a pull request (push/tag/manual only) and uses the job-scoped
   `GITHUB_TOKEN` with `packages: write` — not a PAT.
4. **Workflow files are protected content.** Require review from CODEOWNERS for
   `.github/workflows/**`; anyone who can change a workflow can run arbitrary code
   on the runners.
5. **Actions are pinned by major tag** so Renovate can bump them; switch to
   full-SHA pinning if supply-chain paranoia outweighs churn.
6. `src/webapp/` is created by topic 4. Until it exists, the source-dependent jobs
   detect the missing directory and skip instead of failing.
