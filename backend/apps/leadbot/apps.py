from django.apps import AppConfig


class LeadbotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leadbot"
    label = "leadbot"
    verbose_name = "Lead WhatsApp AI"

    def ready(self):
        from . import signals  # noqa: F401
