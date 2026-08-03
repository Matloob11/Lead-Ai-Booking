from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.utils import timezone


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

    # Set once the agent renames themselves in the panel. Sign-in refreshes the
    # display name from the portal, which would otherwise undo that edit on the
    # agent's very next visit and make the profile screen look broken.
    display_name_is_custom = models.BooleanField(default=False)

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


class AccessRequest(models.Model):
    """An agent asking to be given a number to work.

    Agents arrive through Bitrix with nothing assigned — the panel cannot know
    which number is theirs — so their first sight of it is an empty inbox. This
    is the way out of that: they say who they are, an admin sees it without
    being told separately, and assigns them a number.

    Resolving does not grant anything. It only marks that an admin has dealt
    with the request; the grant itself is the number assignment.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="access_requests")
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        Agent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_access_requests",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One open request per agent. Pressing the button twice should not
            # put the same person in an admin's list twice.
            models.UniqueConstraint(
                fields=["agent"],
                condition=Q(status="pending"),
                name="one_pending_access_request_per_agent",
            )
        ]

    def __str__(self):
        return f"{self.agent} ({self.status})"

    def resolve(self, by):
        self.status = self.Status.RESOLVED
        self.resolved_at = timezone.now()
        self.resolved_by = by
        self.save(update_fields=["status", "resolved_at", "resolved_by"])
        return self
