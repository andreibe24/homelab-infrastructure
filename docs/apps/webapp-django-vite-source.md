# Campfire source-code map

This guide explains the application code under `src/webapp-django-vite/`.
You can understand the deployment without learning Django or Vite: Kubernetes
manifests live separately under `apps/webapp-django-vite/`. See the
[Campfire operations guide](webapp-django-vite.md) for setup, deployment, and
local development instructions.

## How a request moves through the app

```text
Browser page and JavaScript
        |
        | /api/... requests
        v
Web server (Vite locally, nginx in the container)
        |
        v
Django API
    |
    +--> PostgreSQL: accounts and forum messages
    |
    +--> RAG service
             |
             +--> PostgreSQL + pgvector: semantic retrieval
             |
             +--> agentgateway: answer generation

MCP client -> separate MCP pod -> shared forum tools and PostgreSQL
```

The browser UI never connects directly to the database or AI provider. In local
development, Vite forwards `/api/` requests to Django. In the deployed frontend
container, nginx serves the built page and forwards API, admin, and static-file
requests to the backend container. Django sends Ask Campfire questions to the
separate RAG service. That service generates embeddings locally, queries the
pgvector database, and sends retrieved text to agentgateway for answer
generation. MCP runs in its own pod, using shared backend code and the same
forum database.

## Directory and file map

```text
src/webapp-django-vite/
├── backend/                     Django server and shared app logic
│   ├── manage.py                Django command-line entry point
│   ├── requirements.txt         Python packages needed at runtime
│   ├── requirements-dev.txt     Additional lint and test tools
│   ├── config/                  Whole-project Django configuration
│   │   ├── settings.py          Environment variables, database, security, apps
│   │   ├── urls.py              URL paths mapped to backend handlers
│   │   ├── asgi.py, wsgi.py     Server integration entry points
│   │   └── __init__.py
│   └── chat/                    Forum feature and its API
│       ├── models.py            Database structure for forum messages
│       ├── views.py             HTTP handlers: login, messages, tools, questions
│       ├── tools.py             Shared forum tools and AI-assisted drafts
│       ├── rag.py               Calls the separate RAG service
│       ├── llm.py               Sends AI requests to agentgateway
│       ├── tests.py             Backend behavior tests
│       ├── admin.py, apps.py    Django admin registration and app setup
│       ├── migrations/          Versioned changes to the database structure
│       └── management/commands/
│           └── mcp_server.py    Starts stdio locally or authenticated HTTP in-cluster
├── rag/                         Embeddings, vector search, and RAG answer API
├── frontend/                    Browser interface
│   ├── index.html               Page structure and element IDs
│   ├── src/
│   │   ├── main.js              UI behavior and calls to the Django API
│   │   └── style.css            Page appearance
│   ├── package.json             Frontend scripts and direct dependencies
│   ├── package-lock.json        Exact npm dependency versions
│   ├── vite.config.js           Local frontend server and API proxy
│   └── eslint.config.js         JavaScript lint rules
├── Dockerfile.backend           Builds the Django/Gunicorn backend image
├── Dockerfile.frontend          Builds browser assets and the nginx image
├── Dockerfile.rag               Builds the semantic retrieval service image
├── nginx.conf                   Serves the page and forwards backend requests
├── docker-bake.hcl              Builds and tags all application images together
└── .env.example                 Example local settings; Django does not load it
```

The app also has `.gitignore` and `.dockerignore` files to keep local settings,
dependencies, and generated files out of Git or container build contexts.
`frontend/node_modules/`, `frontend/dist/`, Python virtual environments, and
Python cache files are generated; edit their source or dependency manifests
instead.

## Where to look for a change

| If you want to change... | Start with... |
| --- | --- |
| What the page looks like | `frontend/index.html` and `frontend/src/style.css` |
| What happens when someone clicks or submits something | `frontend/src/main.js` |
| An API URL or the backend behavior behind it | `backend/config/urls.py`, then `backend/chat/views.py` |
| Message data stored in the database | `backend/chat/models.py`; its matching schema history is in `backend/chat/migrations/` |
| Forum tools used by the page and MCP | `backend/chat/tools.py` |
| How Ask Campfire finds messages | `backend/chat/rag.py` calls retrieval in `rag/server.py` |
| How messages are embedded and ranked | `rag/server.py` and the `chat-vectors` CNPG Cluster manifest |
| The request sent to the AI gateway | `backend/chat/llm.py` |
| Database, security, or environment configuration | `backend/config/settings.py` and `.env.example` |
| A bug or regression check | `backend/chat/tests.py` or frontend lint/build checks |
| How images are built or traffic is routed | `Dockerfile.*`, `docker-bake.hcl`, and `nginx.conf` |
| What runs in Kubernetes | `apps/webapp-django-vite/`, not this source directory |

When a model changes, its migration must be updated too; do not edit an existing
applied migration just to change the current database structure. For the
commands to run tests, lint, build images, and work locally, use the
[Campfire operations guide](webapp-django-vite.md).
