# Campfire: Django + Vite + MCP

A learning app with a shared forum, Django accounts, PostgreSQL, and a small
vanilla-JavaScript Vite frontend. Sign in to use either workspace tab:

- **Forum**: read/post messages and privately summarize the conversation.
- **MCP tools**: read recent messages, summarize, or draft a reply. Review a
  draft and explicitly move it to the composer; only **Send** publishes it.

The browser uses authenticated, CSRF-protected Django JSON endpoints. Its tools
tab is a playground for the same Python functions exposed by the stdio MCP
server, not a browser MCP transport. The server exposes three tools:
`recent_messages`, `summarize_forum`, and `draft_reply`.

## Local development

From `backend/`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
export DJANGO_SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
export DJANGO_DEBUG=true DATABASE_ENGINE=django.db.backends.sqlite3 DATABASE_NAME=db.sqlite3
export CSRF_TRUSTED_ORIGINS=http://localhost:5173
python manage.py migrate
python manage.py runserver
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173` and register. Vite proxies `/api/` to Django.
`.env.example` documents the variables; Django does not load it automatically.
Without gateway credentials, accounts, messages, and the recent-messages tool
still work; AI tools return an explicit configuration error.

### Agentgateway

All inference, including MCP-triggered inference, uses the shared `chat/llm.py`
client. It calls `/v1/responses` with `gpt-6-luna`, `stream: false`,
`store: false`, a 1,024-token output cap, and a 20-second timeout. There is no
direct provider fallback or automatic retry.

For local AI use, port-forward the existing gateway:

```sh
kubectl -n agentgateway port-forward service/agentgateway-proxy 4000:4000
```

In the backend/MCP environment set `AGENTGATEWAY_BASE_URL=http://127.0.0.1:4000/v1`
and securely supply `AGENTGATEWAY_API_KEY` with the existing **forum-app** client
key, not a Copilot/provider token. Never put it in a `VITE_` variable or commit it.
Alternatively, `AGENTGATEWAY_CLIENT_CREDENTIALS` accepts the gateway's JSON secret
entry (`key` and `metadata.client_id`, which must be `forum-app`).

Summaries and drafts send up to 20 recent shared messages, plus the draft idea,
to the configured provider through the gateway. Do not post sensitive data.
The gateway applies guards and shares a quota of 10 requests/minute and 100,000
input/output tokens/day across browser and MCP calls. Guards are not complete
data-loss or prompt-injection protection; AI text must be reviewed.

### MCP client

Use the same database and environment as Django, then launch from `backend/`:

```sh
.venv/bin/python manage.py mcp_server --username YOUR_REGISTERED_USERNAME
```

Configure an MCP-capable client with that executable, the absolute path to
`manage.py`, `mcp_server`, and `--username` as arguments, and the backend directory
as its working directory. Supply the Django/database/gateway environment to the
client process too. For SQLite, use an absolute `DATABASE_NAME` path.

The username must identify an active forum account. This is a **trusted local
operator** command with database access, not password-based MCP authentication;
do not expose it as a public service. The command uses stdio only, and the MCP
adapter runs tools on Django's synchronous database thread and closes stale
connections. Logs go to stderr.

To access the cluster database through the existing backend environment, a local
MCP client can instead launch `kubectl` with these arguments (no `-t`):

```sh
kubectl -n webapp-django-vite exec -i deployment/webapp-django-vite-backend -- \
  python manage.py mcp_server --username YOUR_REGISTERED_USERNAME
```

## Checks

From `backend/`, with the development environment above:

```sh
ruff check .
python manage.py makemigrations --check --dry-run
python manage.py test
```

From `frontend/`, run `npm run lint` and `npm run build`. Backend tests exercise
tool access, shared context, the gateway request contract/errors, and MCP SDK
tool discovery/execution without spending real inference quota.

## Containers and Kubernetes

From this directory, `docker buildx bake` builds backend/frontend images for
amd64 and arm64. Set `TAGS=1.2.3` and `REGISTRY` to override defaults.
The backend runs migrations on startup and serves collected Django admin static
files through WhiteNoise. nginx serves the frontend and proxies the Django API,
admin, and static paths.

`apps/webapp-django-vite` deploys the app at `https://chat.localhost`, with a
CloudNativePG database and the SOPS-managed Django signing key. Reflector copies
the existing `agentgateway-client-keys` Secret into the app namespace; the
backend reads only its `forum-app` JSON entry. The source Secret's reflector
annotations allow both namespaces, with credentials kept SOPS-encrypted.
Flux waits for the database operator and gateway configuration.
Startup/readiness/liveness probes explicitly send an allowed Host header.

The image workflow builds same-repository PR previews tagged `pr-N`.
Releases publish only `X.Y.Z` from the **release tag's revision**, including
manual dispatches. No `dev`, `dev-X.Y.Z`, or `latest` aliases are published.
PR titles follow Conventional Commits; the release workflow tags the merged
commit and explicitly dispatches image publishing because releases created with
`GITHUB_TOKEN` do not trigger another workflow automatically.

The manifests currently use the legacy `dev` tag. Select a published `X.Y.Z`
release or `pr-N` preview for both deployment images in Git to deploy it.
Make both GHCR packages public, or provide an image pull secret.
