#!/usr/bin/env bash
set -euo pipefail

# Local development only: -k skips verification of the gateway's TLS certificate.
url="${1:-https://agentgateway.localhost:8443/v1/responses}"

for command in kubectl python3 curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done

forum_key="$(
  kubectl -n agentgateway get secret agentgateway-client-keys -o json |
    python3 -c '
import base64
import json
import sys

secret = json.load(sys.stdin)
entry = json.loads(base64.b64decode(secret["data"]["forum-app"]))
key = entry["key"]
if not isinstance(key, str) or not key or any(c in key for c in "\r\n"):
    raise SystemExit("forum-app has an invalid client key")
sys.stdout.write(key)
'
)"
trap 'unset forum_key' EXIT

# Pass the credential via stdin instead of exposing it in curl's process arguments.
printf 'Authorization: Bearer %s\n' "$forum_key" |
  curl -k --silent --show-error --fail-with-body \
    --connect-timeout 10 --max-time 300 \
    --header @- \
    --header 'Content-Type: application/json' \
    --write-out '\nHTTP %{http_code}\n' \
    "$url" \
    --data '{
      "model": "gpt-6-luna",
      "input": "Reply with hello.",
      "max_output_tokens": 64,
      "stream": false
    }'
