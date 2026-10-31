# Two-node Talos homelab

This is an operator-run, **new-cluster** bootstrap: one Talos control plane
running etcd and one Talos worker. It is not highly available: losing the
control plane loses the API and etcd, and losing the worker stops its workloads.
Keep an off-node etcd snapshot, credentials and tested recovery procedure.
Nothing in this repository has installed or configured the actual machines.

The bootstrap installs Cilium without kube-proxy, the Gateway API CRDs, the
Flux Operator and a FluxInstance. Flux adopts Cilium with a Talos-specific
overlay and adopts the shared Flux Operator release. The shared infrastructure
and application roots are **suspended by default**: the dev manifests are not
yet safe or complete for this cluster. No dev secrets or dev age key are
copied. The existing `gateway-ip-allowlist.yaml` is not registered and must not
be relied on as protection.

## Plan and prerequisites

- Merge these files to the configured Git `main` branch before installing Flux:
  the FluxInstance reads that branch, not the local checkout. Review the
  repository URL and ref in `clusters/homelab/bootstrap/flux.fluxinstance.yaml`.
- Select two distinct machines and stable, reachable IPv4 addresses (DHCP
  reservations are fine), and identify the correct installation disk on each.
  Installation overwrites the selected disk. Ensure the machines boot from the
  installed disk after installation. These examples assume physical metal or
  equivalent VMs, with DHCP networking, Internet access and standard Talos
  images; add and validate machine patches for static network settings, hardware
  extensions, VLANs or custom Image Factory schematics before using this script.
- Reserve the control-plane IP for the Kubernetes API on TCP 6443; it is also
  the fixed Cilium API endpoint. Readdressing it requires a coordinated Talos
  certificate, kubeconfig, Cilium and bootstrap configuration change. Node and
  operator access to Talos TCP 50000, node-to-node Kubernetes/Cilium traffic
  (including Cilium VXLAN UDP 8472 with the default chart) and registry/GitHub
  access must be permitted. Restrict management interfaces to trusted networks.
  Ensure generated pod `10.244.0.0/16` and service `10.96.0.0/12` networks do
  not overlap your LAN, VPN or routes; if they do, add matching Talos patches
  and review Cilium and routing before generating the configs.
