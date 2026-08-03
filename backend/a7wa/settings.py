"""Settings for the A7 WhatsApp agent inbox.

Single-tenant: one alots.io account, many WABA numbers, many Bitrix agents.
Everything environment-specific comes from the environment; see deploy/.env.example.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def env_bool(name, default=False):
    return str(os.environ.get(name, default)).lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# The panel is served inside a Bitrix24 placement iframe, so the portal origin
# must be trusted for CSRF and allowed as a CORS origin.
BITRIX_PORTAL_URL = env("BITRIX_PORTAL_URL", "https://crm.a7grouprealestatedxb.com").rstrip("/")
PANEL_BASE_URL = env("PANEL_BASE_URL", "https://wa.srv1802669.hstgr.cloud").rstrip("/")

CSRF_TRUSTED_ORIGINS = [BITRIX_PORTAL_URL, PANEL_BASE_URL]
CORS_ALLOWED_ORIGINS = [BITRIX_PORTAL_URL, PANEL_BASE_URL]
CORS_ALLOW_CREDENTIALS = True

# Cookies must survive the cross-site iframe, which requires SameSite=None+Secure.
SESSION_COOKIE_SAMESITE = "None"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "apps.accounts",
    "apps.catalog",
    "apps.inbox",
    "apps.gateway",
    "apps.reports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "a7wa.urls"
ASGI_APPLICATION = "a7wa.asgi.application"
WSGI_APPLICATION = "a7wa.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

AUTH_USER_MODEL = "accounts.Agent"

# Data stores
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "a7wa"),
        "USER": env("POSTGRES_USER", "a7wa"),
        "PASSWORD": env("POSTGRES_PASSWORD", "a7wa"),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = "Asia/Dubai"

# Templates are created and approved in the gateway's own panel, so the mirror
# would go stale on its own. Hourly is frequent enough that a template approved
# during the day is usable the same day, and cheap: one call per WABA.
# Channels change far less often, so they are refreshed a few times a day.
CELERY_BEAT_SCHEDULE = {
    "sync-templates-hourly": {
        "task": "apps.catalog.tasks.sync_templates",
        "schedule": 60 * 60,
    },
    "sync-numbers-every-6h": {
        "task": "apps.catalog.tasks.sync_numbers",
        "schedule": 6 * 60 * 60,
    },
    # A follow-up set for 15:00 should not surface at 15:04.
    "fire-due-reminders": {
        "task": "apps.inbox.tasks.fire_due_reminders",
        "schedule": 60,
    },
    # The last cheap hour before a free-form window shuts.
    "warn-closing-windows": {
        "task": "apps.inbox.tasks.warn_closing_windows",
        "schedule": 15 * 60,
    },
}

# Localisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", BASE_DIR / "media"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "a7wa.exceptions.exception_handler",
}

# alots.io (WBBOX) gateway
# ---------------------------------------------------------------------------
ALOTS_BASE_URL = env("ALOTS_BASE_URL", "https://alots.io").rstrip("/")
ALOTS_API_KEY = env("ALOTS_API_KEY", "")
ALOTS_VERSION = env("ALOTS_VERSION", "v23.0")
ALOTS_TIMEOUT = float(env("ALOTS_TIMEOUT", "30"))

# Shared secret alots sends back on every webhook call, configured per number in
# their panel as a Bearer token. Requests without it are rejected.
ALOTS_WEBHOOK_TOKEN = env("ALOTS_WEBHOOK_TOKEN", "")

# Meta closes the free-form window 24h after the customer's last inbound message.
SESSION_WINDOW_HOURS = int(env("SESSION_WINDOW_HOURS", "24"))

# What the gateway will actually forward. Its /messages endpoint is documented
# as a raw pass-through to Meta but is really an allowlist, verified by probing
# each type on 2026-08-02:
#
#   forwarded : text, image, video, audio, document, sticker, location,
#               template, interactive
#   rejected  : read (receipts, and the typing indicator that rides on them),
#               reaction, contacts, order, button, system
#               -> "Unsupported message type: <x>"
#
# So blue ticks, "typing…" and sending reactions are unavailable through this
# gateway however correct our payload is. Inbound reactions still arrive over
# the webhook. These flags exist so we neither waste a call on a send that
# cannot succeed nor offer the agent a button that will never work — flip them
# if the gateway widens its allowlist.
GATEWAY_SUPPORTS_READ_RECEIPTS = env_bool("GATEWAY_SUPPORTS_READ_RECEIPTS", False)
GATEWAY_SUPPORTS_TYPING = env_bool("GATEWAY_SUPPORTS_TYPING", False)
GATEWAY_SUPPORTS_REACTIONS = env_bool("GATEWAY_SUPPORTS_REACTIONS", False)
GATEWAY_SUPPORTS_CONTACT_CARDS = env_bool("GATEWAY_SUPPORTS_CONTACT_CARDS", False)

# Hosts the media downloader may fetch from. The URL it follows arrives inside a
# webhook body, so it is third-party input: without this list a crafted payload
# would turn the worker into a proxy for anything reachable from the box — and
# this box also runs Frappe, n8n and their databases. The gateway's own host is
# added automatically.
MEDIA_ALLOWED_HOSTS = env_list("MEDIA_ALLOWED_HOSTS", "gsauth.com,lookaside.fbsbx.com")

# Of those, the only host that may ever see our bearer token. The gateway's CDN
# serves media unauthenticated and has no need for it.
MEDIA_AUTHENTICATED_HOSTS = env_list("MEDIA_AUTHENTICATED_HOSTS", "lookaside.fbsbx.com")

# Bitrix24
# ---------------------------------------------------------------------------
BITRIX_CLIENT_ID = env("BITRIX_CLIENT_ID", "")
BITRIX_CLIENT_SECRET = env("BITRIX_CLIENT_SECRET", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}
