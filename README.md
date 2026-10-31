# homelab-infrastructure

TODO

Renovate pins container image digests in Kubernetes manifests (including the
kind cluster configuration), Kustomize image overrides, Dockerfiles, GitHub
Actions, GitLab CI, and Flux HelmRelease values and Kustomizations. Keep Flux
OCIRepository resources in dedicated
`*.ocirepository.yaml` files, separate from `*.helmrelease.yaml` and `*.ks.yaml`
files: their OCI chart/artifact tags and bootstrap chart versions are not
container images and must remain tag-based. Renovate also updates the
Dragonfly operator's remote Kustomize manifest by its GitHub tag, without
pinning it to a commit digest.
