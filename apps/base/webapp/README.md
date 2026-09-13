# webapp — Django/HTTP-3 backend + Vite/nginx frontend (topic 4: cd-webapp)

Environment-agnostic manifests for the demo application. The cluster overlay is
[`apps/homelab/`](../../homelab/), the application source is
[`src/webapp/`](../../../src/webapp/), and the images are built and pushed by
topic 3's `.github/workflows/build-images.yaml`.

```
apps/base/webapp/
├── configmap-app.yaml        Django env + nginx envsubst variables
├── configmap-nginx.yaml      nginx server block (template, rendered at pod start)
├── deployment-backend.yaml   Django + Hypercorn/aioquic, 3 listeners, mesh-skip
├── deployment-frontend.yaml  nginx serving the Vite bundle
├── service-backend.yaml      ClusterIP + LoadBalancer(TCP) + LoadBalancer(UDP)
├── service-frontend.yaml     ClusterIP
├── certificate.yaml          cert-manager Certificates (backend TLS/QUIC, SPA TLS)
├── ingress.yaml              ingress-nginx: SPA + TCP-only API fallback
└── kustomization.yaml
```

The `webapp` Namespace is **not** declared here — it is owned by
`infrastructure/namespaces/namespaces.yaml` and already carries
`linkerd.io/inject: enabled`.

---

## 1. Architecture

```
                    ┌──────────────────────── browser ────────────────────────┐
                    │                                                         │
         https://webapp.homelab.lan (TCP 443)              https://api.webapp.homelab.lan
                    │                                        TCP 443 │ UDP 443 (QUIC/h3)
                    ▼                                                ▼        ▼
        ┌───────────────────────┐                        ┌──────────────────────────────┐
        │ ingress-nginx (LB)    │  TLS terminated        │ MetalLB 192.168.1.240        │
        │ Ingress/webapp        │  h1 + h2 only          │ Service/webapp-backend-tls   │
        └──────────┬────────────┘                        │ Service/webapp-backend-quic  │
                   │                                     └───────────────┬──────────────┘
      ┌────────────┴──────────────┐                                      │ (bypasses ingress)
      │ /                         │ /api                                 │
      ▼                           ▼                                      ▼
┌──────────────┐   /api/   ┌──────────────────────────────────────────────────────────┐
│ nginx :8080  │──────────►│ Hypercorn   TCP 8000 (plain, meshed)                     │
│ (SPA, meshed)│  Linkerd  │             TCP 8443 (TLS h1/h2, mesh-skipped)           │
└──────────────┘   mTLS    │             UDP 8443 (QUIC/HTTP-3, mesh-skipped, aioquic)│
                           └──────────────────────────────────────────────────────────┘
```

### Ports

| Component | Port | Proto | Exposed as | Meshed | Purpose |
| --------- | ---- | ----- | ---------- | ------ | ------- |
| backend   | 8000 | TCP   | `Service/webapp-backend:8000` (ClusterIP) | ✅ mTLS | in-cluster API, kubelet probes, `/metrics` |
| backend   | 8443 | TCP   | `Service/webapp-backend-tls:443` (LoadBalancer) | ❌ skipped | HTTPS fallback + carries the `alt-svc` header |
| backend   | 8443 | UDP   | `Service/webapp-backend-quic:443` (LoadBalancer) | ❌ (UDP) | **HTTP/3** |
| frontend  | 8080 | TCP   | `Service/webapp-frontend:80` → `Ingress/webapp` | ✅ mTLS | SPA + same-origin `/api` proxy |

Both LoadBalancer Services are pinned to the **same** MetalLB address via
`metallb.universe.tf/allow-shared-ip: webapp-api` (+ `loadBalancerIP` in the
overlay), so `api.webapp.homelab.lan` answers on TCP/443 *and* UDP/443.

---

## 2. HTTP/3 negotiation (Alt-Svc)

A browser cannot know that UDP/443 speaks QUIC, and there is no DNS or URL scheme
that says so (HTTPS/SVCB records would, but no homelab resolver is assumed here).
The discovery is **in-band**:

