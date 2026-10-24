#!/usr/bin/env bash
set -euo pipefail

namespace=monitoring-alert-tests

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f - <<'EOF'
# Triggers KubernetesContainerOOMKilled by repeatedly exceeding the 64Mi limit.
apiVersion: v1
kind: Pod
metadata:
  name: alert-test-oom
  namespace: monitoring-alert-tests
  labels:
    app.kubernetes.io/name: monitoring-alert-test
spec:
  restartPolicy: Always
  containers:
    - name: oom
      image: python:3.12-alpine
      command:
        - python
        - -c
        - a = bytearray(128 * 1024 * 1024); import time; time.sleep(3600)
      resources:
        limits:
          memory: 64Mi
---
# Triggers KubernetesPodProbeFailure with a continuously failing readiness probe.
apiVersion: v1
kind: Pod
metadata:
  name: alert-test-readiness
  namespace: monitoring-alert-tests
  labels:
    app.kubernetes.io/name: monitoring-alert-test
spec:
  restartPolicy: Always
  containers:
    - name: probe
      image: busybox:1.36
      command: ["sh", "-c", "sleep 3600"]
      readinessProbe:
        exec:
          command: ["sh", "-c", "exit 1"]
        periodSeconds: 5
        timeoutSeconds: 1
        failureThreshold: 1
---
# Triggers KubernetesPodProbeFailure with a continuously failing liveness probe.
apiVersion: v1
kind: Pod
metadata:
  name: alert-test-liveness
  namespace: monitoring-alert-tests
  labels:
    app.kubernetes.io/name: monitoring-alert-test
spec:
  restartPolicy: Always
  containers:
    - name: probe
      image: busybox:1.36
      command: ["sh", "-c", "sleep 3600"]
      livenessProbe:
        exec:
          command: ["sh", "-c", "exit 1"]
        periodSeconds: 5
        timeoutSeconds: 1
        failureThreshold: 1
EOF

printf 'Test pods created in namespace %s. They remain until deleted so Prometheus can scrape the failures.\n' "$namespace"
printf 'Inspect with: kubectl get pods -n %s\n' "$namespace"
printf 'Clean up with: kubectl delete namespace %s\n' "$namespace"
