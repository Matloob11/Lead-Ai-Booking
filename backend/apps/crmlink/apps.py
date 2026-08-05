from django.apps import AppConfig


class CrmLinkConfig(AppConfig):
    name = "apps.crmlink"
    verbose_name = "CRM link"

    def ready(self):
        # Importing for the side effect: the receiver registers itself.
        from . import signals  # noqa: F401
