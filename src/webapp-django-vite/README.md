# Campfire: Django + Vite + MCP

A learning app with a shared forum, Django accounts, PostgreSQL, and a small
vanilla-JavaScript Vite frontend. Sign in to use either workspace tab:

- **Forum**: read/post messages and privately summarize the conversation.
- **Ask Campfire**: ask a question about the shared forum and get a private,
  AI-generated answer with retrieved messages to check as sources.
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
Ask Campfire searches the full forum by matching up to 12 meaningful question
words against message text, ranks matches by the number of matching words (then
recency), and sends the question and up to 8 matching messages to the gateway.
This is keyword retrieval, not semantic search: reword the question if a
relevant discussion is missed. With no matches, no AI request is made. The
displayed sources are the retrieved messages, not verified citations; check
the answer against them. Questions and answers are not posted to the forum.
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
amd64 and arm64. Set `TAGS=webapp-django-vite-1.2.3` and `REGISTRY` to override defaults.
The backend runs migrations on startup and serves collected Django admin static
files through WhiteNoise. nginx serves the frontend and proxies the Django API,
admin, and static paths.

`apps/webapp-django-vite` deploys the app at `https://campfire.localhost`, with a
CloudNativePG database and the SOPS-managed Django signing key. Reflector copies
the existing `agentgateway-client-keys` Secret into the app namespace; the
backend reads only its `forum-app` JSON entry. The source Secret's reflector
annotations allow both namespaces, with credentials kept SOPS-encrypted.
Flux waits for the database operator and gateway configuration.
Startup/readiness/liveness probes explicitly send an allowed Host header.

The image workflow builds same-repository PR previews tagged `pr-N`.
When a push to `main` changes `src/webapp-django-vite/**`, the same workflow automatically builds
both images tagged `X.Y.Z`, then creates a GitHub Release and Git tag named
`webapp-django-vite-X.Y.Z`. No manual tag push or separate release workflow is
needed. No `dev`, `dev-X.Y.Z`, or `latest` aliases are published.

Versions are calculated from commits touching `src/webapp-django-vite/` since the previous app
tag: Conventional Commit `!` or `BREAKING CHANGE:` bumps major, `feat:` bumps
minor, and all other source changes bump patch. Use Conventional Commit titles
when squash-merging PRs. Changes outside this app do not create releases.
The initial baseline is `1.0.0`, using legacy `v1.0.0` as the history boundary
when present. Subsequent versions use only the app-prefixed tags. A rerun of an
already released commit reuses its version. Images are published before the
release is created, so no chained workflow trigger is needed.

The deployments start at the published `1.0.0` images. Renovate only accepts
plain `X.Y.Z` image tags for them.
On its next run after publication, Renovate can propose a grouped
backend/frontend update, ignoring `pr-N` previews. Existing
repository rules allow minor/patch automerge but require review for major updates.
Flux rolls out the new images after that Renovate PR merges, not merely when
the image tags appear.

Renovate also updates the app's own dependencies: `requirements*.txt`,
`frontend/package.json` and its lockfile, and the Dockerfile base images.  Updates are
grouped into one backend PR (Python packages, backend base image, CI Python) and
one frontend PR (npm packages, frontend base images, CI Node.js), so the
Dockerfiles and `lint-src.yaml` stay on the same runtime. Major updates get a
separate `major-` PR for review. Merged dependency PRs release a new patch version.

To test a PR, temporarily select its `pr-N` tag for both deployments in Git.
Return to a stable `X.Y.Z` tag afterward so Renovate can track upgrades.
Make both GHCR packages public, or provide an image pull secret.
