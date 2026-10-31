#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "${BASH_SOURCE[0]}")"

# renovate: datasource=github-releases depName=siderolabs/talos
TALOS_VERSION="v1.14.5"
# renovate: datasource=github-releases depName=kubernetes/kubernetes
KUBERNETES_VERSION="v1.37.1"
# renovate: datasource=github-releases depName=kubernetes-sigs/gateway-api
GATEWAY_API_VERSION="v1.7.0"
# renovate: datasource=docker depName=quay.io/cilium/charts/cilium
CILIUM_VERSION="1.20.4"
# renovate: datasource=docker depName=ghcr.io/controlplaneio-fluxcd/charts/flux-operator
FLUX_OPERATOR_VERSION="0.62.1"

STATE_DIR="${STATE_DIR:-$HOME/.config/talos/homelab}"
CONTROL_PLANE_IP="${CONTROL_PLANE_IP:-}"
WORKER_IP="${WORKER_IP:-}"
CONTROL_PLANE_DISK="${CONTROL_PLANE_DISK:-}"
WORKER_DISK="${WORKER_DISK:-}"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing required tool: $1"; }
ipv4() {
  local ip="$1" part
  local -a parts
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
  IFS=. read -r -a parts <<< "$ip"
  for part in "${parts[@]}"; do
    [[ ${#part} -le 3 ]] && (( 10#$part <= 255 )) || return 1
  done
}
check_ip() { ipv4 "$1" || fail "expected an IPv4 address, got: $1"; }
check_disk() {
  [[ "$1" =~ ^/dev/[a-zA-Z0-9._/-]+$ ]] || fail "expected a /dev/ disk path, got: $1"
}
check_state() {
  [[ -f "$STATE_DIR/talosconfig" && -f "$STATE_DIR/controlplane.yaml" && -f "$STATE_DIR/worker.yaml" && -f "$STATE_DIR/nodes" ]] ||
    fail "generated configuration not found in $STATE_DIR"
}
check_addresses() {
  local saved_control_plane saved_worker
  read -r saved_control_plane saved_worker < "$STATE_DIR/nodes"
  [[ "$CONTROL_PLANE_IP" == "$saved_control_plane" ]] || fail "control-plane address differs from generated configuration"
  if [[ -n "$WORKER_IP" ]]; then
    [[ "$WORKER_IP" == "$saved_worker" ]] || fail "worker address differs from generated configuration"
  fi
}

case "${1:-}" in
  generate)
    need talosctl
    [[ "$(talosctl version --client --short)" == *"Talos ${TALOS_VERSION}"* ]] ||
      fail "talosctl client must be ${TALOS_VERSION}"
    check_ip "$CONTROL_PLANE_IP"
    check_ip "$WORKER_IP"
    [[ "$CONTROL_PLANE_IP" != "$WORKER_IP" ]] || fail "node addresses must differ"
    check_disk "$CONTROL_PLANE_DISK"
    check_disk "$WORKER_DISK"
    [[ ! -e "$STATE_DIR" ]] || fail "state directory already exists: $STATE_DIR"
    mkdir -p "$STATE_DIR"
    talosctl gen config homelab "https://${CONTROL_PLANE_IP}:6443" \
      --output "$STATE_DIR" --with-docs=false --with-examples=false \
      --talos-version "$TALOS_VERSION" --kubernetes-version "$KUBERNETES_VERSION" \
      --install-image "ghcr.io/siderolabs/installer:${TALOS_VERSION}" \
      --install-disk "$CONTROL_PLANE_DISK" \
      --config-patch-control-plane "@network.patch.yaml" \
      --config-patch-worker "{\"apiVersion\":\"v1alpha1\",\"kind\":\"UnattendedInstallConfig\",\"provisioning\":{\"diskSelector\":{\"match\":\"disk.dev_path == \\\"${WORKER_DISK}\\\"\"}}}"
    talosctl validate --mode metal --config "$STATE_DIR/controlplane.yaml"
    talosctl validate --mode metal --config "$STATE_DIR/worker.yaml"
    printf '%s %s\n' "$CONTROL_PLANE_IP" "$WORKER_IP" > "$STATE_DIR/nodes"
    printf 'Generated sensitive configuration in %s; back it up securely.\n' "$STATE_DIR"
    ;;
  apply)
    need talosctl
    check_state
    check_ip "$CONTROL_PLANE_IP"
    check_ip "$WORKER_IP"
    [[ "$CONTROL_PLANE_IP" != "$WORKER_IP" ]] || fail "node addresses must differ"
    check_addresses
    [[ "${CONFIRM_INSTALL:-}" == "yes" ]] || fail "set CONFIRM_INSTALL=yes after verifying both nodes and install disks"
    talosctl apply-config --insecure --nodes "$CONTROL_PLANE_IP" --file "$STATE_DIR/controlplane.yaml"
    talosctl apply-config --insecure --nodes "$WORKER_IP" --file "$STATE_DIR/worker.yaml"
    ;;
  bootstrap)
    need talosctl
    check_state
    check_ip "$CONTROL_PLANE_IP"
    check_addresses
    [[ ! -e "$STATE_DIR/bootstrap-attempted" && ! -e "$STATE_DIR/kubeconfig" ]] ||
      fail "bootstrap already attempted; see the recovery instructions before proceeding"
    ( set -o noclobber; : > "$STATE_DIR/bootstrap-attempted" ) || fail "bootstrap already attempted"
    talosctl --talosconfig "$STATE_DIR/talosconfig" --endpoints "$CONTROL_PLANE_IP" \
      --nodes "$CONTROL_PLANE_IP" bootstrap
    talosctl --talosconfig "$STATE_DIR/talosconfig" --endpoints "$CONTROL_PLANE_IP" \
      --nodes "$CONTROL_PLANE_IP" kubeconfig --merge=false "$STATE_DIR/kubeconfig"
    ;;
  install)
    need kubectl
    need helm
    check_state
    check_ip "$CONTROL_PLANE_IP"
    check_addresses
    [[ -f "$STATE_DIR/kubeconfig" ]] || fail "kubeconfig not found in $STATE_DIR"
    export KUBECONFIG="$STATE_DIR/kubeconfig"
    kubectl get nodes
    kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
    helm upgrade --install cilium oci://quay.io/cilium/charts/cilium \
      --version "$CILIUM_VERSION" --namespace kube-system \
      -f ../../../infrastructure/imported/cilium/custom.helmvalues.yaml \
      -f ../../../infrastructure/imported/cilium/custom-values/homelab.yaml \
      --set-string "k8sServiceHost=$CONTROL_PLANE_IP" --wait --timeout 10m
    kubectl -n kube-system create configmap homelab-cilium-settings \
      --from-literal="HOMELAB_API_HOST=$CONTROL_PLANE_IP" --dry-run=client -o yaml | kubectl apply -f -
    kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -
    helm upgrade --install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator \
      --version "$FLUX_OPERATOR_VERSION" --namespace flux-system \
      -f ../../../infrastructure/imported/flux-operator/custom.helmvalues.yaml --wait --timeout 10m
    kubectl apply -f flux.fluxinstance.yaml
    kubectl -n flux-system wait fluxinstance/flux --for=condition=Ready --timeout=10m
    printf 'Flux is installed. Shared infrastructure and apps remain suspended; see docs/homelab-talos.md.\n'
    ;;
  *)
    fail "usage: $0 {generate|apply|bootstrap|install}; see docs/homelab-talos.md"
    ;;
esac
