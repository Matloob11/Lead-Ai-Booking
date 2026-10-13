from django.conf import settings
from django.db import models


# Auto-retry: wait this long, then try again — up to MAX_SEND_ATTEMPTS total tries.
MAX_SEND_ATTEMPTS = 5
RETRY_AFTER_MINUTES = 5


class CrmTarget(models.TextChoices):
    """Where a send's CRM card goes.

    Empty on a ``Campaign`` means what it always meant — an Availability card
    per recipient — so nothing made before the Excel screen existed changes.
    """

    NONE = "none", "No CRM card"
    OWNER_DATA = "owner_data", "Owner Data (calling board)"
    AVAILABILITY = "availability", "Availability"


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

    # Set only by the Excel batch screen: which upload this number's share
    # belongs to, and whether a CRM card is wanted at all. Empty keeps the
    # original behaviour for every campaign made anywhere else.
    batch = models.ForeignKey(
        "CampaignBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
    )
    crm_target = models.CharField(max_length=16, choices=CrmTarget.choices, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Campaign #{self.pk}"


class CampaignBatch(models.Model):
    """One spreadsheet sent through several numbers.

    The batch is what the agent started. Each child ``Campaign`` is one
    number's share of it — capped, so the per-number runner, the retry wave,
    the webhook reconciliation and the old History screen keep working without
    knowing a batch exists.
    """

    name = models.CharField(max_length=200, blank=True)
    template_name = models.CharField(max_length=255)
    template_language = models.CharField(max_length=16, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="campaign_batches"
    )
    source_filename = models.CharField(max_length=255, blank=True)
    # {"phone": col, "name": col | null, "vars": {"1": {"column": col} | {"value": "text"}}}
    column_map = models.JSONField(default=dict, blank=True)
    per_number_cap = models.PositiveIntegerField(default=300)
    crm_target = models.CharField(max_length=16, choices=CrmTarget.choices, default=CrmTarget.NONE)
    # Rows handed to numbers, and rows no number had room for.
    total = models.PositiveIntegerField(default=0)
    leftover = models.PositiveIntegerField(default=0)
    # [{"number_id", "phone", "label", "reason"}] — ticked but unusable.
    skipped_numbers = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"Batch #{self.pk}"


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
    # CRM Lead this row was sent from (Leads list / kanban). Timeline comment
    # goes here as well as Owner Data. Null for spreadsheet campaigns.
    crm_lead_id = models.PositiveIntegerField(null=True, blank=True)
    # Renewals deal (category 9) this row was sent from. Later messages on
    # the same WhatsApp chat are mirrored onto this deal's timeline.
    crm_deal_id = models.PositiveIntegerField(null=True, blank=True)
    # "tenant" or "owner" — which side of the deal this number belongs to.
    crm_role = models.CharField(max_length=16, blank=True, default="")
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
