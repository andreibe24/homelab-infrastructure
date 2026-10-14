# flux-system (cluster: homelab)

This directory is **owned and managed by the Flux CLI**, not by hand.

If it currently contains only this README, Flux has not been bootstrapped against
this repository yet (or was bootstrapped into a different path). Bootstrap with:

```sh
export GITHUB_TOKEN=<a PAT with repo scope>

flux bootstrap github \
  --owner=andreibe24 \
  --repository=homelab-infrastructure \
  --branch=main \
  --path=clusters/homelab \
  --personal \
  --components-extra=image-reflector-controller,image-automation-controller
```

`--components-extra` is required because the `cd-webapp` topic uses
`ImageRepository` / `ImagePolicy` / `ImageUpdateAutomation` for continuous deployment.

After bootstrap this directory contains (committed by the Flux CLI):

- `gotk-components.yaml` — Flux controller Deployments, CRDs, RBAC, namespace
- `gotk-sync.yaml`       — `GitRepository/flux-system` + `Kustomization/flux-system`
  pointing at `./clusters/homelab`
- `kustomization.yaml`   — kustomize entrypoint listing the two files above

The `Kustomization/flux-system` reconciles everything else in `clusters/homelab/`,
i.e. `infrastructure.yaml` and `apps.yaml`, which in turn pull in
`./infrastructure/**` and `./apps/homelab/**`.
