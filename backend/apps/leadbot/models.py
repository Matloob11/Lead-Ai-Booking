from django.conf import settings
from django.db import models


class LeadAutomation(models.Model):
    """One Bitrix lead driven by Official WhatsApp outreach + Sara AI."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        AWAITING_REPLY = "awaiting_reply", "Awaiting reply"
        ACTIVE = "active", "AI qualifying"
        QUALIFIED = "qualified", "Qualified"
        JUNK = "junk", "Junk / opt-out"
        FAILED = "failed", "Failed"

    bitrix_lead_id = models.PositiveIntegerField(unique=True, db_index=True)
    conversation = models.ForeignKey(
        "inbox.Conversation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lead_automations",
    )
    number = models.ForeignKey(
        "catalog.WabaNumber",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lead_automations",
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lead_automations",
    )
    state = models.CharField(max_length=32, choices=State.choices, default=State.PENDING, db_index=True)
    customer_phone = models.CharField(max_length=32, blank=True, default="")
    outreach_template_name = models.CharField(max_length=128, blank=True, default="")
    outreach_message_id = models.CharField(max_length=128, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)
    confirmed_fields = models.JSONField(default=dict, blank=True)
    qualification_reason = models.CharField(max_length=255, blank=True, default="")
    qualified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Lead {self.bitrix_lead_id} ({self.state})"

    @property
    def ai_active(self) -> bool:
        return self.state in {self.State.AWAITING_REPLY, self.State.ACTIVE}

    def panel_badge(self) -> dict | None:
        labels = {
            self.State.AWAITING_REPLY: ("AI qualifying", "awaiting"),
            self.State.ACTIVE: ("AI qualifying", "active"),
            self.State.QUALIFIED: ("Qualified", "qualified"),
            self.State.JUNK: ("Opt-out", "junk"),
            self.State.FAILED: ("Outreach failed", "failed"),
            self.State.PENDING: ("AI pending", "pending"),
        }
        label, kind = labels.get(self.state, (None, None))
        if not label:
            return None
        return {"label": label, "kind": kind, "state": self.state, "lead_id": self.bitrix_lead_id}
