# webapp-frontend — Vite SPA served by nginx

Framework-free Vite scaffold whose only purpose is to call the Django backend and
show which HTTP version carried the response, so an HTTP/3 upgrade is observable.

```
index.html                 Vite entry document
src/main.js                bootstraps the app
src/App.js                 the "component": fetch /api/health + render
src/App.test.js            vitest unit tests (topic 3 runs them in CI)
src/style.css
vite.config.js             build + dev-proxy + vitest config
nginx.conf.template        runtime server block (envsubst-rendered)
Dockerfile                 node build stage -> nginx:alpine runtime stage, non-root
```

## Runtime

* Build stage: `node:22.12.0-alpine`, `npm ci`, `npm run build` → `/app/dist`.
* Runtime stage: `nginx:1.27.3-alpine` serving `/usr/share/nginx/html` on **TCP 8080**
  as uid 101 (non-root, read-only root filesystem in Kubernetes).
* `nginx.conf.template` is rendered by the official nginx entrypoint through
  `envsubst`, filtered to `^(BACKEND_|ALT_SVC|SPA_)` so nginx's own `$uri`/`$host`
  variables are left alone.

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `BACKEND_HOST` | `webapp-backend` | Service DNS name of the Django backend |
| `BACKEND_PORT` | `8000` | its plaintext in-mesh TCP port |
| `ALT_SVC` | `h3=":443"; ma=86400` | HTTP/3 advertisement added to every response |
| `SPA_API_ORIGIN` | *(empty)* | HTTP/3 API origin the SPA calls directly (`VITE_API_BASE` at build time) |

## Request paths

```
browser ──h1/h2──► ingress-nginx ──► nginx :8080 ──► /api/ proxy ──► backend :8000 (mTLS by Linkerd)
browser ──h3/QUIC────────────────────────────────────────────────► backend :8443/udp (LoadBalancer, no ingress)
```

`gzip` is on for text assets and `http2 on;` is set (nginx ≥ 1.25.1 directive form);
TLS itself is terminated by ingress-nginx in front of the pod, so there is no `ssl_*`
block here. nginx does **not** speak QUIC in this image — HTTP/3 is served by the
backend only. See `apps/base/webapp/README.md` for why.

## Local development

```sh
npm ci
npm run dev      # http://localhost:5173, /api proxied to 127.0.0.1:8000
npm test         # vitest
npm run build    # -> dist/
docker build -t webapp-frontend:dev . && docker run --rm -p 8080:8080 webapp-frontend:dev
```
