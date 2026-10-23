# Django + Vite chat

Campfire is a single shared channel. Users register or sign in with a Django
account before reading or posting messages. Django stores accounts and messages
in PostgreSQL; the frontend uses the same-origin JSON API and session cookies.

## Local development

Run the backend from `backend/` with a generated secret key and SQLite:

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

In another terminal, run the Vite frontend:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api/` requests to Django.

## Container images

From this directory, `docker buildx bake` builds the backend and frontend with
the `dev` tag by default. Set `TAGS=v1.2.3,dev` for a versioned release and
`REGISTRY` to override the image namespace. The GitHub workflow uses `dev` for
pull-request dry runs and derives the release tag from the merged PR title,
which must start with `vMAJOR.MINOR.PATCH`.
