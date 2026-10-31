# KEDA autoscaling and high availability

`infrastructure/components/metrics-server` provides the resource metrics API
and `infrastructure/components/keda` installs KEDA (operator, metrics API
server and webhooks at two replicas each). Both run in namespaces that opt out
of Linkerd injection so the API server can reach them.

Stateless Deployments have a `ScaledObject` with a `cpu` and a `memory`
trigger, `minReplicaCount: 1` and `maxReplicaCount: 5`:

- Apps (`whoami`, `sample-http3`, the four `webapp-django-vite` Deployments)
  and `agentgateway-ratelimit` use `Utilization` triggers scoped with
  `containerName`, so the injected Linkerd proxy is ignored. Every scaled
  container must declare resource requests.
- Helm-installed controllers (cert-manager, agentgateway controller, Envoy
  Gateway controller, CloudNativePG operator, Reloader, falcosidekick and the
  Dragonfly operator) use `AverageValue` triggers (500m CPU, 256Mi memory per
  pod) because their charts do not set requests.

Deployments scaled by KEDA must not set `spec.replicas`; Flux would otherwise
reset them. The Flux Kustomization of each scaled component depends on `keda`.

Other components get fixed replica counts: two Prometheus and Alertmanager
replicas, three CloudNativePG instances per database, two Dragonfly pods, two
Linkerd control-plane replicas, and two Cilium operators on homelab only (dev
is a single node). Not autoscaled: Falco (DaemonSet), Cilium and Flux Operator
(bootstrap-managed), Reflector, kube-state-metrics and Grafana (not safe to run
as multiple stateless replicas with the current configuration), the Prometheus
operator, and the hostNetwork Envoy data plane.

Run replica counts above one only where the cluster has capacity; the dev kind
cluster has a single node, so replicas share it.
