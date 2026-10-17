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

# The visit address the assistant sends: our own office, Building V03 only (Matloob, 2026-10-15; it
# read "V02/V03" before, and the live settings row was changed to this the same day). "Shop 20" is the
# office's own unit number, never a shop for rent (prompt.SHOPS_SYSTEM says so).
DEFAULT_OFFICE_ADDRESS = "Russia Cluster, Building V03, Shop 20, Dubai International City"
# The brand the shops campaigns run under (owner's choice 2026-10-13).
DEFAULT_BRAND_NAME = "AR Properties"

# What the shops playbook may quote (the build pack of 2026-10-12, section 2).
# The owner edits the final figures in the Lead AI settings; assistant/shops.py
# reads them and falls back to these, key by key, for anything missing or broken.
# Rents are per year in AED; "cheapest" is the "from" price quoted to customers.
DEFAULT_SHOPS_FACTS = {
    "types": [
        {"label": "Small", "size_from": 400, "size_to": 550, "rent_from": 33000, "rent_to": 45000, "cheapest": 33000},
        {"label": "Medium", "size_from": 600, "size_to": 800, "rent_from": 48000, "rent_to": 65000, "cheapest": 48000},
        {"label": "Large", "size_from": 900, "size_to": 1200, "rent_from": 80000, "rent_to": 200000, "cheapest": 80000},
    ],
    "clusters": ["France", "England", "China", "Russia", "Morocco", "Persia"],
    "cheques": "1 to 4 cheques",
    "licences": "DED (mainland) or Trakhees licence; opening a new licence is also fine",
    "viewing": (
        "The client comes to our office; our agent drives them to the shops (5 minutes away) and back. "
        "30-minute slots, one client per slot, 10:00 to the last slot at 19:30, Monday to Saturday, Sunday closed."
    ),
}


def default_shops_facts() -> dict:
    """A fresh copy, so no row ever shares (and changes) the module's own lists."""
    import copy

    return copy.deepcopy(DEFAULT_SHOPS_FACTS)


