# Linkerd — automatic mTLS for the `homelab` cluster

> "For 2 identities, mutual means that each part verifies the TLS cert of the other
> part." — `development-environment/todo.md`

That sentence is the whole point of this directory. Every meshed pod gets its own
cryptographic **identity**, and on every connection *both* sides present a
certificate and *both* sides validate the peer's certificate against a shared
trust anchor. Not "the client trusts the server" (ordinary TLS), but both
directions — hence *mutual* TLS.

## What is installed here

| File | Object | Purpose |
| ---- | ------ | ------- |
| `helmrelease-crds.yaml` | `HelmRelease/linkerd-crds` (chart `1.8.0`) | `Server`, `AuthorizationPolicy`, `MeshTLSAuthentication`, `ServiceProfile`, `HTTPRoute` CRDs |
| `helmrelease-control-plane.yaml` | `HelmRelease/linkerd-control-plane` (chart `1.16.11` = `stable-2.14.10`) | destination, identity and proxy-injector controllers |
| `helmrelease-viz.yaml` | `HelmRelease/linkerd-viz` (chart `30.12.11`) | dashboard, tap, metrics-api + a small scoped Prometheus |
| `kustomization-pki.yaml` | `Kustomization/linkerd-pki` | reconciles `../../configs/linkerd/pki` early (see [Bootstrap ordering](#bootstrap-ordering)) |

Certificates live in [`../../configs/linkerd/pki/`](../../configs/linkerd/pki), mesh
policy in [`../../configs/linkerd/`](../../configs/linkerd), and cert-manager itself
in [`../cert-manager/`](../cert-manager).

## How the mTLS actually works

```
          cert-manager                                  Linkerd
──────────────────────────────────   ────────────────────────────────────────────
Issuer/linkerd-selfsigned-issuer
  └─ Certificate/linkerd-trust-anchor  ── tls.crt ──►  identityTrustAnchorsPEM
       (root CA, ECDSA P-256, 10y)      (Helm value)   └─ ConfigMap
       │                                                  linkerd-identity-trust-roots
       │                                                  mounted by EVERY proxy
       └─ Issuer/linkerd-trust-anchor (ca)
            └─ Certificate/linkerd-identity-issuer ──►  Secret/linkerd-identity-issuer
                 (intermediate CA, 48h, auto-renewed)    mounted by linkerd-identity
                                                              │
                                                              ▼
                                       signs 24h leaf certs whose SAN is
                                       <sa>.<ns>.serviceaccount.identity.linkerd.cluster.local
```

1. The proxy-injector webhook adds a `linkerd-proxy` sidecar to every pod in a
   namespace annotated `linkerd.io/inject: enabled` (set in
   `infrastructure/namespaces/namespaces.yaml`: `webapp`, `observability`,
   `linkerd-viz`; deliberately **not** `arc-runners`).
2. At startup the proxy proves its ServiceAccount to `linkerd-identity` with a
   projected SA token and receives a 24h leaf certificate whose identity is
   `<serviceaccount>.<namespace>.serviceaccount.identity.linkerd.cluster.local`.
3. When pod A talks to pod B, the proxies do a TLS handshake in which **each
   side sends its leaf certificate and validates the other's chain** against the
   trust anchor in `linkerd-identity-trust-roots`. Both identities are therefore
   authenticated — that is the "2 identities verify each other" property.
4. Those verified identities are what `MeshTLSAuthentication` /
   `AuthorizationPolicy` match on, so authorization is based on cryptographic
   identity rather than on IP addresses.

Application code needs **zero** changes: the mesh transparently upgrades
pod-to-pod TCP to mTLS.

## Bootstrap ordering

The control-plane chart needs the trust anchor's public certificate as a *Helm
value* (`identityTrustAnchorsPEM`), and that value comes from a cert-manager
`Certificate`. Reconciling those certificates in the normal `infra-configs`
stage would deadlock (`infra-configs` waits for `infra-controllers`, which waits
for the control plane, which waits for the Secret). The cycle is broken by
`kustomization-pki.yaml`: a dedicated Flux `Kustomization` that reconciles only
`infrastructure/configs/linkerd/pki` and is itself applied in the controllers
stage. The HelmRelease then pulls the anchor in with:

```yaml
valuesFrom:
  - kind: Secret
    name: linkerd-trust-anchor
    valuesKey: tls.crt
    targetPath: identityTrustAnchorsPEM
```

The **identity issuer rotates itself**: cert-manager reissues the 48h
intermediate roughly every 23h with no git commit and no human involvement. The
trust anchor is 10 years and `rotationPolicy: Never`, because replacing it
requires the documented two-step bundle rotation and a restart of every meshed
pod.

### Decisions recorded

- **Channel**: `stable` (`https://helm.linkerd.io/stable`, already defined in
  `infrastructure/sources/helm-repositories.yaml`). `1.16.11` / `stable-2.14.10`
  is the last free stable release; moving to `edge` means changing the URL in the
  shared sources file, not adding a repository here.
- **Trust anchor delivery**: cert-manager + `valuesFrom`, **not** trust-manager.
  A `Bundle` would add a second controller and a second bootstrap cycle for no
  gain at this scale. If trust-manager is ever introduced, set
  `identity.externalCA: true` and let it own `linkerd-identity-trust-roots`.
- **HA**: off. Single-node homelab, so `controllerReplicas: 1`, no pod
  anti-affinity, no PDBs. Enable the chart's `values-ha.yaml` equivalents when
  the cluster gets more nodes.
- **Default inbound policy**: `all-unauthenticated`. mTLS still happens
  automatically between meshed pods; deny-by-default is opt-in per workload via
  `Server` + `AuthorizationPolicy`.
- **viz Prometheus**: the chart's own scoped Prometheus stays enabled so this
  topic does not depend on topic 5. Switching to `kube-prometheus-stack` is a
  commented-out block in `helmrelease-viz.yaml`.

## ⚠️ Linkerd does **not** proxy UDP — read this before meshing QUIC/HTTP3

Linkerd's data plane only handles **TCP** (and protocols on top of it: HTTP/1,
HTTP/2, gRPC). `linkerd-init`'s iptables rules only redirect TCP, so **UDP
traffic bypasses the proxy entirely** — it is *not* encrypted by the mesh, *not*
load balanced by it, and *not* visible in `linkerd viz` metrics. There is no mTLS
for UDP.

This matters directly for topic 4's Django/`aioquic`/Hypercorn backend, which
serves **HTTP/3 over QUIC (UDP)**. Options, in order of preference:

1. **Terminate QUIC at the edge.** Let an edge proxy/LB speak HTTP/3 to the
   internet and plain HTTP/2 over TCP to the meshed pods. The pod-to-pod hop is
   then fully mTLS'd, and the mesh sees everything.
2. **Keep QUIC in-pod but skip the mesh for that port.** Annotate the workload so
   the proxy does not try to touch it, and secure the UDP listener with its own
   TLS (QUIC has TLS 1.3 built in) using a cert-manager `Certificate` from
   `ClusterIssuer/homelab-ca`:

   ```yaml
   metadata:
     annotations:
       config.linkerd.io/skip-inbound-ports: "443"    # UDP/443 QUIC listener
       config.linkerd.io/skip-outbound-ports: "443"   # if the pod dials QUIC out
   ```

   (The annotations take port numbers, comma separated; ranges like `8000-8010`
   also work. They belong on the **pod template**, not on the Service.)
3. **Exclude the workload from the mesh** entirely with
   `linkerd.io/inject: disabled` on the pod template — last resort, since it also
   gives up mTLS for its TCP traffic.

Also remember: a `Service` cannot mix TCP and UDP on the same port number unless
`spec.ports` lists them separately with distinct names, and a `Server` CR must
never be created for a UDP port — the policy layer is TCP-only.

## Verifying

```bash
# 1. Control plane, PKI, certificate expiry, clock skew, proxy versions
linkerd check                     # add --proxy for data-plane checks
linkerd check --proxy -n webapp

# 2. Are the certificates the ones cert-manager issued?
kubectl -n linkerd get certificate            # linkerd-trust-anchor, linkerd-identity-issuer
kubectl -n linkerd get secret linkerd-identity-issuer \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -subject -dates

# 3. THE mTLS proof: both ends of every edge have a verified identity
linkerd viz edge deployment -n webapp
# SRC          DST          SRC_NS  DST_NS  SECURED  CLIENT_ID            SERVER_ID
# frontend     backend      webapp  webapp  √        frontend.webapp...   backend.webapp...
#                                           ^^^^^^^  ^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^
#                                           mutual   identity of client   identity of server

# 4. Live traffic with the TLS status of each request
linkerd viz tap deploy/backend -n webapp
linkerd viz stat deploy -n webapp
linkerd viz dashboard            # opens a port-forward to linkerd-viz

# 5. Which pods actually got a sidecar?
kubectl get pods -A -o custom-columns=NS:.metadata.namespace,\
POD:.metadata.name,CONTAINERS:.spec.containers[*].name | grep linkerd-proxy
```

`SECURED = √` plus a non-empty `CLIENT_ID` **and** `SERVER_ID` in
`linkerd viz edge` is the acceptance criterion for this topic. An edge with an
empty `CLIENT_ID` means the caller is unmeshed — the connection is *not* mTLS.

## Interfaces with other topics

- **Topic 4 (webapp)** — namespace `webapp` is already annotated for injection.
  Apply the UDP/QUIC caveat above. TCP ports are meshed automatically.
- **Topic 5 (observability)** — scrape the proxies on container port
  **`linkerd-admin` (4191)**, path `/metrics`, container name `linkerd-proxy`;
  a `PodMonitor` selecting `linkerd.io/control-plane-ns` / all meshed namespaces
  is owned by topic 5. Control-plane components expose admin on **9990**.
- **Topic 3 (ARC)** — `arc-runners` is intentionally unmeshed; build pods churn
  too fast for sidecar injection to pay off.
