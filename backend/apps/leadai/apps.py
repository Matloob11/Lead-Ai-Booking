from django.apps import AppConfig


class LeadAiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leadai"
    label = "leadai"
    verbose_name = "Lead AI screen"

    def ready(self):
        from . import signals  # noqa: F401
