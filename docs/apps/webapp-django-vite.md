# Campfire: Django + Vite + MCP

A learning app with a shared forum, Django accounts, PostgreSQL, and a small
vanilla-JavaScript Vite frontend. Sign in to use either workspace tab:

- **Forum**: read/post messages and privately summarize the conversation.
- **Ask Campfire**: ask a question about the shared forum and get a private,
  AI-generated answer with retrieved messages to check as sources.
- **MCP tools**: read recent messages, summarize, or draft a reply. Review a
  draft and explicitly move it to the composer; only **Send** publishes it.

The browser uses authenticated, CSRF-protected Django JSON endpoints. Its tools
tab is a playground for the same Python functions exposed by the MCP server,
not a browser MCP transport. The server exposes three tools:
`recent_messages`, `summarize_forum`, and `draft_reply`.

## Local development

From `src/webapp-django-vite/backend/`:

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

In another terminal, from the repository root:

```sh
cd src/webapp-django-vite/frontend
npm ci
npm run dev
```

Open `http://localhost:5173` and register. Vite proxies `/api/` to Django.
`src/webapp-django-vite/.env.example` documents the variables; Django does not
load it automatically.
Without gateway credentials, accounts, messages, and the recent-messages tool
still work; AI tools return an explicit configuration error.
Local **Ask Campfire** also needs a running RAG service, a PostgreSQL forum
database, and a pgvector-enabled embeddings database. Its local URL is
configurable with `RAG_SERVICE_URL`.

### Agentgateway

Forum summaries and drafts use `chat/llm.py`; the separate RAG service uses the
same agentgateway `/v1/responses` API for answers. Both use `gpt-6-luna`,
`stream: false`, `store: false`, a 1,024-token output cap, and a 20-second
timeout. There is no direct provider fallback or automatic retry.

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
Ask Campfire embeds forum messages locally with FastEmbed's English
`BAAI/bge-small-en-v1.5` model and stores 384-dimensional vectors in a separate
pgvector database. It retrieves up to eight nearest messages using cosine
similarity, then sends the question and those messages to the gateway. The
service synchronizes new, changed, and deleted messages before each search;
only changed messages need new embeddings. No sufficiently similar results
means no AI request is made. The displayed sources are retrieved messages, not
verified citations; check the answer against them. Questions and answers are
not posted to the forum.
The gateway applies guards and shares a quota of 10 requests/minute and 100,000
input/output tokens/day across browser and MCP calls. Guards are not complete
data-loss or prompt-injection protection; AI text must be reviewed.

### MCP client

For local development, launch the stdio MCP server from
`src/webapp-django-vite/backend/` with the same database and environment as
Django:

```sh
.venv/bin/python manage.py mcp_server --username YOUR_REGISTERED_USERNAME
```

Configure an MCP-capable client with that executable, the absolute path to
`manage.py`, `mcp_server`, and `--username` as arguments, and the backend
directory as its working directory. Supply the Django/database/gateway
environment to the client process too. For SQLite, use an absolute
`DATABASE_NAME` path.

The username must identify an active forum account. This is a **trusted local
operator** command with database access, not password-based MCP authentication.
The stdio adapter runs tools on Django's synchronous database thread and closes
stale connections. Logs go to stderr.

The cluster runs MCP in its own Deployment using Streamable HTTP. It has a
ClusterIP Service only—there is no public route. An operator with Kubernetes
access can connect from a local MCP client by port-forwarding:

```sh
kubectl -n webapp-django-vite port-forward service/webapp-django-vite-mcp 8001:8000
```

Configure the client to use `http://127.0.0.1:8001/mcp` with the header
`Authorization: Bearer <token>`. Retrieve the token from the encrypted dev
Secret without committing or sharing it:

```sh
kubectl -n webapp-django-vite get secret webapp-django-vite \
  -o jsonpath='{.data.mcp-auth-token}' | base64 --decode
```

