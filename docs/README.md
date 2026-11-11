# Documentation

Paths in the guides are relative to the repository root unless stated otherwise.

## Repository and operations

- [Architecture and clusters](architecture.md): repository layout, reconciliation,
  cluster status, network policies, and dependency updates.
- [Talos homelab bootstrap](homelab-talos.md): two-node provisioning, Flux
  adoption, workload prerequisites, and upgrades.
- [Adding components](adding-components.md): application, infrastructure, and
  imported-component patterns, naming, and cluster targeting.
- [Secrets](secrets.md): SOPS/age, the dev secret location, and prerequisites
  for a separate homelab configuration.
- [Workstation notes](workstation.md): shell, tooling, Git, inotify limits, and
  other setup notes.
- [External workflow dispatchers](external-workflow-dispatchers/README.md):
  GitLab and Cloudflare alternatives for triggering GitHub Actions.
- [Todo notes](todo.md).

## Applications and components

- [Campfire (Django + Vite)](apps/webapp-django-vite.md).
- [Campfire source-code map](apps/webapp-django-vite-source.md).
- [MLflow experiment tracking and training](apps/mlops.md).
- [Agentgateway](components/agentgateway.md).
- [Linkerd](components/linkerd.md).
- [KEDA autoscaling and high availability](components/keda.md).
- [Monitoring](components/monitoring.md).
- [Reloader](components/reloader.md).

Keep application and infrastructure documentation under `docs/`, not beside
the manifests or application source. Add new guides to this index.
