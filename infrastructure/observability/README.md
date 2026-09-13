# Observability — Prometheus, Alertmanager, Grafana (topic 5)

Everything metrics-related in the `homelab` cluster comes from a **single**
`HelmRelease`: `kube-prometheus-stack` in the `observability` namespace.

| Path | Flux Kustomization | Contents |
| ---- | ------------------- | -------- |
| `release/` (here) | `observability-release` | `Namespace/observability`, Helm sources, the HelmRelease + secret template |
| `crs/` | `observability-crs` (`dependsOn: observability-release`, `wait: true`) | ServiceMonitors, PodMonitors, PrometheusRules, AlertmanagerConfig, dashboard ConfigMap |

The split is not cosmetic: `Kustomization/observability-crs` `dependsOn`
`observability-release` with `wait: true`, which is what guarantees the
Prometheus Operator CRDs exist before any `ServiceMonitor` is applied.

---

## 1. Topology

```
          ┌──────────────────────── namespace: observability ─────────────────────────┐
          │                                                                           │
          │   Prometheus Operator ──watches──► ServiceMonitor / PodMonitor /          │
          │        (CRD controller)            PrometheusRule / AlertmanagerConfig    │
          │            │ generates                                                    │
          │            ▼                                                              │
          │      Prometheus (StatefulSet, 20Gi PVC, 15d)                              │
          │        │  scrapes                         │ evaluates rules               │
          │        │                                  ▼                               │
          │        │                            Alertmanager (2Gi PVC)                │
          │        │                                  │ Slack + generic webhook       │
          │        │                                  ▼  (URLs from a Secret)         │
          │        │                            chat / phone push                     │
          │        ▼                                                                  │
          │      Grafana  ◄── sidecar imports ConfigMaps labelled grafana_dashboard=1  │
          └───────────────────────────────────────────────────────────────────────────┘
                     ▲            ▲               ▲                 ▲
         kubelet/cAdvisor   kube-state-metrics  node-exporter   your workloads
                                                               (webapp, linkerd, ARC)
```

Bundled sub-charts (one release, one upgrade): `grafana`, `kube-state-metrics`,
`prometheus-node-exporter`, plus the operator CRDs.

**Decision — bundled Grafana.** `grafana.enabled: true` instead of a separate
HelmRelease from `HelmRepository/grafana`: the chart already provisions the
Prometheus + Alertmanager datasources, the dashboard sidecar and the upstream
Kubernetes dashboards. The `grafana` Helm source stays in
`release/helm-repositories.yaml` for a future Loki/Promtail split.

**Decision — control-plane scrape jobs off.** `kubeEtcd`, `kubeControllerManager`,
`kubeScheduler` and `kubeProxy` are disabled (and their default rules with them)
because a typical homelab control plane does not bind those metrics endpoints to
the node IP. Leaving them on produces permanently-firing `TargetDown` alerts, which
trains you to ignore alerts. Enable them the day you expose the endpoints.

**Decision — Prometheus is not mesh-injected.** The `observability` namespace
carries `linkerd.io/inject: enabled`, but the Prometheus pod overrides it with
`linkerd.io/inject: disabled` (`prometheusSpec.podMetadata`). Prometheus talks to
thousands of pod IPs on arbitrary ports, including the Linkerd proxy admin port
4191 which is deliberately outside the mesh. Grafana and Alertmanager stay meshed.

---

## 2. How a workload gets scraped

1. A topic ships a `ServiceMonitor` (Service-backed workloads) or a `PodMonitor`
   (no Service, e.g. ARC listeners) anywhere in the cluster.
2. The operator sees it because this release sets, for every selector type:

   ```yaml
   serviceMonitorSelectorNilUsesHelmValues: false   # + podMonitor/rule/probe/scrapeConfig
   serviceMonitorSelector: {}                       # any labels
   serviceMonitorNamespaceSelector: {}              # any namespace
   ```

   That is the cross-topic contract: **no `release: kube-prometheus-stack` label is
   required.** Other topics can add monitors without knowing this release exists.
3. The operator regenerates the Prometheus scrape config and the config-reloader
   sidecar hot-reloads it — no restart.

