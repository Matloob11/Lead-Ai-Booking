from django.db import models


class WabaNumber(models.Model):
    """One WhatsApp Business number as alots.io exposes it.

    In this account every number carries its own ``waba_business_id``, and
    templates are approved per WABA — so the template list an agent sees is
    resolved through this field, not through the phone number.
    """

    class Quality(models.TextChoices):
        GREEN = "GREEN", "Green"
        YELLOW = "YELLOW", "Yellow"
        RED = "RED", "Red"
        HIGH = "HIGH", "High"
        UNKNOWN = "UNKNOWN", "Unknown"

    phone_number = models.CharField(max_length=32, unique=True)
    phone_number_id = models.CharField(max_length=64, unique=True, db_index=True)
    waba_business_id = models.CharField(max_length=64, db_index=True)

    # What the gateway calls it. Its channel API does not actually return this,
    # so it is usually empty.
    display_name = models.CharField(max_length=255, blank=True)

    # What we call it. Admins set this themselves — normally the agent who works
    # the number — and it is what the panel shows, so a sync can never wipe it.
    label = models.CharField(max_length=255, blank=True)
    quality_rating = models.CharField(max_length=16, choices=Quality.choices, default=Quality.UNKNOWN)
    verification_status = models.CharField(max_length=32, blank=True)
    messaging_limit = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True)
    webhook_configured = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["phone_number"]

    def __str__(self):
        return f"{self.phone_number} ({self.label or self.display_name or 'unnamed'})"

    @property
    def title(self):
        """What to print for this number, falling back through what we know.

        The admin's own label wins: the gateway's display_name is whatever was
        registered with Meta, while the label is usually the agent who holds
        the number, which is what the team actually calls it.
        """
        return self.label or self.display_name or self.phone_number

    @property
    def templates(self):
        return WaTemplate.objects.filter(waba_business_id=self.waba_business_id)


class NumberAssignment(models.Model):
    """Links an agent to a number.

    Many-to-many on purpose: an agent may cover a second number while a
    colleague is on leave, and a number may be worked by more than one agent.
    """

    class Role(models.TextChoices):
        PRIMARY = "primary", "Primary"
        BACKUP = "backup", "Backup"

    number = models.ForeignKey(WabaNumber, on_delete=models.CASCADE, related_name="assignments")
    agent = models.ForeignKey("accounts.Agent", on_delete=models.CASCADE, related_name="number_assignments")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.PRIMARY)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["number", "agent"],
                condition=models.Q(is_active=True),
                name="unique_active_number_agent",
            )
        ]
        ordering = ["number", "role"]

    def __str__(self):
        return f"{self.agent} -> {self.number} ({self.role})"


class WaTemplate(models.Model):
    """A Meta-approved message template, mirrored from alots.io.

    Only APPROVED templates can reopen a closed session window, but rejected and
    pending ones are kept so admins can see why something is unavailable.
    """

    class Status(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        PENDING = "PENDING", "Pending"
        REJECTED = "REJECTED", "Rejected"
        PAUSED = "PAUSED", "Paused"
        DISABLED = "DISABLED", "Disabled"

    waba_business_id = models.CharField(max_length=64, db_index=True)
    meta_template_id = models.CharField(max_length=64, blank=True, db_index=True)

    name = models.CharField(max_length=255)
    language = models.CharField(max_length=16, default="en")
    category = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    # Meta's raw component array, kept verbatim so the composer can render
    # headers, buttons, and variable placeholders without a lossy translation.
    components = models.JSONField(default=list)

    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["waba_business_id", "name", "language"],
                name="unique_template_per_waba",
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} [{self.language}]"

    def _component(self, kind):
        for component in self.components:
            if component.get("type") == kind:
                return component
        return None

    @staticmethod
    def _count_placeholders(text):
        import re

        return len(set(re.findall(r"\{\{(\d+)\}\}", text or "")))

    @property
    def body_text(self):
        component = self._component("BODY")
        return component.get("text", "") if component else ""

    @property
    def footer_text(self):
        component = self._component("FOOTER")
        return component.get("text", "") if component else ""

    @property
    def header(self):
        """The header as the composer needs it, or None.

        ``format`` decides what the sender must supply: TEXT headers may carry
        their own {{1}}, while IMAGE/VIDEO/DOCUMENT headers need a media id
        uploaded before the template can go out.
        """
        component = self._component("HEADER")
        if not component:
            return None
        text = component.get("text", "")
        return {
            "format": component.get("format", "TEXT"),
            "text": text,
            "variable_count": self._count_placeholders(text),
        }

    @property
    def buttons(self):
        component = self._component("BUTTONS")
        if not component:
            return []
        return [
            {
                "type": b.get("type", ""),
                "text": b.get("text", ""),
                "url": b.get("url", ""),
                "phone_number": b.get("phone_number", ""),
            }
            for b in component.get("buttons", [])
        ]

    @property
    def variable_count(self):
        """How many positional {{n}} placeholders the body expects."""
        return self._count_placeholders(self.body_text)

    @property
    def requires_header_media(self):
        header = self.header
        return bool(header and header["format"] in {"IMAGE", "VIDEO", "DOCUMENT"})
