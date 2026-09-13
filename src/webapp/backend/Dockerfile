# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Django + Hypercorn/aioquic (HTTP/3) backend.
# Built and pushed by topic 3's .github/workflows/build-images.yaml as
#   ghcr.io/andreibe24/webapp-backend        <-- replace `andreibe24` with the real
#                                                GitHub org before first use; the same
#                                                path is referenced by the Flux
#                                                ImageRepository in apps/homelab/.
# Multi-arch safe: no architecture-specific steps, aioquic/cryptography ship
# manylinux wheels for amd64 and arm64 (the toolchain below covers a source build).

# ----------------------------------------------------------------------------- build
FROM python:3.12.8-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip==24.3.1 \
    && /opt/venv/bin/pip install -r requirements.txt

# --------------------------------------------------------------------------- runtime
FROM python:3.12.8-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=config.settings \
    RUNTIME_DIR=/var/run/webapp

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=10001:10001 . /app

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /var/run/webapp /etc/webapp/tls /app/staticfiles \
    && chown -R 10001:10001 /var/run/webapp /app/staticfiles

USER 10001:10001

# TCP 8000 plaintext (in-mesh + probes + /metrics), TCP 8443 TLS fallback,
# UDP 8443 QUIC/HTTP-3. Kubernetes ignores EXPOSE, but it documents the contract
# and `docker run -p` needs the UDP mapping to be explicit.
EXPOSE 8000/tcp 8443/tcp 8443/udp

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
# entrypoint.sh execs:
#   hypercorn --config file:$RUNTIME_DIR/hypercorn.toml config.asgi:application
# which is hypercorn.toml's `bind`/`insecure_bind`/`quic_bind` -- equivalent to
#   hypercorn --bind 0.0.0.0:8443 --insecure-bind 0.0.0.0:8000 \
#             --quic-bind 0.0.0.0:8443 --certfile ... --keyfile ... config.asgi:application