class LeadAiCampaign(models.Model):
    """A campaign whose chats belong to the Lead AI screen (the popup checkbox)."""

    class Playbook(models.TextChoices):
        GENERAL = "general", "General"
        IC_SHOPS = "ic_shops", "International City shops"

    campaign = models.OneToOneField(
        "campaigns.Campaign", on_delete=models.CASCADE, related_name="lead_ai"
    )
    # The script the assistant follows in this campaign's chats, chosen in the
    # Bitrix popup (owner's choice 2026-10-13: shop campaigns get their own).
    # A database default as well: the popup's send inserts these rows, and the
    # old code still running in the minutes after the migration knows nothing
    # of this column.
    playbook = models.CharField(
        max_length=24, choices=Playbook.choices, default=Playbook.GENERAL, db_default=Playbook.GENERAL
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
        # Shops chats only: a forwarded chain message, a scam or another business's advert.
        SPAM = "spam", "Spam"

    conversation = models.OneToOneField(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="lead_ai_state"
    )
    # Requirement, size, budget, ... as the assistant learned them (English).
    facts = models.JSONField(default=dict, blank=True)
    language = models.CharField(max_length=16, blank=True)
    # The customer asked to stop, or the other side is a bot: silent until resumed.
    stopped_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=24, choices=StopReason.choices, blank=True)
    # An agent pressed "Pause AI" in this chat (or, with no paused_by, the
    # assistant met a broker there): silent until someone presses Resume.
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
    # Shops chats: after a "Not now" the assistant asked "Should I check back with
    # you in a month?" and that question is still the last thing it said; a yes
    # sets followup_due_at (the follow-up template goes out then), a no closes the
    # lead. Both nullable: rows the old code inserts during a deploy leave them empty.
    followup_asked_at = models.DateTimeField(null=True, blank=True)
    followup_due_at = models.DateTimeField(null=True, blank=True)
    unsupported_notice_at = models.DateTimeField(null=True, blank=True)
    # Shops chats: the build pack's "Please share a copy of your trade license here"
    # went out (once per chat, never again: assistant/shop_flow.py), and the ask was
    # closed, by the copy arriving or by a no. While it is open, a photo or a PDF the
    # customer sends is the licence (tasks.write_licence_file), not a handover.
    # Nullable: rows the old code inserts during a deploy leave them empty.
    licence_asked_at = models.DateTimeField(null=True, blank=True)
    licence_closed_at = models.DateTimeField(null=True, blank=True)
    # Shops chats, the automatic follow-ups (followups.py; board T63, T25, T29). Template B
    # (intl_city_shops_followup) went out once, 72 hours after a shops campaign send the customer
    # never answered (last at template_b_sent_at; a later send of the campaign has its own); and
    # once on the day they asked us to check back (followup_due_at is
    # cleared then). ``nudges``: how many nudges went to a customer who fell silent after our
    # question (two at most, ever), the last at ``nudged_at``. A database default for the
    # count: rows the old code inserts during a deploy name none.
    template_b_sent_at = models.DateTimeField(null=True, blank=True)
    followup_sent_at = models.DateTimeField(null=True, blank=True)
    nudges = models.PositiveSmallIntegerField(default=0, db_default=0)
    nudged_at = models.DateTimeField(null=True, blank=True)
    # Shops chats, the old lead (board T28): the Bitrix lead's creation date and its comments,
    # read once (``lead_info_at``) for the model's context as data (assistant/lead_history.py);
    # ``lead_info_tries`` counts failed reads, three at most. Database defaults, as above.
    lead_asked_on = models.DateField(null=True, blank=True)
    lead_notes = models.CharField(max_length=400, blank=True, default="", db_default="")
    lead_info_at = models.DateTimeField(null=True, blank=True)
    lead_info_tries = models.PositiveSmallIntegerField(default=0, db_default=0)
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
            return "paused by an agent" if self.paused_by_id else "paused until an agent presses Resume"
        return ""