The HTTP MCP server uses the same backend image and database, but runs as a
separate pod and process. The bearer token is stored in the SOPS-encrypted dev
Secret. Do not expose the MCP Service through a Gateway or public ingress. The
homelab Flux app remains suspended; provision its own secret before enabling it.

## Checks

From `src/webapp-django-vite/backend/`, with the development environment above:

```sh
ruff check .
python manage.py makemigrations --check --dry-run
python manage.py test
```

From `src/webapp-django-vite/frontend/`, run `npm run lint` and `npm run build`.
Backend tests exercise tool access, shared context, the gateway request
contract/errors, and MCP SDK tool discovery/execution without spending real
inference quota. The RAG service has separate Ruff and unit-test checks under
`src/webapp-django-vite/rag/`.

## Containers and Kubernetes

From `src/webapp-django-vite/`, `docker buildx bake` builds backend, frontend,
and RAG images for amd64 and arm64. Set `TAGS=webapp-django-vite-1.2.3` and
`REGISTRY` to override defaults. The backend runs migrations on startup and
serves collected Django admin static files through WhiteNoise. nginx serves the
frontend and proxies the Django API, admin, and static paths.

`apps/webapp-django-vite` deploys the app at `https://campfire.localhost`, with
CloudNativePG clusters for forum data and vector embeddings, plus the
SOPS-managed Django signing key and MCP bearer token. Reflector copies
the existing `agentgateway-client-keys` Secret into the app namespace; the
backend, RAG, and MCP workloads read only its `forum-app` JSON entry. The source
Secret's reflector annotations allow both namespaces, with credentials kept
SOPS-encrypted. Flux waits for the database operator and gateway configuration.
Startup/readiness/liveness probes explicitly send an allowed Host header.

The vector cluster uses CloudNativePG's standard PostgreSQL image, which
includes pgvector. The RAG service embeds messages locally, indexes them in
that cluster, and uses cosine similarity to retrieve sources. The embedding
model is included in the RAG image. Retrieved message text and the question are
sent to agentgateway for answer generation; embeddings are not. Plan storage
and backups for this cluster separately.

The image workflow builds same-repository PR previews tagged `pr-N`.
When a push to `main` changes `src/webapp-django-vite/**`, the same workflow automatically builds
all three images tagged `X.Y.Z`, then creates a GitHub Release and Git tag named
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

The deployments use published `X.Y.Z` images. Renovate only accepts plain
`X.Y.Z` image tags and groups the backend, frontend, and RAG images, ignoring
`pr-N` previews. Existing repository rules allow minor/patch automerge but
require review for major updates. Flux rolls out image updates after the
Renovate PR merges.

Renovate also updates backend and RAG `requirements*.txt`,
`frontend/package.json` and its lockfile, and Dockerfile base images. Updates
are grouped into backend, RAG, and frontend dependency PRs so CI and images
stay on supported runtimes. Major updates get a separate PR for review. Merged
dependency PRs release a new patch version.

To test a PR, temporarily select its `pr-N` tag for the deployments in Git.
Return to a stable `X.Y.Z` tag afterward so Renovate can track upgrades.
Make the GHCR packages public, or provide an image pull secret.

## Database connections and high availability

The `chat-db` and `chat-vectors` CloudNativePG clusters run three instances
(one primary, two streaming replicas). The backend and MCP server define two
Django connections: `default` (`DATABASE_HOST=chat-db-rw`, the primary) and
`replica` (`DATABASE_REPLICA_HOST=chat-db-ro`, the read-only replicas).
`config.db_router.PrimaryReplicaRouter` sends reads to `replica` and writes and
migrations to `default`. Leaving `DATABASE_REPLICA_HOST` unset (local SQLite
development) keeps a single connection. Reads can briefly lag writes; code that
must read its own write immediately should use `.using("default")`.

All Deployments scale between one and five replicas through KEDA
`ScaledObject`s (see [KEDA autoscaling](../components/keda.md)).
