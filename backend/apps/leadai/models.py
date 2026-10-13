"""Lead AI screen: chats that live there and not in the main Official inbox.

A CRM campaign sent with the popup's "Lead AI" box ticked puts every chat it
reaches here. The main inbox list leaves these chats out, and live events for
them travel under a ``leadai.`` prefix, so the Official inbox never shows
them; the agent reads and answers them in the Lead AI screen. The Lead AI
assistant (apps.leadai.assistant) answers them too, with its own OpenAI key;
Sara (apps.leadbot) and the inbox AI desk both skip an active Lead AI chat.
"Move to inbox" hands one back to the main inbox, and only that does.

The assistant keeps its own state in tables that nothing outside this app
joins. LeadAiChat is selected by the main inbox list, so it is left exactly as
it was: adding columns to it would break that list for every agent in the
moment between a deploy and its migration.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

# The visit address the assistant sends (owner's choice, 2026-10-09).
DEFAULT_OFFICE_ADDRESS = "Russia Cluster, Building V02/V03, Shop 20, Dubai International City"


class LeadAiCampaign(models.Model):
    """A campaign whose chats belong to the Lead AI screen (the popup checkbox)."""

    campaign = models.OneToOneField(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="lead_ai"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Lead AI campaign {self.campaign_id}"


class LeadAiChat(models.Model):
    """One conversation in the Lead AI screen.

    One conversation exists per (our number, customer), so a customer who was
    already chatting on that number brings the whole history along; the same
    customer on another number is another conversation and stays put.

    ``active`` false means it is back in the main inbox; only the agent's
    "Move to inbox" does that. ``confirmed`` turns true once a Lead AI
    campaign message to the chat was accepted by the gateway (a failed send
    rolls the whole mark back, so an unconfirmed row is one whose send is
    still in flight).
    """

    conversation = models.OneToOneField(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="lead_ai_chat"
    )
    active = models.BooleanField(default=True, db_index=True)
    confirmed = models.BooleanField(default=False)
    campaign = models.ForeignKey(
        "campaigns.Campaign", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The CRM record the campaign was sent from: lead, deal, owner_data or "".
    crm_entity = models.CharField(max_length=24, blank=True)
    crm_id = models.PositiveIntegerField(null=True, blank=True)
    moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    moved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        state = "Lead AI" if self.active else "inbox"
        return f"Conversation {self.conversation_id} ({state})"


class LeadAiChatState(models.Model):
    """What the assistant knows and has decided about one chat.

    Its own table, joined by nothing outside apps.leadai (see the module note).
    """

    class StopReason(models.TextChoices):
        NONE = "", "Not stopped"
        STOP_ALL = "stop_all", "Customer asked us to stop"
        WRONG_NUMBER = "wrong_number", "Wrong number"
        AUTO_REPLY = "auto_reply", "Customer side is an automatic reply"

    conversation = models.OneToOneField(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="lead_ai_state"
    )
    # Requirement, size, budget, ... as the assistant learned them (English).
    facts = models.JSONField(default=dict, blank=True)
    language = models.CharField(max_length=16, blank=True)
    # The customer asked to stop, or the other side is a bot: silent until resumed.
    stopped_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=24, choices=StopReason.choices, blank=True)
    # An agent pressed "Pause AI" in this chat: silent until they press Resume.
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The customer asked for a person (owner's choice: the assistant goes quiet,
    # handling only bookings and reminder taps, until an agent writes).
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handover_reason = models.CharField(max_length=40, blank=True)
    holding_line_at = models.DateTimeField(null=True, blank=True)
    # Declined this offer: no more invitations, still answered politely.
    not_interested_at = models.DateTimeField(null=True, blank=True)
    invites = models.PositiveSmallIntegerField(default=0)
    unsupported_notice_at = models.DateTimeField(null=True, blank=True)
    # The CRM record's responsible person, looked up once and cached.
    responsible_bitrix_user_id = models.CharField(max_length=16, blank=True)
    responsible_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    responsible_checked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Lead AI state of conversation {self.conversation_id}"

    @classmethod
    def for_conversation(cls, conversation) -> "LeadAiChatState":
        row, _ = cls.objects.get_or_create(conversation=conversation)
        return row

    @property
    def silent_reason(self) -> str:
        if self.stopped_at is not None:
            return self.get_stop_reason_display() or "stopped"
        if self.paused_at is not None:
            return "paused by an agent"
        return ""


class LeadAiSettings(models.Model):
    """One row (pk=1): the assistant's switch, its test numbers and the office.

    Kept in the database, not the environment, so an admin can turn the
    assistant on or off, add test numbers or paste the office's Maps link from
    the Lead AI screen without a deploy. The data migration creates it OFF
    (owner's choice: first only his own test number, then he turns it on).
    """

    assistant_enabled = models.BooleanField(default=False)
    # While the assistant is off it still answers these customer numbers
    # (digits with country code), so the owner can test on his own phone.
    test_numbers = models.JSONField(default=list, blank=True)
    # Public holidays and other days the office is closed (YYYY-MM-DD).
    closed_dates = models.JSONField(default=list, blank=True)
    office_address = models.CharField(max_length=255, default=DEFAULT_OFFICE_ADDRESS)
    office_maps_url = models.URLField(max_length=500, blank=True)
    office_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    office_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # A ceiling on model calls across all chats per day (spend guard).
    daily_call_limit = models.PositiveIntegerField(default=1500)
    # Circuit breaker: after repeated OpenAI failures the assistant pauses itself.
    paused_until = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_sweep_at = models.DateTimeField(null=True, blank=True)
    history = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Lead AI settings"

    def __str__(self):
        return "Lead AI settings"

    @classmethod
    def load(cls) -> "LeadAiSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    @property
    def has_pin(self) -> bool:
        return self.office_latitude is not None and self.office_longitude is not None

    def answers(self, wa_id: str) -> bool:
        """May the assistant talk to this customer number right now?"""
        if self.assistant_enabled:
            return True
        digits = "".join(ch for ch in str(wa_id or "") if ch.isdigit())
        return bool(digits) and digits in {"".join(c for c in str(n) if c.isdigit()) for n in (self.test_numbers or [])}


class LeadAiTurn(models.Model):
    """One run of the assistant on a customer's message (or a reminder tap).

    The row for an inbound message is created before anything else happens,
    and ``inbound`` is unique, so a redelivered or duplicated task finds it
    and stops: one customer message is answered at most once.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        REPLIED = "replied", "Replied"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey("inbox.Conversation", on_delete=models.CASCADE, related_name="+")
    inbound = models.OneToOneField(
        "inbox.Message", null=True, blank=True, on_delete=models.CASCADE, related_name="lead_ai_turn"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=64, blank=True)
    calls = models.PositiveSmallIntegerField(default=0)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    reply_message = models.ForeignKey(
        "inbox.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actions = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Turn {self.pk} on conversation {self.conversation_id} ({self.status})"


class LeadAiAppointment(models.Model):
    """A visit the assistant arranged (the owner's rules 50-59).

    The source of truth for the 30-minute reminder and its buttons: Bitrix
    cannot be, because its Lead Automation process erases the lead's meeting
    time. One open (tentative or confirmed) appointment per chat; a
    reschedule moves it, a cancel closes it, and one whose time is more than
    three hours past is closed as done by the sweep.
    """

    class Status(models.TextChoices):
        TENTATIVE = "tentative", "Tentative"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        DONE = "done", "Past"

    class Place(models.TextChoices):
        OFFICE = "office", "Our office"
        CUSTOMER_PROPERTY = "customer_property", "The customer's property"
        CALL = "call", "A call"

    class CustomerState(models.TextChoices):
        NONE = "", "No answer yet"
        ON_MY_WAY = "on_my_way", "On the way"
        RUNNING_LATE = "running_late", "Running late"
        RESCHEDULE = "reschedule", "Wants to reschedule"

    OPEN = ("tentative", "confirmed")

    conversation = models.ForeignKey(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="lead_ai_appointments"
    )
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    place = models.CharField(max_length=24, choices=Place.choices, default=Place.OFFICE)
    starts_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    customer_words = models.CharField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    mobile = models.CharField(max_length=32, blank=True)
    # Requirement, size, budget, business activity, trade licence, move-in,
    # selected shop, ... as the assistant learned them.
    details = models.JSONField(default=dict, blank=True)
    customer_state = models.CharField(max_length=24, choices=CustomerState.choices, blank=True)
    eta_at = models.DateTimeField(null=True, blank=True)
    reminder_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reminder_claimed_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_message = models.ForeignKey(
        "inbox.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reminder_error = models.TextField(blank=True)
    # Our own heads-up to the agent shortly before the visit.
    agent_reminded_at = models.DateTimeField(null=True, blank=True)
    crm_entity = models.CharField(max_length=24, blank=True)
    crm_id = models.PositiveIntegerField(null=True, blank=True)
    crm_stage_moved_at = models.DateTimeField(null=True, blank=True)
    crm_todo_id = models.PositiveIntegerField(null=True, blank=True)
    crm_synced_at = models.DateTimeField(null=True, blank=True)
    crm_error = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation"],
                condition=Q(status__in=["tentative", "confirmed"]),
                name="leadai_one_open_appointment",
            )
        ]

    def __str__(self):
        return f"Appointment {self.pk} ({self.status}) on conversation {self.conversation_id}"

    def log(self, event: str, **data) -> None:
        """Append one line to the history (saved by the caller)."""
        entry = {"at": timezone.now().isoformat(), "event": event}
        entry.update({k: v for k, v in data.items() if v not in (None, "")})
        self.history = list(self.history or []) + [entry]


class LeadAiCrmStep(models.Model):
    """One Bitrix write that is done, so a retried sync never repeats it.

    Insert-only and unique per (appointment, step): a lead update makes Bitrix
    plan another meeting to-do every time, so repeating one is not harmless.
    """

    appointment = models.ForeignKey(LeadAiAppointment, on_delete=models.CASCADE, related_name="crm_steps")
    step = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["appointment", "step"], name="leadai_crm_step_once")]