class LeadAiSettings(models.Model):
    """One row (pk=1): the assistant's switch, its test numbers, the office and
    who else hears of its alerts.

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
    # Bitrix users (digit strings) who hear of every booking, handover and
    # unanswered message besides the chat's owner and the CRM responsible
    # (owner's choice 2026-10-13: Matloob).
    alert_bitrix_user_ids = models.JSONField(default=list, blank=True)
    # The shops playbook (International City shops campaigns): the facts it may
    # quote (DEFAULT_SHOPS_FACTS shows the shape), the brand it speaks for and the
    # agent a booked client meets ("" is "our agent").
    shops_facts = models.JSONField(default=default_shops_facts, blank=True)
    brand_name = models.CharField(max_length=80, default=DEFAULT_BRAND_NAME, db_default=DEFAULT_BRAND_NAME)
    viewing_agent_name = models.CharField(max_length=60, blank=True, default="", db_default="")
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

    def alert_user_ids(self) -> list[str]:
        """alert_bitrix_user_ids as digit strings. Only the panel checks what it saves,
        so anything else here (a bare number or a string typed in the Django admin)
        is nobody, never a crash in the middle of a booking."""
        value = self.alert_bitrix_user_ids
        if not isinstance(value, list):
            return []
        return [text for text in (str(item).strip() for item in value if item is not None) if text.isdigit()]

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


class LeadAiCrmField(models.Model):
    """One value the shops playbook writes to the chat's Bitrix lead through the
    Lead fields tool (assistant/crm_fields.py), or the lead's lost move.

    Insert-only. A value is queued only when it is not what the chat last queued
    for that lead and field (crm_fields.queue, under the chat's lock), so the
    same value is never posted twice in a row, and one that comes back (Lost,
    then a booking, then Lost again) is posted again. ``field`` is a Bitrix UF
    code, or "lost" for the move to a lost stage (``value`` is then the stage,
    ``payload`` holds the reason). ``sent_at`` is set once the tool took it;
    ``error`` keeps why it did not; ``retry_at`` is when the sweep sends it again
    after Bitrix was down (tasks._retry_crm_fields).
    """

    conversation = models.ForeignKey("inbox.Conversation", on_delete=models.CASCADE, related_name="+")
    lead_id = models.PositiveIntegerField()
    field = models.CharField(max_length=64)
    value = models.CharField(max_length=255)
    # What goes to the tool besides the value: {"only_if_empty": true}, {"reason": "..."}.
    payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.field}={self.value} on lead {self.lead_id}"


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


class LeadAiShopMedia(models.Model):
    """One file of the shops playbook's media library (board T30): a shop type's
    video or photo, or the office photo.

    The bot sends a type's files when a customer picks the type (shop_media.py):
    the video first, then the photos in ``order`` (file-name order by default),
    then the detail card. ``file`` is stored under MEDIA_ROOT; ``file_name`` is
    the name it was uploaded with, for people (never rendered as HTML). The same
    content twice in one type is one row (``sha256``). ``asset`` is the inbox
    attachment the sent messages link to, so the thread shows what went out.
    """

    class Shop(models.TextChoices):
        TYPE_1 = "type_1", "Type 1"
        TYPE_2 = "type_2", "Type 2"
        TYPE_3 = "type_3", "Type 3"
        OFFICE = "office", "Office"

    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        PHOTO = "photo", "Photo"

    shop = models.CharField(max_length=16, choices=Shop.choices, db_index=True)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    file = models.FileField(upload_to="leadai/shops/%Y/%m/", max_length=255)
    file_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    order = models.PositiveSmallIntegerField(default=0)
    asset = models.ForeignKey("inbox.MediaAsset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shop", "order", "pk"]
        constraints = [models.UniqueConstraint(fields=["shop", "sha256"], name="leadai_shop_media_once")]

    def __str__(self):
        return f"{self.get_shop_display()} {self.kind}: {self.file_name}"


class LeadAiShopMediaUpload(models.Model):
    """The gateway's media id for one library file on one of our numbers.

    A media id belongs to the number that uploaded it, and WhatsApp forgets it
    after about 30 days: shop_media.gateway_media_id uploads again when this one
    is older than 25 days, or when a send says the id is no good.
    """

    media = models.ForeignKey(LeadAiShopMedia, on_delete=models.CASCADE, related_name="uploads")
    number = models.ForeignKey("catalog.WabaNumber", on_delete=models.CASCADE, related_name="+")
    gateway_id = models.CharField(max_length=128)
    uploaded_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["media", "number"], name="leadai_shop_media_upload_once")]

    def __str__(self):
        return f"{self.gateway_id} (library file {self.media_id}, number {self.number_id})"


class LeadAiOptOut(models.Model):
    """One phone that asked us to stop: no campaign on any number messages it (board T60, Q8).

    ``phone`` is digits only, country code first (optout.canonical). Every
    campaign path asks optout.phones_blocked through the campaigns' own hook
    (crm_leads.phones_blocked_by_registry). A person may delete a row in the
    Django admin to undo a mistake; that writes nothing to Bitrix.
    """

    class Source(models.TextChoices):
        LEADAI_STOP = "leadai_stop", "Lead AI: asked us to stop"
        LEADAI_SPAM = "leadai_spam", "Lead AI: spam"
        WRONG_NUMBER = "wrong_number", "Wrong number"
        INBOX_TAP = "inbox_tap", "Inbox: Unsubscribe or Stop"
        BITRIX = "bitrix", "Bitrix: set by a person"
        IMPORT = "import", "Imported from past messages"

    phone = models.CharField(max_length=20, unique=True)
    reason = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices)
    conversation = models.ForeignKey("inbox.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lead AI opt-out"

    def __str__(self):
        return f"+{self.phone} ({self.get_source_display()})"


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
