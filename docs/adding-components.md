# Adding components

These are the current patterns, not a promise that every component needs every
resource. Inspect a neighboring component and its dependencies first. All paths
below are relative to the repository root.

## Choose the target clusters

The dev entry point reconciles the shared `apps/`,
`infrastructure/components/`, and `infrastructure/imported/` roots. Homelab
adopts its own Cilium overlay and the shared Flux Operator; its shared apps and
infrastructure roots are suspended pending operator preparation. A registration
in a shared root will also affect homelab when it reconciles that root. For cluster-specific
components or configuration, use an explicit cluster-specific selection or
overlay and wire it only into the intended cluster's entry point. Do not assume
such an overlay already exists. Review storage, networking, hostnames, secrets,
and bootstrap dependencies separately for each cluster.

## Application in `apps/`

1. Create `apps/<name>/` with `<name>.namespace.yaml` if the namespace is new,
   `<name>.ks.yaml` for the Flux Kustomization, and `kustomization.yaml` for
   the workload resources. Follow `apps/whoami/` as a small example.
2. Set the Flux Kustomization's namespace, source reference, `spec.path` to
   `./apps/<name>`, and any required `dependsOn` entries. The namespace and
   Flux Kustomization are registered by the parent; do not include them in the
   workload Kustomization they reconcile.
3. Set the local Kustomization namespace and list the workload resources:
   deployment, service, route, network policy, and other resources as needed.
   Preserve the app namespace injection patch and network-policy conventions.
4. Register the namespace and Flux Kustomization in `apps/kustomization.yaml`,
   unless deliberately using a cluster-specific selection instead. Add any
   encrypted cluster secrets through the process in [secrets.md](secrets.md).
5. Document usage in `docs/apps/` and link it from [the index](README.md).

## Managed infrastructure in `infrastructure/components/`

1. Create `infrastructure/components/<name>/` and follow a comparable existing
   component such as `falco`. Create a namespace manifest if needed, a Flux
   Kustomization with a path to the component, and a local `kustomization.yaml`
   listing the resources to apply.
2. For Helm deployments, keep the source and release in separate
   `*.ocirepository.yaml` (or `*.helmrepository.yaml`) and
   `*.helmrelease.yaml` files. Include network policy and service/route
   resources where needed. Specify real `dependsOn` relationships for CRDs,
   controllers and other prerequisites.
3. Register the namespace and Flux Kustomization in
   `infrastructure/components/kustomization.yaml`, or explicitly select them
   per cluster. Components that share a namespace need not create it again.
   Preserve the namespace injection policy and opt out where appropriate.
4. Add operational documentation under `docs/components/` and link it from
   [the index](README.md).

## Bootstrap-imported infrastructure in `infrastructure/imported/`

This area adopts bootstrap-installed infrastructure such as Cilium and the Flux
Operator; it is not the default location for ordinary Helm installs.

1. Ensure the intended cluster's bootstrap installs the component before Flux
   adopts it, and coordinate chart versions and bootstrap Helm values with its
   Flux resources. The homelab bootstrap and Cilium overlay differ from dev;
   see [homelab-talos.md](homelab-talos.md).
2. Create `infrastructure/imported/<name>/` with `<name>.ks.yaml`, a local
   `kustomization.yaml`, and separate source and HelmRelease manifests. Use the
   existing Cilium or Flux Operator patterns for generated Helm values and
   namespaces.
3. Register the Flux Kustomization in `infrastructure/imported/kustomization.yaml`,
   or explicitly select it per cluster. Preserve the existing `prune: false`
   and prune-disabled annotations for adopted resources; accidental deletion
   can break cluster bootstrap.
4. Document bootstrap and adoption requirements under `docs/` and link the
   guide from [the index](README.md).

## File naming and validation

Use descriptive lowercase kebab-case names. The common convention is
`<component>.<resource-kind>.yaml`, for example `whoami.deployment.yaml`,
`falco.helmrelease.yaml`, `<name>.namespace.yaml`, and `<name>.networkpolicy.yaml`.
Use `kustomization.yaml` for a Kustomize resource list, `*.ks.yaml` for a
Flux Kustomization, and `*.secret.yaml` for SOPS-encrypted secret manifests.
Existing descriptive variants such as `cloudnative-pg.kustomization.yaml` are
valid; do not rename working resources merely for uniformity.

Run `kubectl kustomize` for each changed local and parent Kustomization, and the
relevant checks in `.github/workflows/lint-infrastructure.yaml`. Some builds
fetch remote resources and require network access. Validate both the targeted
cluster's entry point and the intended shared or cluster-specific selection;
do not apply changes to a live cluster merely to validate them.