- Install `talosctl` at the exact `TALOS_VERSION` in the script, `kubectl` and
  Helm 3 with OCI support on a trusted workstation. Use the same version Talos
  metal ISO as the script for each node's architecture, downloaded and verified
  from the [Talos releases](https://github.com/siderolabs/talos/releases).
  Boot both machines into maintenance mode and confirm their addresses and
  disks from their consoles. The standard installer is
  `ghcr.io/siderolabs/installer:<TALOS_VERSION>`; custom extensions need a
  matching Image Factory boot image **and** installer, so adapt the script
  rather than silently losing extensions after installation.
- The generated files contain cluster-admin credentials, CA keys and machine
  tokens. The script creates them with a restrictive umask outside the checkout.
  Back them up securely, never commit them or print them in logs. Prefer a
  dedicated workstation and network: `apply-config --insecure` uses the
  unauthenticated Talos maintenance API and must not be used over an untrusted
  network. The script does not use or alter your default kubeconfig.

## Provision

From the repository root, set values for **your** machines (example addresses
are documentation-only). Keep the same environment for every stage:

```bash
export CONTROL_PLANE_IP=192.0.2.10
export WORKER_IP=192.0.2.11
export CONTROL_PLANE_DISK=/dev/sda
export WORKER_DISK=/dev/nvme0n1
# Optional; must not already exist. Keep it outside the repository.
export STATE_DIR="$HOME/.config/talos/homelab"
bash clusters/homelab/bootstrap/bootstrap.sh generate
```

Inspect the generated `controlplane.yaml` and `worker.yaml` privately: verify
each `UnattendedInstallConfig` disk selector, installer image, networks and
node role. The Talos 1.14 control-plane patch disables `KubeProxyConfig` and
removes the default `KubeFlannelCNIConfig`; changing Talos minor versions
requires revalidating these config document kinds and the generated output.
The control plane retains the standard scheduling taint; normal workloads run
on the worker. Check resource capacity accordingly.

After confirming both addresses and disks, apply once while both nodes are in
maintenance mode. This starts installation and can overwrite disks:

```bash
CONFIRM_INSTALL=yes bash clusters/homelab/bootstrap/bootstrap.sh apply
```

Wait for both nodes to reboot into their installed Talos systems and for the
control-plane Talos API to become available. Verify using the console or
`talosctl --talosconfig "$STATE_DIR/talosconfig" -e "$CONTROL_PLANE_IP" -n "$CONTROL_PLANE_IP" version`.
Then bootstrap **etcd exactly once** and retrieve a dedicated kubeconfig:

```bash
bash clusters/homelab/bootstrap/bootstrap.sh bootstrap
export KUBECONFIG="$STATE_DIR/kubeconfig"
bash clusters/homelab/bootstrap/bootstrap.sh install
kubectl get nodes -o wide
kubectl -n flux-system get fluxinstance,kustomizations
kubectl -n kube-system get kustomizations,helmreleases
```

Nodes can be NotReady before Cilium is installed. `install` uses the private
kubeconfig, installs Cilium with the same values used by Flux, and creates the
`kube-system/homelab-cilium-settings` ConfigMap containing the API IP.
Flux's Cilium Kustomization requires this ConfigMap for substitution; do not
delete it. It and Cilium's Helm release are bootstrap state, not secrets.
Flux uses the shared OCI chart tags and non-pruning adoption settings, but not
the kind-specific `dev-control-plane` Cilium endpoint. Check both nodes become
Ready and that Cilium and Flux report healthy before proceeding.

`generate` refuses an existing state directory; do not regenerate credentials
for an existing cluster. The script records a bootstrap attempt before calling
Talos, so a failed command cannot accidentally bootstrap etcd twice. If the
bootstrap or kubeconfig step fails, inspect the node's Talos/etcd state first.
If etcd is already bootstrapped, retrieve the kubeconfig without bootstrapping
again:

```bash
talosctl --talosconfig "$STATE_DIR/talosconfig" -e "$CONTROL_PLANE_IP" \
  -n "$CONTROL_PLANE_IP" kubeconfig --merge=false "$STATE_DIR/kubeconfig"
```

If etcd was definitely not bootstrapped, investigate the failure and follow
the [Talos bootstrap and recovery documentation](https://docs.siderolabs.com/talos/)
before an explicitly chosen retry. Do not remove the marker and blindly rerun.
`install` can be rerun after resolving a failed Helm or API step. Never use
this new-cluster workflow to reset or reinstall an existing node.

## Enable workloads deliberately

Before removing `spec.suspend: true` from either homelab Flux Kustomization,
commit cluster-specific configuration and verify at least the following:

1. Provision and test a default StorageClass and backups for the CloudNativePG
   database and Dragonfly PVC. Confirm resources and disk capacity on the
   single worker and understand that a single replica is not HA.
2. Set up an independent homelab SOPS recipient and secret reconciliation as
   described in [secrets.md](secrets.md). Create the required application,
   agentgateway, Falco and monitoring secrets with homelab credentials; do not
   use the dev credentials. Confirm reflector namespaces and ordering.
3. Replace or isolate dev-only hostnames, localhost certificates and host
   networking in the shared gateway and routes. Choose LAN ingress, DNS, TLS
   and access controls explicitly; test cross-node Cilium policy and kubelet
   probes. Do not expose the anonymous Flux UI without an access-control review.
   The existing unregistered allowlist selects Cilium ingress endpoints, not
   necessarily the shared Envoy Gateway's host-network traffic.
4. Review Talos compatibility of Falco and other privileged/host-mounted
   components, the `cluster:dev` alert labels, monitoring endpoints, and all
   remaining shared settings. Use homelab overlays or a cluster-specific
   selection rather than changing dev behavior unintentionally.

Only then enable infrastructure by committing its suspension change and verify
its controllers, storage and dependencies. Enable apps separately and verify
their Flux reconciliation and end-to-end traffic. Since Flux reads Git, a
manual `flux resume` alone is not durable. See
[adding components](adding-components.md) for the shared-root implications.

## Dependency updates and maintenance

Renovate reads the `TALOS_VERSION` and `KUBERNETES_VERSION` release tags in
the bootstrap script. Both produce **non-automerge** PRs; neither a PR nor
merging it upgrades running nodes. Review the Talos support matrix and release
notes, Talos machine-config migrations and Kubernetes version skew, as well as
Cilium and other component compatibility. Keep `talosctl`, the boot image and
installer image aligned. The Cilium, Gateway API and Flux Operator bootstrap
versions are also Renovate-managed; keep their tags aligned with the adopted
OCI sources where applicable. Cilium and Flux Operator chart updates are
grouped across bootstrap and Flux adoption and require manual review.

Before an upgrade, back up etcd and all persistent data, test restoration,
check node health and schedule downtime. Use Talos's documented
`talosctl upgrade` per node and `talosctl upgrade-k8s` for Kubernetes, in the
order and version increments required by the upstream upgrade guides. Verify
each node, Cilium, Flux and workloads after each step; a single control plane
and worker cannot provide uninterrupted service during their respective
upgrades. Do not rerun `generate`, `apply`, or `bootstrap` as an upgrade.
