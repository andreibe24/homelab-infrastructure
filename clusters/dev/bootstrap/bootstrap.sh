#!/usr/bin/env bash
# Bootstrap a single-node kind cluster with Cilium, the Flux Operator and Flux.
#
# Usage:  ./bootstrap.sh
# Optional: GIT_USERNAME and GIT_TOKEN in the environment skip the prompts.
set -euo pipefail

# Paths below are relative to the directory this script lives in.
cd "$(dirname "${BASH_SOURCE[0]}")"

CLUSTER_NAME="dev"
KIND_CONFIG="kind.cluster.yaml"
KUBECONFIG_PATH="$HOME/.kube/configs/dev-cluster.yaml"

# renovate: datasource=github-releases depName=kubernetes-sigs/gateway-api
GATEWAY_API_VERSION="v1.6.3"
# renovate: datasource=docker depName=quay.io/cilium/charts/cilium
CILIUM_VERSION="1.20.2"
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

# 3. The cluster must not exist yet
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  fail "kind cluster '$CLUSTER_NAME' already exists; delete it first: kind delete cluster --name $CLUSTER_NAME"
fi

# ---------------------------------------------------------------------------
# Git credentials: ask up front so the script never stalls halfway through.
# ---------------------------------------------------------------------------
GIT_USERNAME="${GIT_USERNAME:-}"
GIT_TOKEN="${GIT_TOKEN:-}"

if [[ -z "$GIT_USERNAME" || -z "$GIT_TOKEN" ]]; then
  [[ -t 0 ]] || fail "GIT_USERNAME and GIT_TOKEN must be set when running non-interactively"
fi
if [[ -z "$GIT_USERNAME" ]]; then
  read -r -p "Git username: " GIT_USERNAME
fi
if [[ -z "$GIT_TOKEN" ]]; then
  read -r -s -p "Git token (input hidden): " GIT_TOKEN
  echo
fi
[[ -n "$GIT_USERNAME" ]] || fail "Git username cannot be empty"
[[ -n "$GIT_TOKEN" ]]    || fail "Git token cannot be empty"

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

# 4. Namespace and Git credentials (kept out of Git)
log "Creating flux-system namespace and git-creds secret"
kubectl create namespace flux-system
printf '%s' "$GIT_TOKEN" | kubectl create secret generic git-creds \
  --namespace=flux-system \
  --from-literal=username="$GIT_USERNAME" \
  --from-file=password=/dev/stdin
unset GIT_TOKEN

# 5. Flux Operator via Helm, with the web UI settings
log "Installing the Flux Operator $FLUX_OPERATOR_VERSION"
helm install flux-operator \
  oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator \
  --version "$FLUX_OPERATOR_VERSION" \
  --namespace flux-system \
  -f "$OPERATOR_VALUES" \
  --wait

# 6. Flux instance; it syncs the repo and adopts the rest
log "Applying the FluxInstance"
kubectl apply -f "$FLUX_INSTANCE"
kubectl -n flux-system wait fluxinstance/flux --for=condition=Ready --timeout=10m

log "Done. To use the cluster in your shell: export KUBECONFIG=$KUBECONFIG_PATH"