class LeadAiAlert(models.Model):
    """A heads-up for an agent: a booking, a hot lead, "on my way", "running
    late", a reschedule, a request for a person, a reminder that failed.

    One row per recipient; ``dedupe_key`` (which includes the recipient) is
    unique, so the same event never alerts the same person twice.
    """

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    kind = models.CharField(max_length=32)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    conversation = models.ForeignKey("inbox.Conversation", on_delete=models.CASCADE, related_name="+")
    appointment = models.ForeignKey(
        LeadAiAppointment, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    bitrix_user_id = models.CharField(max_length=16, blank=True)
    title = models.CharField(max_length=200)
    text = models.TextField()
    crm_url = models.CharField(max_length=200, blank=True)
    dedupe_key = models.CharField(max_length=220, unique=True)
    panel_sent_at = models.DateTimeField(null=True, blank=True)
    bitrix_sent_at = models.DateTimeField(null=True, blank=True)
    bitrix_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Alert {self.kind} on conversation {self.conversation_id}"


class LeadAiTranscript(models.Model):
    """What a customer's voice note says, heard with the Lead AI key.

    Only a successful transcription is final. A failure keeps its error and
    the number of tries, so a later attempt (after a fix, or once the file
    has finally downloaded) can still hear it.
    """

    message = models.OneToOneField(
        "inbox.Message", on_delete=models.CASCADE, related_name="lead_ai_transcript"
    )
    text = models.TextField(blank=True)
    model = models.CharField(max_length=64, blank=True)
    error = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transcript of message {self.message_id}"

    @property
    def heard(self) -> bool:
        return bool(self.text) and not self.error
