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
    "apps.crmlink",
    "apps.campaigns",
    "apps.inboxai",
    "apps.leadbot",
    # Lead AI screen: chats a CRM campaign sent there, kept out of the main inbox.
    "apps.leadai",
    "apps.feedback",
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
# The Lead AI assistant's tasks run on their own queue and worker
# (worker-leadai in deploy/docker-compose.yml): a busy assistant must never
# slow the main inbox's webhooks or campaign sends, and a campaign day must
# never delay a meeting reminder. Beat's leadai entry is routed by name too.
CELERY_TASK_ROUTES = {"apps.leadai.tasks.*": {"queue": "leadai"}}

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
    # Campaign failed recipients: re-queue every minute; each row waits 5 min between tries (max 5).
    "retry-due-campaign-recipients": {
        "task": "apps.campaigns.tasks.retry_due_campaign_recipients",
        "schedule": 60,
    },
    # The alots panel session that mints media-header samples: its auth
    # ticket lasts six hours and slides, and its server session idles out in
    # minutes. One signed-in page every ten minutes keeps both.
    "alots-panel-keepalive": {
        "task": "apps.gateway.tasks.panel_keepalive",
        "schedule": 10 * 60,
    },
    # Lead AI: the customer's WhatsApp reminder 30 minutes before a booked
    # office visit. Checked every minute so it goes out on time.
    "leadai-due-reminders": {
        "task": "apps.leadai.tasks.send_due_reminders",
        "schedule": 60,
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

# Inbox attachments (and Feedback) travel as multipart. Files larger than
# FILE_UPLOAD_MAX_MEMORY_SIZE spill to disk; this cap is the whole request.
# Official nginx is 1024m so a ~90 MB video is not 413'd before Django runs.
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

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

# A signed-in alots *web panel* session, captured from a browser login and
# stored base64 so the cookie string survives env_file quoting. Used for one
# thing: minting the sample handle a media-header template needs, which the
# public API has no route for. See apps/gateway/panel.py.
def _decode_cookie(raw):
    import base64
    import binascii

    try:
        return base64.b64decode((raw or "").strip()).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""


ALOTS_UI_COOKIE = _decode_cookie(env("ALOTS_UI_COOKIE_B64", ""))

# Meta Graph API — template DELETE only. alots forwards GET/POST on
# message_templates but returns HTTP 405 on DELETE, so removal bypasses the
# gateway. Use the System User token from Meta Business Manager with
# whatsapp_business_management (same permanent token as in alots WABA settings).
META_GRAPH_ACCESS_TOKEN = env("META_GRAPH_ACCESS_TOKEN", "")
META_GRAPH_BASE_URL = env("META_GRAPH_BASE_URL", "https://graph.facebook.com").rstrip("/")
# The same token also uploads the sample image/video/PDF a media-header
# template is reviewed with (Meta's Resumable Upload API, which the gateway has
# no route for). That call is addressed to the app the token belongs to; it is
# looked up from Graph once per process unless set here.
META_APP_ID = env("META_APP_ID", "")

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

# An inbound webhook, which is the only credential this backend has for writing
# to the portal. The AUTH_ID an agent signs in with is spent verifying who they
# are and never kept, so nothing else here can reach Bitrix — and a message
# arriving at three in the morning has no agent's session to borrow.
#
# Ends with a slash; a method name is appended to it. Empty disables the
# mirroring entirely rather than failing every message.
BITRIX_WEBHOOK_URL = env("BITRIX_WEBHOOK_URL", "").strip()

# OpenAI — the running summary pinned to a lead
# ---------------------------------------------------------------------------
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT = int(env("OPENAI_TIMEOUT", "45"))

# Lead AI assistant (apps.leadai.assistant) — its OWN OpenAI key, used by the
# Lead AI screen's assistant and nothing else. Empty turns the assistant off;
# it never falls back to OPENAI_API_KEY above.
LEADAI_OPENAI_API_KEY = env("LEADAI_OPENAI_API_KEY", "")
LEADAI_OPENAI_MODEL = env("LEADAI_OPENAI_MODEL", "gpt-4.1-mini")
LEADAI_TRANSCRIBE_MODEL = env("LEADAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
# Seconds one attempt of a Lead AI call waits for OpenAI. Every call is also cut
# to its turn's deadline (apps/leadai/assistant/engine.py), and a retry is made
# only with a whole attempt's time left, so keep it low: a long wait spends the
# turn's time on one attempt.
LEADAI_OPENAI_TIMEOUT = int(env("LEADAI_OPENAI_TIMEOUT", "25"))
# The Bitrix-side tool that turns a Lead AI alert into a Bitrix notification;
# the backend's own webhook has no "im" scope to do it.
LEADAI_BITRIX_NOTIFY_URL = env(
    "LEADAI_BITRIX_NOTIFY_URL",
    "https://crm.a7grouprealestatedxb.com/bitrix/tools/a7_leadai_notify.php",
)
# Official Conversation Health — same default as OpenWA linked-device monitor.
CONVERSATION_HEALTH_OVERRIDE_PASSWORD = env("CONVERSATION_HEALTH_OVERRIDE_PASSWORD", "222007")

# How many messages may pass before the summary is rewritten. Every message
# would cost a model call per message on a busy number; ten keeps it current
# without the bill following the traffic.
SUMMARY_EVERY_N_MESSAGES = int(env("SUMMARY_EVERY_N_MESSAGES", "10"))

# How much of the conversation the model is shown. The tail, because what the
# customer wants now matters more than what they asked three weeks ago.
SUMMARY_CONTEXT_MESSAGES = int(env("SUMMARY_CONTEXT_MESSAGES", "60"))

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
        # httpx logs the full URL of every request it makes, at INFO. The
        # Bitrix inbound webhook carries its token in the path, so that one line
        # puts a standing credential into the container log — which far more
        # people read than the environment file it is supposed to live in.
        # WARNING keeps the failures and drops the addresses.
        "httpx": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "httpcore": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}

# The unscoped admin credential for the OpenWA gateway. Deliberately no default:
# one written here is the same key on every machine that has ever held a copy of
# this repository, and it keeps working after the environment is put right, so
# nobody discovers it was there. Empty means unconfigured, and the route that
# needs it answers 503 rather than quietly using a secret from the source.
OPENWA_MASTER_KEY = env("OPENWA_MASTER_KEY", "")
OPENWA_INTERNAL_URL = env("OPENWA_INTERNAL_URL", "http://openwa-api:2785")

# --- "a linked phone went away" alert -------------------------------------
#
# When an agent unlinks their handset the inbox stops receiving on that number,
# and nothing on any screen says so — the chats simply stop. These settings are
# how the people who need to know get told.
#
# Sent as a TEMPLATE on purpose. The 24-hour free-form window opens only on an
# inbound message, so a cold alert to an admin who has not written today cannot
# be plain text; it would fail with 131047 exactly when it matters. The template
# is UTILITY, not MARKETING, so it is outside Meta's per-customer daily cap that
# the marketing templates share.
DEVICE_ALERT_TEMPLATE = env("DEVICE_ALERT_TEMPLATE", "whatsapp_device_disconnected")
DEVICE_ALERT_TEMPLATE_LANG = env("DEVICE_ALERT_TEMPLATE_LANG", "en")

# Who hears about it. Digits only, no '+' — that is what the gateway expects.
DEVICE_ALERT_RECIPIENTS = env_list(
    "DEVICE_ALERT_RECIPIENTS",
    "923078633218,971503928461,971555484423",
)

# The number the alert is sent FROM, and the one to try when that fails. Two
# different WABAs on purpose: an alert that shares a business account with the
# thing that has gone wrong is an alert that can go down with it. The template is
# approved on both.
DEVICE_ALERT_PHONE_ID = env("DEVICE_ALERT_PHONE_ID", "1170318422839203")
DEVICE_ALERT_PHONE_ID_BACKUP = env("DEVICE_ALERT_PHONE_ID_BACKUP", "1198764669988838")

# Shared with the gateway, which is the only thing that calls the alert route.
# No default: an empty secret must refuse every caller rather than accept any.
DEVICE_ALERT_SECRET = env("DEVICE_ALERT_SECRET", "")

# Shared with the Bitrix CRM PHP tool (a7_lead_wa.config.php). The leads-list
# button has a portal session, not a Django cookie, so the tool signs the JSON
# body. Empty refuses every caller — same rule as DEVICE_ALERT_SECRET.
CRM_LEAD_WA_SECRET = env("CRM_LEAD_WA_SECRET", "")

# Official lead qualification (replaces n8n WhatsApp CRM v9).
# Template must be APPROVED on each agent's 971 WABA before outreach can send.
LEADBOT_OUTREACH_TEMPLATE = env("LEADBOT_OUTREACH_TEMPLATE", "a7_lead_enquiry_confirm")
# Optional override. Empty falls back to CRM_LEAD_WA_SECRET (same HMAC as a7_lead_wa).
LEADBOT_OUTREACH_SECRET = env("LEADBOT_OUTREACH_SECRET", "")
