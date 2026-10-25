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
---
# Triggers the kube-prometheus-stack KubePodCrashLooping alert.
apiVersion: v1
kind: Pod
metadata:
  name: alert-test-crashloop
  namespace: monitoring-alert-tests
  labels:
    app.kubernetes.io/name: monitoring-alert-test
spec:
  restartPolicy: Always
  containers:
    - name: crash
      image: busybox:1.36
      command: ["sh", "-c", "exit 1"]
---
# Triggers FluxKustomizationNotReady because its GitRepository source is not Ready.
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: alert-test-failing-kustomization
  namespace: monitoring-alert-tests
spec:
  interval: 1m
  path: ./
  prune: true
  sourceRef:
    kind: GitRepository
    name: alert-test-failing-gitrepository
---
# Triggers FluxGitRepositoryNotReady with a local connection-refused error.
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: alert-test-failing-gitrepository
  namespace: monitoring-alert-tests
spec:
  interval: 1m
  url: http://127.0.0.1:1/alert-test.git
  ref:
    branch: main
---
# Triggers FluxHelmReleaseNotReady because its HelmRepository source is not Ready.
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: alert-test-failing-helmrelease
  namespace: monitoring-alert-tests
spec:
  interval: 1m
  chart:
    spec:
      chart: alert-test-chart
      version: 0.0.1
      sourceRef:
        kind: HelmRepository
        name: alert-test-failing-helmrepository
---
# Provides a failing Helm chart source without contacting an external registry.
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: alert-test-failing-helmrepository
  namespace: monitoring-alert-tests
spec:
  interval: 1m
  url: http://127.0.0.1:1/charts
---
# Synthetic KubeNodeNotReady alert to test Slack routing without changing real node status.
# Node readiness is cluster-scoped and cannot be safely made NotReady from this namespace.
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: alert-test-node-not-ready
  namespace: monitoring-alert-tests
  labels:
    release: monitoring
spec:
  groups:
    - name: alert-test-node
      rules:
        - alert: KubeNodeNotReady
          expr: vector(1)
          labels:
            severity: warning
            namespace: monitoring-alert-tests
            node: alert-test-node
          annotations:
            summary: Synthetic node readiness alert test
            description: >-
              Synthetic KubeNodeNotReady alert. This does not reflect a real node's status.
EOF

printf 'Alert test resources created in namespace %s. Allow time for Prometheus to scrape and evaluate them.\n' "$namespace"
printf 'The default KubePodCrashLooping alert waits 15 minutes before firing.\n'
printf 'Inspect pods and Flux resources with: kubectl get pods,kustomizations,gitrepositories,helmreleases,helmrepositories -n %s\n' "$namespace"
printf 'Inspect the synthetic node rule with: kubectl get prometheusrule alert-test-node-not-ready -n %s\n' "$namespace"
printf 'Clean up with: kubectl delete namespace %s\n' "$namespace"
