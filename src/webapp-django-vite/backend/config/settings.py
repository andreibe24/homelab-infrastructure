import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host
]
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.environ.get(
            "DATABASE_ENGINE", "django.db.backends.postgresql"
        ),
        "NAME": os.environ.get("DATABASE_NAME", "chatdb"),
        "USER": os.environ.get("DATABASE_USER", "chatuser"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", ""),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
    }
}

# Reads go to the replica connection only when a replica host is configured.
DATABASE_REPLICA_HOST = os.environ.get("DATABASE_REPLICA_HOST")
DATABASE_ROUTERS = []
if DATABASE_REPLICA_HOST:
    DATABASES["replica"] = {
        **DATABASES["default"],
        "HOST": DATABASE_REPLICA_HOST,
        "TEST": {"MIRROR": "default"},
    }
    DATABASE_ROUTERS = ["config.db_router.PrimaryReplicaRouter"]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 65536

OIDC_ENABLED = os.environ.get("OIDC_ENABLED", "false").lower() == "true"
if OIDC_ENABLED:
    INSTALLED_APPS += ["mozilla_django_oidc"]
    AUTHENTICATION_BACKENDS = ["chat.oidc.CampfireOIDCBackend"]
    OIDC_RP_CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
    OIDC_RP_CLIENT_SECRET = os.environ["OIDC_CLIENT_SECRET"]
    OIDC_ISSUER = os.environ["OIDC_ISSUER"].rstrip("/")
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{OIDC_ISSUER}/protocol/openid-connect/auth"
    OIDC_BACKCHANNEL = os.environ["OIDC_BACKCHANNEL"].rstrip("/")
    OIDC_OP_TOKEN_ENDPOINT = f"{OIDC_BACKCHANNEL}/protocol/openid-connect/token"
    OIDC_OP_USER_ENDPOINT = f"{OIDC_BACKCHANNEL}/protocol/openid-connect/userinfo"
    OIDC_OP_JWKS_ENDPOINT = f"{OIDC_BACKCHANNEL}/protocol/openid-connect/certs"
    OIDC_RP_SIGN_ALGO = "RS256"
    OIDC_VERIFY_SSL = os.environ.get("OIDC_CA_FILE") or True
    OIDC_RP_SCOPES = "openid profile"
    OIDC_USE_PKCE = True
    OIDC_TIMEOUT = 10
    SESSION_COOKIE_AGE = 3600
    LOGIN_REDIRECT_URL = "/"
    LOGIN_REDIRECT_URL_FAILURE = "/?login=failed"

AGENTGATEWAY_BASE_URL = os.environ.get(
    "AGENTGATEWAY_BASE_URL", "http://agentgateway-proxy.agentgateway.svc.cluster.local:4000/v1"
)
AGENTGATEWAY_API_KEY = os.environ.get("AGENTGATEWAY_API_KEY", "")
AGENTGATEWAY_CLIENT_CREDENTIALS = os.environ.get("AGENTGATEWAY_CLIENT_CREDENTIALS", "")
RAG_SERVICE_URL = os.environ.get(
    "RAG_SERVICE_URL", "http://webapp-django-vite-rag:8080"
)
