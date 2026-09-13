#!/bin/sh
# Container entrypoint: resolve TLS material, render the Hypercorn config, exec.
set -eu

RUNTIME_DIR="${RUNTIME_DIR:-/var/run/webapp}"
TLS_CERTFILE="${TLS_CERTFILE:-/etc/webapp/tls/tls.crt}"
TLS_KEYFILE="${TLS_KEYFILE:-/etc/webapp/tls/tls.key}"
HTTP3_ALT_SVC="${HTTP3_ALT_SVC:-h3=\":443\"; ma=86400}"
SELF_SIGNED_HOSTS="${SELF_SIGNED_HOSTS:-localhost}"

mkdir -p "$RUNTIME_DIR"

if [ ! -r "$TLS_CERTFILE" ] || [ ! -r "$TLS_KEYFILE" ]; then
    echo "warning: ${TLS_CERTFILE} is not readable -- generating a self-signed cert." >&2
    echo "warning: QUIC requires TLS 1.3; browsers reject self-signed certs. Mount the" >&2
    echo "warning: cert-manager Secret 'webapp-backend-tls' for anything but local runs." >&2
    TLS_CERTFILE="${RUNTIME_DIR}/tls.crt"
    TLS_KEYFILE="${RUNTIME_DIR}/tls.key"
    # shellcheck disable=SC2086
    python /app/tools/gen_self_signed_cert.py "$TLS_CERTFILE" "$TLS_KEYFILE" $SELF_SIGNED_HOSTS
fi

# Render the committed defaults into the effective runtime configuration.
sed \
    -e "s|^certfile = .*|certfile = \"${TLS_CERTFILE}\"|" \
    -e "s|^keyfile = .*|keyfile = \"${TLS_KEYFILE}\"|" \
    -e "s|^alt_svc_headers = .*|alt_svc_headers = ['${HTTP3_ALT_SVC}']|" \
    /app/hypercorn.toml >"${RUNTIME_DIR}/hypercorn.toml"

exec hypercorn --config "file:${RUNTIME_DIR}/hypercorn.toml" config.asgi:application "$@"