1. The first request goes over TCP + TLS 1.3 to `api.webapp.homelab.lan:443`.
2. Hypercorn attaches `alt-svc: h3=":443"; ma=86400` to the response
   (`alt_svc_headers` in `hypercorn.toml`, overridable with `$HTTP3_ALT_SVC` from
   `configmap-app.yaml`).
3. The browser caches that alternative for `ma` seconds, then races a QUIC
   handshake against TCP on the next request. If QUIC wins, everything afterwards
   is HTTP/3 (`/api/health` reports `"protocol": "HTTP/3"`).
4. If UDP is blocked anywhere on the path, the race simply fails and the browser
   keeps using the TCP listener — HTTP/3 is always an optimisation, never a
   requirement.

Two details that are easy to get wrong:

* **Advertise the external port, not the container port.** Left to itself
  Hypercorn derives the header from `quic_bind` and would advertise
  `h3=":8443"`, which is unreachable outside the cluster.
* **The alternative must present a certificate valid for the *origin* host.**
  That is why `certificate.yaml` lists `api.webapp.homelab.lan` and why the SPA
  calls that host directly (`SPA_API_ORIGIN`) instead of relying on the nginx
  proxy when it wants HTTP/3.

```sh
curl -sI https://api.webapp.homelab.lan/api/health | grep -i alt-svc
curl --http3 -s https://api.webapp.homelab.lan/api/health   # "protocol": "HTTP/3"
```

---

## 3. Decision: QUIC bypasses the ingress

**`Ingress` was chosen over Gateway API, and the QUIC datapath deliberately does
not go through it.**

* `Ingress` has no representation for UDP at all. ingress-nginx can carry UDP only
  through the controller's `udp-services` ConfigMap, which is a raw L4 forward —
  not ingress routing, and it still would not terminate QUIC.
* Gateway API `HTTPRoute` is the nicer object, but no Gateway controller is
  installed by any topic in this repo (`infrastructure/sources/` only ships
  ingress-nginx), so an `HTTPRoute` would be inert. HTTP/3 would additionally
  require a Gateway implementation with a QUIC listener (Envoy Gateway, Cilium
  with a `UDPRoute`, …) — a much bigger dependency than this demo warrants.
* Terminating QUIC at the edge and re-originating TCP to the pod would also mean
  the application never sees a real HTTP/3 request, which defeats the purpose of
  the exercise.

So: **the SPA goes through ingress-nginx (TCP only); the HTTP/3 API is published
straight from the pod through a `LoadBalancer` UDP Service.** Consequences to be
aware of:

* No WAF/rate-limit/auth from the ingress on the QUIC path — the backend is
  directly exposed on the LAN address.
