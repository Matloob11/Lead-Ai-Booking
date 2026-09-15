from django.apps import AppConfig


class InboxAiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inboxai"
    label = "inboxai"
    verbose_name = "Inbox AI desk"

    def ready(self):
        from . import signals  # noqa: F401
