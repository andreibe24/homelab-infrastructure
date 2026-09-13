"""Minimal Django settings for the homelab demo webapp.

Every value that differs between environments is read from the environment, which
is populated in-cluster by:

  * ConfigMap `webapp-backend-env`     (apps/base/webapp/configmap-app.yaml)
  * Secret    `webapp-backend-secrets` (created by the repo-wide secret mechanism
                                        owned by topic 3 -- never committed here)
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    # Ephemeral key so the container still boots in a cluster where the Secret has
    # not been provisioned yet. Sessions/signatures do not survive a restart.
    from django.core.management.utils import get_random_secret_key

    SECRET_KEY = get_random_secret_key()

DEBUG = _env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "*")

CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# The SPA is served from a different origin than the HTTP/3 API endpoint
# (see apps/base/webapp/README.md), so the browser sends cross-origin requests.
CORS_ALLOWED_ORIGINS = _env_list("DJANGO_CORS_ALLOWED_ORIGINS")

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "api",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "api.middleware.CorsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

ASGI_APPLICATION = "config.asgi.application"

# No database in the demo app; the DATABASES mapping stays empty on purpose so the
# image has no driver dependencies. Add django_prometheus.db.backends.postgresql
# here when a real datastore is introduced.
DATABASES: dict[str, dict[str, str]] = {}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# TLS is terminated by Hypercorn itself on the QUIC/HTTPS listener and by
# ingress-nginx on the SPA path, so trust the standard forwarded header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Advertised to browsers by the frontend and by Hypercorn (see hypercorn.toml).
HTTP3_ALT_SVC = os.environ.get("HTTP3_ALT_SVC", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