* The backend, not the edge, owns the certificate; cert-manager rotation must be
  paired with a rollout (`kubectl rollout restart deploy/webapp-backend`) because
  Hypercorn reads `certfile`/`keyfile` once at startup. Use
  [Reloader](https://github.com/stakater/Reloader) or a short `duration` +
  scheduled restart if this is more than a demo.
* `externalTrafficPolicy: Local` preserves client IPs and avoids a second hop that
  would confuse QUIC connection migration.

If a Gateway API implementation is added later, the equivalent of `ingress.yaml`
is:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: webapp
spec:
  parentRefs: [{ name: homelab-gateway, namespace: gateway-system }]
  hostnames: ["webapp.homelab.lan"]
  rules:
    - matches: [{ path: { type: PathPrefix, value: /api } }]
      backendRefs: [{ name: webapp-backend, port: 8000 }]
    - matches: [{ path: { type: PathPrefix, value: / } }]
      backendRefs: [{ name: webapp-frontend, port: 80 }]
```

…plus a `Gateway` listener on UDP/443. The UDP `Service` above can then be dropped.

---

## 4. Decision: Linkerd and UDP

**Linkerd does not proxy UDP** (its proxy and iptables rules are TCP-only; UDP is
simply not intercepted). The backend pod therefore carries:

```yaml
config.linkerd.io/skip-inbound-ports: "8443"
config.linkerd.io/skip-outbound-ports: "8443"
```

Why, given that UDP is never intercepted anyway:

1. It documents the intent at the object that owns it, rather than in a comment.
2. It also covers **TCP** 8443 — the HTTPS fallback listener. That connection is
   end-to-end TLS from the browser; letting the proxy intercept it would add a
   pointless TLS-in-mTLS wrapper and protocol-detection latency for traffic the
   mesh cannot inspect anyway.
3. TCP 8000 stays meshed, so all *east-west* traffic (nginx → backend, Prometheus →
   `/metrics`) still gets automatic mTLS and L7 metrics. Nothing is lost: the
   plaintext port is never published outside the cluster.

Coordinate with topic 2 (`infrastructure/controllers/linkerd/PLAN.md`) if the mesh
ever moves to a policy-default-deny posture: the QUIC path is *outside* the mesh,
so `Server`/`AuthorizationPolicy` objects cannot protect it.

---

## 5. Flux continuous delivery

Image automation CRs live in the overlay (`apps/homelab/image-automation.yaml`)
because they encode cluster-specific git behaviour:

| Object | Name | Role |
| ------ | ---- | ---- |
| `ImageRepository` | `webapp-backend`, `webapp-frontend` | scan GHCR every 5m |
| `ImagePolicy` | same | pick the newest tag matching `^sha-(?P<ts>\d+)-[0-9a-f]{7,40}$`, ordered numerically |
| `ImageUpdateAutomation` | `webapp` | rewrite `./apps/homelab` and push to `main` |

The `# {"$imagepolicy": ...}` setter markers are in the `images:` block of
`apps/homelab/kustomization.yaml`, so the base never carries a cluster's tag.

**Tag contract with topic 3:** CI must publish `sha-<unix-timestamp>-<short-sha>`
(e.g. `sha-1730000000-1a2b3c4`). Raw git SHAs are not orderable, so a numeric,
monotonically increasing field is required for a deterministic "latest".

> **Bootstrap prerequisite.** `image-reflector-controller` and
> `image-automation-controller` are *optional* Flux components. The cluster must be
> bootstrapped with
> `--components-extra=image-reflector-controller,image-automation-controller`
> (documented in [`clusters/homelab/flux-system/README.md`](../../../clusters/homelab/flux-system/README.md)).
> `infrastructure/sources/` contains only `HelmRepository` objects and does **not**
> and cannot install those controllers — if they are missing, the CRDs are absent
> and the whole `apps` Kustomization fails on unknown kinds. Re-run
> `flux bootstrap` with the flag to fix it.
>
> Renovate (topic 6) must ignore `ghcr.io/<org>/webapp-*` so the two automations do
> not fight over the same tags.

---

## 6. Contracts with other topics

| Topic | Contract |
| ----- | -------- |
| 2 — linkerd-mtls | provides `ClusterIssuer/homelab-ca` consumed by `certificate.yaml`; if it is named differently, change the two `issuerRef`s. Mesh injection comes from the namespace annotation. |
| 3 — ci-self-hosted-runners | builds `ghcr.io/<org>/webapp-{backend,frontend}` from `src/webapp/**` with the tag scheme above; also owns the `webapp-backend-secrets` Secret (`DJANGO_SECRET_KEY`) via the repo-wide SOPS/SealedSecrets mechanism. The backend mounts it with `optional: true`, so nothing blocks before that lands. |
| 5 — observability | `ServiceMonitor` selector: labels `app.kubernetes.io/name: webapp` + `app.kubernetes.io/component: backend`, namespace `webapp`, port name **`http`**, path `/metrics` (django-prometheus). HTTP/3 handshake failures are visible as a gap between `webapp-backend-tls` and `webapp-backend-quic` traffic. |
| 6 — renovate | pins to bump: `src/webapp/backend/requirements.txt`, `src/webapp/frontend/package.json`, both `Dockerfile` base images. Must **not** manage the two GHCR app images. |

## 7. Replace before first use

* `ghcr.io/andreibe24/webapp-backend` / `-frontend` → the real GitHub org
  (`apps/homelab/kustomization.yaml`, `apps/homelab/image-automation.yaml`, both
  Dockerfiles).
* `webapp.homelab.lan` / `api.webapp.homelab.lan` → the real hostnames
  (`configmap-app.yaml`, `certificate.yaml`, `ingress.yaml`).
* `192.168.1.240` and the `homelab-lan` MetalLB pool
  (`apps/homelab/patches/webapp-edge-ip.yaml`).
* `ClusterIssuer/homelab-ca` → whatever topic 2 creates.
