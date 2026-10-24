#!/usr/bin/env bash
# Bootstrap a single-node kind cluster with Cilium, the Flux Operator and Flux.
#
# Usage:  ./bootstrap.sh
set -euo pipefail

# Paths below are relative to the directory this script lives in.
cd "$(dirname "${BASH_SOURCE[0]}")"

CLUSTER_NAME="dev"
KIND_CONFIG="kind.cluster.yaml"
KUBECONFIG_PATH="$HOME/.kube/configs/dev-cluster.yaml"
SOPS_AGE_KEY="$HOME/.config/sops/age/keys.txt"

# renovate: datasource=github-releases depName=kubernetes-sigs/gateway-api
GATEWAY_API_VERSION="v1.6.3"
# renovate: datasource=docker depName=quay.io/cilium/charts/cilium
CILIUM_VERSION="1.20.4"
# renovate: datasource=docker depName=ghcr.io/controlplaneio-fluxcd/charts/flux-operator
FLUX_OPERATOR_VERSION="0.61.0"

CILIUM_VALUES="../../../infrastructure/imported/cilium/custom.helmvalues.yaml"
OPERATOR_VALUES="../../../infrastructure/imported/flux-operator/custom.helmvalues.yaml"
FLUX_INSTANCE="flux.fluxinstance.yaml"

log()  { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks: everything is verified before anything is created.
# ---------------------------------------------------------------------------

# 1. CLI tools
missing=()
for tool in kind kubectl helm; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done

# kind needs a container runtime (docker, or podman as an alternative)
if command -v docker >/dev/null 2>&1; then
  docker info >/dev/null 2>&1 || fail "docker is installed but its daemon is not reachable"
elif ! command -v podman >/dev/null 2>&1; then
  missing+=("docker (or podman)")
fi

if (( ${#missing[@]} > 0 )); then
  printf 'ERROR: missing required tools:\n' >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

# 2. Files the script depends on
for f in "$KIND_CONFIG" "$CILIUM_VALUES" "$OPERATOR_VALUES" "$FLUX_INSTANCE"; do
  [[ -f "$f" ]] || fail "required file not found: $f"
done
[[ -f "$SOPS_AGE_KEY" ]] || fail "SOPS age key file not found: $SOPS_AGE_KEY"

# 3. The cluster must not exist yet
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  fail "kind cluster '$CLUSTER_NAME' already exists; delete it first: kind delete cluster --name $CLUSTER_NAME"
fi

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

# 1. Cluster
log "Creating kind cluster '$CLUSTER_NAME'"
mkdir -p "$(dirname "$KUBECONFIG_PATH")"
kind create cluster --name "$CLUSTER_NAME" \
  --config "$KIND_CONFIG" \
  --kubeconfig "$KUBECONFIG_PATH"

# kind wrote the credentials to a dedicated file, not ~/.kube/config, so point
# every following kubectl/helm call at it (otherwise they hit another cluster).
export KUBECONFIG="$KUBECONFIG_PATH"

# 2. Gateway API CRDs
log "Applying Gateway API CRDs $GATEWAY_API_VERSION"
kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"

# 3. CNI: the node stays NotReady until this finishes
log "Installing Cilium $CILIUM_VERSION"
helm install cilium \
  oci://quay.io/cilium/charts/cilium \
  --version "$CILIUM_VERSION" \
  --namespace kube-system \
  -f "$CILIUM_VALUES" \
  --wait

# 4. Flux namespace
log "Creating flux-system namespace"
kubectl create namespace flux-system

# 5. SOPS decryption key
log "Creating SOPS decryption key secret"
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.agekey=/dev/stdin < "$SOPS_AGE_KEY"

# 6. Flux Operator via Helm, with the web UI settings
log "Installing the Flux Operator $FLUX_OPERATOR_VERSION"
helm install flux-operator \
  oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator \
  --version "$FLUX_OPERATOR_VERSION" \
  --namespace flux-system \
  -f "$OPERATOR_VALUES" \
  --wait

# 7. Flux instance; it syncs the repo and adopts the rest
log "Applying the FluxInstance"
kubectl apply -f "$FLUX_INSTANCE"
kubectl -n flux-system wait fluxinstance/flux --for=condition=Ready --timeout=10m

log "Done. To use the cluster in your shell: export KUBECONFIG=$KUBECONFIG_PATH"
