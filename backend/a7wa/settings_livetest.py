"""Settings for running a test suite INSIDE the live image (ops/wa.sh leadai-tests).

The production settings with every way out of the container shut, so a test
that forgets to fake something fails instead of reaching a real system:
- Celery's broker is in memory: no task reaches the live workers;
- the channel layer is in memory: no event reaches an agent's browser;
- the gateway, Meta, Bitrix, OpenWA and OpenAI point nowhere or have no key;
- uploaded files go to /tmp.
The database is the live Postgres server, but Django's test runner creates
and drops its own test_<name> database; the live database is never touched.

ops/wa.sh also overrides the broker and Redis variables in the container's
environment, because Celery reads CELERY_BROKER_URL from the environment
before it reads settings.
"""

from pathlib import Path

from a7wa.settings import *  # noqa: F401,F403

NOWHERE = "http://127.0.0.1:9"

CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
MEDIA_ROOT = Path("/tmp/a7wa-livetest-media")

ALOTS_BASE_URL = NOWHERE
ALOTS_API_KEY = "test-key"
ALOTS_WEBHOOK_TOKEN = "test-token"
ALOTS_UI_COOKIE = ""
META_GRAPH_ACCESS_TOKEN = ""
META_GRAPH_BASE_URL = NOWHERE
BITRIX_WEBHOOK_URL = ""
OPENAI_API_KEY = ""
LEADAI_OPENAI_API_KEY = ""
LEADAI_BITRIX_NOTIFY_URL = NOWHERE + "/notify"
OPENWA_INTERNAL_URL = NOWHERE
OPENWA_MASTER_KEY = ""
DEVICE_ALERT_RECIPIENTS = []
