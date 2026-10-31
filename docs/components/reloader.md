# Reloader

Stakater Reloader watches ConfigMaps and Secrets across the cluster and restarts
workloads that reference them when their contents change.

Opt in a Deployment, StatefulSet, or DaemonSet by adding this annotation to its
pod-owning workload's metadata:

```yaml
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```

Reloader then restarts the workload when any referenced ConfigMap or Secret
changes. Without the annotation, the workload is not automatically restarted.