`job` label conventions worth remembering when writing alerts:
* `ServiceMonitor` without `jobLabel` → `job` = **Service name** (`webapp-backend`).
* `PodMonitor` → `job` = `<namespace>/<podmonitor-name>` (`linkerd/linkerd-proxy`).
* Sub-charts set theirs explicitly: `kube-state-metrics`, `node-exporter`.

Monitors shipped by this topic (all label-selector based and **forward-looking** —
they are inert until topics 2/3/4 land their workloads, and start working on their
own afterwards):

| Object | Target |
| ------ | ------ |
| `ServiceMonitor/webapp-backend` | Django + Hypercorn `/metrics` on the **TCP** port (QUIC/UDP cannot be scraped) |
| `ServiceMonitor/webapp-frontend` | nginx exporter port |
| `PodMonitor/linkerd-control-plane` | destination / identity / proxy-injector, port `admin-http` |
| `PodMonitor/linkerd-proxy` | every meshed pod's `linkerd-admin` (4191): RPS, latency, `tls=` label |
| `PodMonitor/arc-controller`, `PodMonitor/arc-runner-listener` | ARC `:8080` metrics (`gha_*`) |
| `PodMonitor/arc-runners` | optional exporter sidecar on ephemeral runner pods |

---

## 3. Alerting — and the "CronJob poller fails" case

From `development-environment/todo.md`:

> ## alertmanager
> notify incidents, **k8s cronjob poller fails**, etc.

`crs/prometheusrule-cronjob-failures.yaml` is the
direct answer. It is built on kube-state-metrics series and covers the four ways a
poller actually dies:

| Alert | Expression idea | Catches |
| ----- | --------------- | ------- |
| `CronJobFailed` | `(kube_job_status_failed > 0) * on(namespace,job_name) group_left(owner_name) kube_job_owner{owner_kind="CronJob"}` | a run exited non-zero |
| `CronJobNotScheduledRecently` | `time() - kube_cronjob_status_last_schedule_time > 24h` | the schedule never fired |
| `CronJobNoRecentSuccess` | `time() - kube_cronjob_status_last_successful_time > 48h` | every run is evicted/OOM-killed |
| `CronJobRunningTooLong` | `time() - kube_job_status_start_time > 1h and kube_job_status_active > 0` | a **hung** poller — the silent one |
| `RenovateCronJobFailed` / `RenovateCronJobStale` | same, scoped to `namespace="renovate"` | topic 6's daily update poller |

Plus `prometheusrule-platform.yaml` (pod restarts/CrashLoopBackOff/OOMKilled, node
Memory/Disk pressure and NotReady, filesystem nearly full, Linkerd proxy and
control-plane down, unencrypted mesh traffic, identity cert expiry) and
`prometheusrule-webapp.yaml` (backend down, 5xx burn rate, p95 latency, QUIC
handshake failures, cert expiry).

### Routing

`AlertmanagerConfig/homelab-alerts` (CRD-based, not a hand-rolled
`alertmanager.yaml` Secret) is picked up because the Alertmanager CR selects every
`AlertmanagerConfig` in this namespace. Two details make it work:

* `alertmanagerConfigMatcherStrategy.type: None` in the HelmRelease — the operator
  default (`OnNamespace`) would inject `namespace="observability"` into every route
  and silently drop alerts about `webapp`, `renovate`, `arc-*`, `kube-system`.
* the chart's base config has `route.routes: []` — its default contains a
  `Watchdog → null` child that is evaluated *before* CR routes and would swallow
  the dead-man's-switch.

Resulting delivery matrix (verified with `amtool config routes test`):

| Alert | Receivers |
| ----- | --------- |
| `Watchdog` | `generic-webhook` only (5m repeat — alarm when it *stops* arriving) |
| any `severity=critical` | `generic-webhook` **and** Slack |
| `category=cronjob` | Slack, grouped by owning CronJob, 6h repeat |
| `severity=info` | Slack, 24h repeat |
| everything else | Slack |

### Webhook secret — never committed

Both receivers read their URL from `Secret/alertmanager-webhooks` in
`observability` (`slack-webhook-url`, `generic-webhook-url`). A Slack incoming
webhook URL *is* the credential. `./secrets.example.yaml` is a **template only**
(not referenced from `kustomization.yaml`); copy it, fill in the real URL and
encrypt it with the repo-wide mechanism chosen by topic 3 (SOPS + age or
SealedSecrets), then add the encrypted file to `kustomization.yaml`. With SOPS,
remember `decryption.secretRef` on the Flux Kustomization in
`clusters/homelab/infrastructure.yaml`.

