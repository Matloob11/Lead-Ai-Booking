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
    #
    # Two sources, because neither alone is right. Portal admins should not have
    # to be granted access twice, but the panel also needs admins who are not
    # Bitrix admins. So ``is_bitrix_admin`` is refreshed from the portal on every
    # sign-in — losing it there loses it here — while ``is_wa_admin`` is a manual
    # grant that survives.
    is_wa_admin = models.BooleanField(default=False, help_text="Granted here, independent of Bitrix")
    is_bitrix_admin = models.BooleanField(default=False, help_text="Mirrored from the portal at sign-in")

    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_name", "username"]

    def __str__(self):
        return self.display_name or self.username

    @property
    def has_admin_rights(self):
        """Whether this agent administers the panel, from either source."""
        return self.is_wa_admin or self.is_bitrix_admin or self.is_superuser

    @property
    def visible_numbers(self):
        """Numbers whose chats this agent may open."""
        from apps.catalog.models import WabaNumber

        if self.has_admin_rights:
            return WabaNumber.objects.filter(is_active=True)
        return WabaNumber.objects.filter(
            is_active=True,
            assignments__agent=self,
            assignments__is_active=True,
        ).distinct()
