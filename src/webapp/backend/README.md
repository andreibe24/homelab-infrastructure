# webapp-backend — Django over Hypercorn + aioquic (HTTP/3)

A deliberately small Django project whose only job is to demonstrate a **real
HTTP/3 (QUIC over UDP)** deployment path in the homelab cluster.

```
manage.py                      Django entrypoint
config/settings.py             env-driven settings (ConfigMap + Secret in-cluster)
config/urls.py                 /api/health, /api/info, /healthz, /metrics
config/asgi.py                 the ASGI callable Hypercorn serves
api/views.py                   JSON views; echo back the negotiated HTTP version
api/middleware.py              dependency-free CORS middleware
api/tests.py                   Django SimpleTestCase suite (topic 3 runs it in CI)
hypercorn.toml                 the three listeners + TLS + alt-svc
tools/gen_self_signed_cert.py  local/bootstrap fallback certificate
entrypoint.sh                  renders hypercorn.toml from env, execs hypercorn
Dockerfile                     multi-stage, non-root (uid 10001), multi-arch safe
requirements.txt               pinned: Django, hypercorn[h3], aioquic, django-prometheus
```

## Ports

| Listener        | Proto    | Port | Purpose |
| --------------- | -------- | ---- | ------- |
| `insecure_bind` | TCP      | 8000 | plaintext HTTP/1.1 + h2c — in-mesh calls from nginx, kubelet probes, Prometheus `/metrics`. Linkerd wraps it in mTLS. |
| `bind`          | TCP      | 8443 | TLS HTTP/1.1 + h2 — the **fallback** for clients/networks that cannot use QUIC. |
| `quic_bind`     | UDP      | 8443 | QUIC / HTTP-3 via aioquic. |

TCP 8443 and UDP 8443 are different sockets; sharing the number is deliberate so the
edge `LoadBalancer` can publish both as `:443` on one MetalLB address.

## How the HTTP/3 stack fits together

```
browser ──TLS1.3/TCP──► Hypercorn TCP 8443 ──► h11 / h2 protocol ─┐
                                                                  ├─► ASGI ─► Django
browser ──QUIC/UDP────► Hypercorn UDP 8443 ──► aioquic ─► H3 ─────┘
```

* **aioquic** implements QUIC (RFC 9000) and HTTP/3 (RFC 9114). Hypercorn's
  `UDPServer` feeds datagrams into `aioquic.quic.connection.QuicConnection`, and the
  `H3Protocol` wrapper turns each QUIC stream into ordinary ASGI `http` scope events.
* **Django never sees QUIC.** `config/asgi.py` returns the standard ASGI application;
  the only visible difference is `SERVER_PROTOCOL == "HTTP/3"` (surfaced by
  `/api/health`), which is how you verify a real h3 request end to end.
* **TLS 1.3 is mandatory** for QUIC — there is no plaintext HTTP/3. The cert comes
  from the cert-manager `Certificate` mounted at `/etc/webapp/tls`
  (`apps/base/webapp/certificate.yaml`). If that mount is missing, `entrypoint.sh`
  generates a short-lived self-signed cert so the container still boots; browsers
  will refuse it, which is intentional (fail loud, not silently insecure).
* Hypercorn applies `certfile`/`keyfile` to **all** TCP binds, which is why the
  plaintext in-mesh listener uses `insecure_bind` rather than a second `bind`.

## Alt-Svc: how a browser discovers HTTP/3

A browser never starts with HTTP/3 — it has no way to know UDP/443 is open. The
first request is TCP/TLS, and the server advertises the alternative:

```
HTTP/2 200
alt-svc: h3=":443"; ma=86400
```

The browser caches that entry for `ma` seconds (86400 = 1 day) and **races** a QUIC
handshake against TCP on subsequent requests; if QUIC wins, everything after that
is HTTP/3. The alternative endpoint must present a certificate valid for the
*origin* host, which is why `certificate.yaml` lists the API hostname.

Hypercorn generates this header automatically from `quic_bind`, but it would then
advertise the **container** port (`h3=":8443"`). `hypercorn.toml` therefore sets
`alt_svc_headers` explicitly to the externally reachable port; `entrypoint.sh`
overrides it from `$HTTP3_ALT_SVC` (set by `configmap-app.yaml`).

Verify with curl (note `--http3` needs a curl built against ngtcp2/quiche):

```sh
curl -sI https://api.webapp.homelab.lan/api/health | grep -i alt-svc
curl --http3 -s https://api.webapp.homelab.lan/api/health   # -> "protocol": "HTTP/3"
```

## Service mesh caveat

**Linkerd does not proxy UDP.** The QUIC listener therefore bypasses the mesh, and
the backend pod carries `config.linkerd.io/skip-inbound-ports: "8443"` /
`skip-outbound-ports: "8443"`. In-mesh traffic keeps using plaintext TCP 8000 where
Linkerd provides mTLS. Full rationale: `apps/base/webapp/README.md`.

## Running locally

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py test                 # unit tests

# HTTP/3 on localhost (self-signed cert is generated automatically):
TLS_CERTFILE=./dev-certs/tls.crt TLS_KEYFILE=./dev-certs/tls.key \
HTTP3_ALT_SVC='h3=":8443"; ma=3600' ./entrypoint.sh
```

```sh
docker build -t webapp-backend:dev .
docker run --rm -p 8000:8000/tcp -p 8443:8443/tcp -p 8443:8443/udp webapp-backend:dev
```

## Environment variables

| Variable | Source | Meaning |
| -------- | ------ | ------- |
| `DJANGO_DEBUG` | ConfigMap | never `true` in-cluster |
| `DJANGO_ALLOWED_HOSTS` | ConfigMap | comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | ConfigMap | comma-separated origins |
| `DJANGO_CORS_ALLOWED_ORIGINS` | ConfigMap | SPA origin (cross-origin because the h3 API is a different host) |
| `HTTP3_ALT_SVC` | ConfigMap | the advertised `alt-svc` value |
| `TLS_CERTFILE` / `TLS_KEYFILE` | ConfigMap | paths inside the cert-manager Secret mount |
| `SELF_SIGNED_HOSTS` | ConfigMap | SANs used only by the fallback cert |
| `APP_VERSION`, `POD_NAME`, `NODE_NAME` | Downward API / CI | reported by `/api/info` |
| `DJANGO_SECRET_KEY` | **Secret** | provided by the repo-wide secret mechanism (topic 3). If absent, an ephemeral key is generated and logged as such — sessions do not survive a restart. |
