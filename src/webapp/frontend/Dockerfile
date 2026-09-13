# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Vite SPA, served by nginx.
# Published by topic 3's build-images.yaml as
#   ghcr.io/andreibe24/webapp-frontend       <-- replace `andreibe24` with the real
#                                                GitHub org; the Flux ImageRepository
#                                                in apps/homelab/ must match.

# ----------------------------------------------------------------------------- build
FROM node:22.12.0-alpine AS build

WORKDIR /app

# package-lock.json is committed so `npm ci` gives reproducible, Renovate-trackable
# builds.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# --------------------------------------------------------------------------- runtime
FROM nginx:1.27.3-alpine AS runtime

# Defaults for the envsubst-rendered template; overridden in-cluster by
# apps/base/webapp/configmap-app.yaml.
ENV BACKEND_HOST=webapp-backend \
    BACKEND_PORT=8000 \
    ALT_SVC='h3=":443"; ma=86400' \
    SPA_API_ORIGIN='' \
    NGINX_ENVSUBST_FILTER='^(BACKEND_|ALT_SVC|SPA_)' \
    NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx/conf.d

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Run as the image's unprivileged `nginx` user (uid 101). The entrypoint renders
# templates into conf.d and nginx writes its pid/caches, so those paths must be
# writable; in Kubernetes they are emptyDir mounts and the root FS is read-only.
RUN rm -f /etc/nginx/conf.d/default.conf \
    && touch /var/run/nginx.pid \
    && chown -R 101:101 /var/cache/nginx /var/run/nginx.pid /etc/nginx/conf.d

USER 101:101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
