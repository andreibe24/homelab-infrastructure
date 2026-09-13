# Renovate (topic 6) — daily dependency updates

Renovate keeps every pinned third-party version in this repository fresh: Helm
chart versions in Flux `HelmRelease` objects, container image tags in Kubernetes
manifests and Dockerfiles, GitHub Actions versions in `.github/workflows/`, and
the Python/npm pins of the webapp source.

| | |
| --- | --- |
| Config | [`/renovate.json`](../../../renovate.json) (repo root) |
| Runtime | `CronJob/renovate` in namespace `renovate`, daily at **02:00** Europe/Bucharest |
| Image | `ghcr.io/renovatebot/renovate:44.83.0` (pinned) |
| Credentials | fine-grained GitHub PAT in `Secret/renovate-token` (encrypted, not committed) |
| Effect on the cluster | **none directly** — Renovate only opens pull requests |

## Files

| File | Purpose |
| --- | --- |
| `cronjob.yaml` | the daily Renovate run |
| `rbac.yaml` | `ServiceAccount` only — see [RBAC](#rbac-why-there-is-almost-none) |
| `secret.sops.yaml.example` | template for the GitHub token; encrypt before committing the real one |
| `kustomization.yaml` | stage registration |

There is **no `infrastructure/configs/renovate/` directory**: Renovate ships no
CRDs and needs no custom resources, so there is nothing that must wait for a
controller to become Ready. Everything is applied in the `infra-controllers`
stage.

## Why a self-hosted CronJob instead of the Renovate GitHub App

The hosted [Mend Renovate App](https://github.com/apps/renovate) would be less
work — install it, commit `renovate.json`, done. This homelab runs it in-cluster
anyway, for three reasons:

1. **No third-party app on a personal account.** The GitHub App needs
   read/write access to the repository and runs on infrastructure we do not
   control. A self-hosted job uses a token we mint, scope, rotate and revoke
   ourselves, and the bot's network path is fully visible.
2. **Control over when and how it runs.** The schedule, the Renovate version,
   the log level and the resource envelope are all declared in git and changed
   through the same review flow as everything else. When a Renovate release
   regresses, the fix is a one-line revert of the image tag.
3. **It is the point of the exercise.** A homelab exists to practise the
   patterns: `CronJob` + `ServiceAccount` + encrypted `Secret` + GitOps
   registration is exactly the shape of every batch workload that follows.

The trade-off is honest: self-hosting means we own the failure mode. If the pod
crashloops, nobody emails us. That is why topic 5 alerts on
`kube_job_status_failed` for this CronJob — it is the canonical "CronJob poller
failure" alert in the observability topic.

## The daily schedule (two places, keep them in sync)

* `CronJob.spec.schedule: "0 2 * * *"` with `timeZone: Europe/Bucharest` — when
  the process starts.
* `schedule: ["after 2am and before 4am"]` in `renovate.json` — when Renovate
  considers itself *allowed* to open PRs.

Renovate re-checks its own schedule at runtime, so if the two ever drift apart
the job will start, log `Skipping branch creation as not within schedule` and do
nothing. `concurrencyPolicy: Forbid` plus `restartPolicy: Never` and
`backoffLimit: 1` mean a slow or failing run is never stacked on top of the next
one.

Once a day is deliberate: dependency noise is the main reason people start
ignoring bot PRs. One batch per night, grouped, is reviewable over coffee.

## Token scoping / least privilege

`RENOVATE_TOKEN` is a **fine-grained** PAT limited to this single repository with
exactly two permissions:

* `Contents: read & write` — push the `renovate/*` update branches.
* `Pull requests: read & write` — open, update and (for the patch group) merge.

Explicitly **not** granted: `workflow` (a classic-PAT scope that would let the
bot rewrite CI), any organisation-level permission, `admin`, or package
registry write. Renovate edits the *contents* of workflow files, which
`Contents: write` covers for a fine-grained token — there is no need for the
much broader classic scope.

The optional `GITHUB_COM_TOKEN` is a separate, **zero-scope** token used only to
read public changelogs without hitting the anonymous API rate limit. Even if it
leaked it grants nothing.

Both live in `Secret/renovate-token`, encrypted with the repo-wide mechanism
chosen by topic 3 (SOPS+age or SealedSecrets). Nothing in this directory ever
contains a plaintext credential — `secret.sops.yaml.example` holds placeholders
and is excluded from `kustomization.yaml`.

### RBAC: why there is almost none

Renovate talks to GitHub and to public registries. It never reads a ConfigMap,
never lists a Pod, never touches the Kubernetes API. So `rbac.yaml` contains a
`ServiceAccount` and **no Role, RoleBinding or ClusterRole at all**, and the pod
sets `automountServiceAccountToken: false` so not even an API token is mounted.
A compromised Renovate container holds one repo-scoped GitHub PAT and zero
cluster credentials.

The dedicated (privilege-free) ServiceAccount exists instead of the namespace
`default` purely so the workload has its own identity for audit logs and
NetworkPolicy/admission selectors.

## Division of labour with Flux image automation

Two automations write to this repo, and they must never touch the same lines:

| Dependency | Owned by | Mechanism |
| --- | --- | --- |
| `ghcr.io/<org>/webapp-backend`, `ghcr.io/<org>/webapp-frontend` | **Flux image automation** (topic 4) | `ImageRepository` → `ImagePolicy` → `ImageUpdateAutomation` commits the new tag straight to `main` |
| Everything else: Helm charts, third-party images, GitHub Actions, Python/npm deps | **Renovate** (this topic) | pull request |

`renovate.json` therefore carries an explicit `enabled: false` package rule
matching `/^ghcr\.io/[^/]+/webapp-(backend|frontend)$/`. Without it, CI pushes
`sha-<ts>`, Flux commits that tag to the Deployment, and Renovate would then open
a PR proposing a different "newer" tag for the same image — two bots fighting
over one line, with a rebase loop as the prize. This is the cross-topic contract
in `PLAN.md` §4.6.

Renovate *does* still manage the webapp's **base** images (`python:…`,
`node:…`, `nginx:…` in `src/webapp/*/Dockerfile`) — those are third-party.

## How updates actually reach the cluster (the review gate)

Renovate applies **nothing**. The full path is:

```
CronJob 02:00 → Renovate opens/updates PRs → CI (topic 3) lints & validates
              → a human reviews and merges to main
              → Flux GitRepository picks up the merge commit
              → infra-* / apps Kustomizations reconcile the change
```

The GitOps review gate is preserved because the cluster only ever follows
`main`. A Renovate PR that is never merged has zero effect on the cluster.

What lands in the repo each night:

* **one grouped PR for all patch updates** — automerged;
* **one grouped "digest pins" PR** (image digests and the GitHub Action SHAs
  pinned by `helpers:pinGitHubActionDigests`) — automerged;
* **one grouped PR for all minor updates** — human merges;
* **one PR per major update**, labelled `major-update` / `needs-review`;
* **one PR per CRD-bearing chart** (cert-manager, Linkerd, ARC,
  kube-prometheus-stack) for minor and major bumps — never grouped, because a
  chart minor can ship a CRD schema change that deserves its own rollout;
* a **Dependency Dashboard** issue listing everything pending, rate-limited or
  ignored.

### Why automerge only for patch level

Patch releases are by semver contract backwards-compatible bug and security
fixes. Hand-reviewing twenty of them a month trains you to rubber-stamp, which
is worse than not reviewing at all. Minor and major releases can change chart
defaults, CRD schemas or container entrypoints, so they always stop at a human.

Two guard rails keep the automerged group safe:

* `minimumReleaseAge: "3 days"` — a release that gets yanked within the first
  days never reaches a PR.
* `platformAutomerge: true` — GitHub performs the merge, and only once the
  required status checks (topic 3's lint/test workflows) are green. Make those
  checks *required* on `main`, otherwise automerge merges unverified code.

Patch and minor are two separate groups on purpose: a mixed group takes the
highest update type (minor) and would therefore never automerge.

To pause everything, comment out the CronJob or set `"enabled": false` in
`renovate.json` — the repo keeps working, it just stops receiving updates.

## Bootstrapping fun fact: Renovate updates Renovate

The CronJob image is pinned to an exact tag, and `renovate.json` enables the
`kubernetes` manager over `infrastructure/**.yaml`. That means Renovate scans
`cronjob.yaml`, finds `ghcr.io/renovatebot/renovate:44.83.0`, and opens a PR to
upgrade *itself* — which, once merged, is rolled out by Flux at the next
reconciliation. It is deliberately excluded from the grouped PRs
(`groupName: renovate self-update`) and never automerged, so a bad Renovate
release is a single-commit revert rather than an untangling exercise.

Same story for the Flux manager and the `flux-system` components: pin everything,
and the bot maintains the pins.

## Operating it

```bash
# trigger a run by hand (does not disturb the schedule)
kubectl -n renovate create job --from=cronjob/renovate renovate-manual-$(date +%s)

# watch it
kubectl -n renovate logs -l app.kubernetes.io/name=renovate --tail=200 -f

# more verbosity for a debugging run: LOG_LEVEL=debug in cronjob.yaml,
# or a dry run that opens nothing:
#   RENOVATE_DRY_RUN=full
```

Common failures:

| Symptom | Cause |
| --- | --- |
| `Repository is not enabled` / config errors | `RENOVATE_REPOSITORIES` still holds the `<github-org>` placeholder |
| `Authentication failure` | PAT expired (fine-grained PATs always expire) or missing one of the two permissions |
| No PRs, log says not in schedule | CronJob `schedule`/`timeZone` drifted from `renovate.json`'s `schedule` |
| `EACCES` / read-only filesystem | a new Renovate version writes outside `/tmp`; extend the `workdir` mounts |
