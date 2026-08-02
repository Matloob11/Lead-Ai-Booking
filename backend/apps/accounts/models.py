from django.contrib.auth.models import AbstractUser
from django.db import models


class Agent(AbstractUser):
    """A person who works the inbox.

    Identity comes from Bitrix24: agents never sign in here directly, they land
    in the panel through the Bitrix placement iframe and are matched on
    ``bitrix_user_id``. ``username`` is kept only because Django's auth stack
    requires it, and is derived from the Bitrix id.
    """

    bitrix_user_id = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    bitrix_portal = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(blank=True)

    # Distinct from is_staff/is_superuser, which govern the Django admin. This
    # flag governs the WhatsApp panel: every number, every chat, and the right
    # to reassign a conversation to another agent.
    is_wa_admin = models.BooleanField(default=False)

    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_name", "username"]

    def __str__(self):
        return self.display_name or self.username

    @property
    def visible_numbers(self):
        """Numbers whose chats this agent may open."""
        from apps.catalog.models import WabaNumber

        if self.is_wa_admin:
            return WabaNumber.objects.filter(is_active=True)
        return WabaNumber.objects.filter(
            is_active=True,
            assignments__agent=self,
            assignments__is_active=True,
        ).distinct()
