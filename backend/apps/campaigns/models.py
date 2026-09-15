from django.conf import settings
from django.db import models


# Auto-retry: wait this long, then try again — up to MAX_SEND_ATTEMPTS total tries.
MAX_SEND_ATTEMPTS = 5
RETRY_AFTER_MINUTES = 5


class Campaign(models.Model):
    """Bulk template send. Every recipient is tied to Bitrix Owner Data (SPA 1042)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        RETRYING = "retrying", "Retrying"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(max_length=200, blank=True)
    number = models.ForeignKey("catalog.WabaNumber", on_delete=models.PROTECT, related_name="campaigns")
    template = models.ForeignKey("catalog.WaTemplate", on_delete=models.PROTECT, related_name="campaigns")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="campaigns"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    variables = models.JSONField(default=dict, blank=True)
    header_variables = models.JSONField(default=dict, blank=True)
    button_variables = models.JSONField(default=dict, blank=True)
    header_media_id = models.CharField(max_length=255, blank=True)
    total = models.PositiveIntegerField(default=0)
    sent = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    error_detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Campaign #{self.pk}"


class CampaignRecipient(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"  # will auto-retry until exhausted
        EXHAUSTED = "exhausted", "Exhausted"  # 5 attempts used — permanent fail
        SKIPPED = "skipped", "Skipped"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="recipients")
    phone = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=200, blank=True)
    variables = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    owner_data_id = models.PositiveIntegerField(null=True, blank=True)
    owner_data_created = models.BooleanField(default=False)
    conversation = models.ForeignKey(
        "inbox.Conversation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    error_detail = models.TextField(blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "phone"], name="uniq_campaign_phone"),
        ]

    def __str__(self):
        return f"{self.phone} ({self.status})"