Test the whole path end-to-end once the Secret exists:

```bash
kubectl -n observability port-forward svc/kube-prometheus-stack-alertmanager 9093 &
amtool --alertmanager.url=http://localhost:9093 alert add \
  alertname=CronJobFailed category=cronjob severity=critical namespace=renovate \
  summary="test from amtool"
```

---

## 4. Grafana

* **Credentials**: `grafana.admin.existingSecret: grafana-admin-credentials`
  (keys `admin-user` / `admin-password`). No password is in this repo — the chart's
  own Secret template is bypassed entirely. Create the Secret the same way as the
  webhook one (see `./secrets.example.yaml`).
* **Dashboards**: the sidecar watches **all** namespaces for ConfigMaps labelled
  `grafana_dashboard: "1"` and imports them live; the `grafana_folder` annotation
  chooses the folder. This repo ships `Homelab — Cluster Overview`
  (`crs/dashboard-cluster-overview-configmap.yaml`):
  node CPU/memory/disk, pod restarts, failed CronJob-owned Jobs, time since each
  CronJob's last success, webapp RPS by status and Linkerd success rate. The
  upstream Kubernetes dashboards come bundled with the chart.
* **Viewing it** (default is `ClusterIP` — nothing is published):

  ```bash
  kubectl -n observability port-forward svc/kube-prometheus-stack-grafana 3000:80
  # http://localhost:3000  — user/password from the Secret above

  # Prometheus UI / Alertmanager UI if you need the raw targets & silences:
  kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090
  kubectl -n observability port-forward svc/kube-prometheus-stack-alertmanager 9093
  ```

  To publish it instead, either set `grafana.ingress.enabled: true` (+ `hosts`,
  `ingressClassName`, and `grafana.ini.server.root_url`) in the HelmRelease, or —
  preferably — let topic 4 attach an `HTTPRoute` to the Gateway it already runs for
  the webapp and point it at `kube-prometheus-stack-grafana:80`. Either way, put a
  cert-manager `Certificate` (topic 2) in front of it.

---

## 5. Versions

Pinned on purpose so **Renovate (topic 6) proposes upgrades as reviewable PRs**
instead of the cluster drifting on its own:

| Thing | Version |
| ----- | ------- |
| chart `kube-prometheus-stack` | `91.1.0` |
| Prometheus Operator | `v0.94.0` (chart appVersion; operator + config-reloader images pinned) |
| Prometheus | `v3.14.0-distroless` |
| Alertmanager | `v0.34.0` |
| Grafana | `13.2.1` |
| sub-charts | grafana `13.2.4`, kube-state-metrics `8.4.2`, node-exporter `4.57.0` |

The HelmRelease carries `# renovate:` hints next to each pin. Chart upgrades
occasionally rename values — read the chart's `UPGRADE.md` before merging a major
bump (e.g. anything touching `prometheusSpec` selectors would break the
"discover monitors everywhere" contract above).

---

## 6. Storage & retention

| Component | PVC | Notes |
| --------- | --- | ----- |
| Prometheus | 20Gi, `retention: 15d`, `retentionSize: 16GiB` | the size cap is below the PVC on purpose: a full PVC wedges the TSDB, a size cap just prunes old blocks |
| Alertmanager | 2Gi | notification log / silences |
| Grafana | 5Gi | dashboards created in the UI; provisioned ones live in Git |

`storageClassName` is left commented out, so the cluster default class is used —
uncomment it (`local-path` on k3s, `longhorn`, …) if you have more than one.

---

## 7. Troubleshooting

```bash
flux -n observability get helmrelease kube-prometheus-stack
kubectl -n observability get prometheus,alertmanager,servicemonitor,podmonitor,prometheusrule,alertmanagerconfig -A

# is my ServiceMonitor actually generating a target?
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090
#   → http://localhost:9090/targets  and  /config

# operator refused a CR? it says why here:
kubectl -n observability logs deploy/kube-prometheus-stack-operator | tail -50

# Alertmanager failed to load the merged config (usually: webhook Secret missing):
kubectl -n observability logs alertmanager-kube-prometheus-stack-alertmanager-0 -c alertmanager
```
