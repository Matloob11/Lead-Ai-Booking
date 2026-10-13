from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Contact(models.Model):
    """A customer, identified by the WhatsApp id Meta returns for them.

    One contact can hold conversations with several of our numbers, so the
    contact is global and the per-number state lives on Conversation.
    """

    wa_id = models.CharField(max_length=32, unique=True, db_index=True)
    profile_name = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True, help_text="Name an agent set manually")

    # Internal only. The customer never sees this; it is where an agent records
    # what the chat itself does not say — budget, which property, when to call.
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_name or self.profile_name or self.wa_id


class Label(models.Model):
    """A tag an agent puts on a chat — Hot lead, Site visit, Follow-up.

    Ours, not WhatsApp's: the API has no concept of labels, so these live here
    and are shared across the team so a transferred chat keeps its meaning.
    """

    name = models.CharField(max_length=64, unique=True)
    colour = models.CharField(max_length=16, default="#25D366")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class QuickReply(models.Model):
    """A saved answer an agent can drop into the composer.

    Agents type the same handful of replies all day. A quick reply with no
    owner is shared with everyone; one with an owner belongs to that agent
    alone.
    """

    shortcut = models.CharField(max_length=32, help_text="Typed after / to insert it")
    body = models.TextField()
    owner = models.ForeignKey(
        "accounts.Agent", on_delete=models.CASCADE, null=True, blank=True, related_name="quick_replies"
    )
    created_by = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shortcut"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "shortcut"], name="unique_shortcut_per_owner")
        ]

    def __str__(self):
        return f"/{self.shortcut}"


class Conversation(models.Model):
    """One thread between one of our numbers and one customer.

    ``assigned_agent`` is who may open the thread. A customer may still reach
    a number directly; ingest then claims the row for that number's primary
    agent. A panel admin can move it without the history going anywhere.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    number = models.ForeignKey("catalog.WabaNumber", on_delete=models.PROTECT, related_name="conversations")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="conversations")

    assigned_agent = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    # Meta's free-form window: it opens on every inbound message and closes 24h
    # after the last one. Stored rather than computed so it can be indexed and
    # queried, and so a template send can extend it explicitly.
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    session_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=255, blank=True)
    # Lets the conversation list mark a photo or document without loading the
    # message itself.
    last_message_kind = models.CharField(max_length=16, blank=True)
    unread_count = models.PositiveIntegerField(default=0)

    # Housekeeping the WhatsApp API knows nothing about. Kept on the
    # conversation rather than per agent: everyone working a number sees the
    # same list, so pinning has to mean the same thing to all of them.
    is_pinned = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    labels = models.ManyToManyField(Label, blank=True, related_name="conversations")

    # The other Official thread this one was copied onto after a transfer.
    # WhatsApp still has two chats; the panel keeps their histories in step.
    linked_conversation = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number", "contact"], name="unique_conversation_per_number")
        ]
        ordering = ["-is_pinned", "-last_message_at", "-created_at"]
        indexes = [models.Index(fields=["number", "-last_message_at"])]

    def __str__(self):
        return f"{self.contact} <-> {self.number.phone_number}"

    @property
    def is_session_open(self):
        return bool(self.session_expires_at and self.session_expires_at > timezone.now())

    def open_session(self, at=None):
        """Start or extend the free-form window from an inbound message."""
        at = at or timezone.now()
        self.last_inbound_at = at
        self.session_expires_at = at + timedelta(hours=settings.SESSION_WINDOW_HOURS)


class MediaAsset(models.Model):
    """A file that travelled in either direction.

    Outbound files are uploaded to alots first and keep the returned
    ``alots_media_id``; inbound ones are downloaded and stored locally so the
    history stays readable after Meta expires the original.
    """

    file = models.FileField(upload_to="wa/%Y/%m/", blank=True)
    alots_media_id = models.CharField(max_length=128, blank=True, db_index=True)

    # The webhook hands us a ready-to-fetch link, which is the only route that
    # actually works: the gateway's media-by-id endpoint answers 400 for every
    # media we own. Their hosted copy needs no auth; Meta's lookaside link is
    # short-lived and does.
    source_url = models.TextField(blank=True)

    # Meta's own link, kept as the second attempt. The gateway's copy is
    # preferred because it needs no credentials and does not expire, but it is
    # not always there — stickers in particular come back 404 — and Meta's
    # still works for the few minutes right after the webhook, which is when
    # the download runs.
    fallback_url = models.TextField(blank=True)

    mime_type = models.CharField(max_length=128, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    downloaded = models.BooleanField(default=False)
    download_error = models.TextField(blank=True)

    # Who uploaded it, so an outbound asset can only be attached by the agent
    # who put it there. Null for inbound media, which nobody uploaded.
    uploaded_by = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="uploads"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_name or self.alots_media_id or f"media #{self.pk}"


class Message(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "in", "Inbound"
        OUTBOUND = "out", "Outbound"

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        TEMPLATE = "template", "Template"
        IMAGE = "image", "Image"
        DOCUMENT = "document", "Document"
        AUDIO = "audio", "Audio"
        VIDEO = "video", "Video"
        STICKER = "sticker", "Sticker"
        LOCATION = "location", "Location"
        CONTACTS = "contacts", "Contacts"
        INTERACTIVE = "interactive", "Interactive"
        BUTTON = "button", "Button reply"
        REACTION = "reaction", "Reaction"
        ALBUM = "album", "Album"
        PINNED = "pinned_message", "Pinned message"
        SYSTEM = "system", "System"
        UNKNOWN = "unknown", "Unknown"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        READ = "read", "Read"
        FAILED = "failed", "Failed"
        RECEIVED = "received", "Received"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=8, choices=Direction.choices)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TEXT)

    # Meta's message id. Unique when present, but outbound messages exist in the
    # DB for a moment before the gateway hands one back.
    wamid = models.CharField(max_length=128, blank=True, null=True, unique=True)

    body = models.TextField(blank=True)
    media = models.ForeignKey(MediaAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    template = models.ForeignKey(
        "catalog.WaTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )

    # Everything Meta sent or we sent, kept for debugging and for rendering
    # message kinds the UI does not model yet.
    payload = models.JSONField(default=dict, blank=True)

    # The message this one quotes, in either direction. Null when the customer
    # replied to something sent before we started recording, or to nothing.
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )

    # Set when this row is a panel-only copy of a message on the linked
    # conversation. It must never be sent through the gateway, and it has no
    # WhatsApp id of its own.
    mirrored_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="panel_copies",
    )

    # Emoji the customer put on this message, keyed by their wa_id. Reactions
    # arrive as their own webhook event naming a target, and belong on the
    # bubble they decorate rather than as a message of their own. Sending one
    # back is not possible — the gateway refuses the type.
    reactions = models.JSONField(default=dict, blank=True)

    # Shared across the team rather than per-agent: several people can work the
    # same number, and a starred message here means "this one matters to whoever
    # picks up the chat", not "I personally bookmarked it".
    is_starred = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=32, blank=True)
    error_detail = models.TextField(blank=True)

    sent_by = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_messages"
    )

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "mirrored_from"],
                condition=models.Q(mirrored_from__isnull=False),
                name="unique_panel_copy_per_peer",
            )
        ]

    def __str__(self):
        return f"{self.direction} {self.kind} #{self.pk}"


class Reminder(models.Model):
    """A nudge to come back to a chat.

    Real estate leads go quiet and come back weeks later, and the 24-hour
    window makes timing matter — an agent who forgets to follow up before it
    closes has to spend a template to say anything at all.
    """

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="reminders")
    agent = models.ForeignKey("accounts.Agent", on_delete=models.CASCADE, related_name="reminders")
    due_at = models.DateTimeField(db_index=True)
    note = models.CharField(max_length=255, blank=True)

    is_done = models.BooleanField(default=False)
    fired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at"]
        indexes = [models.Index(fields=["agent", "is_done", "due_at"])]

    def __str__(self):
        return f"{self.agent} -> {self.conversation} at {self.due_at}"


class AssignmentLog(models.Model):
    """Audit trail for conversation handovers."""

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="assignment_logs")
    from_agent = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_agent = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_by = models.ForeignKey(
        "accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.conversation_id}: {self.from_agent} -> {self.to_agent}"


class SharedAsset(models.Model):
    """A shared media file (brochure, layout, payment plan) uploaded once
    and available for all agents to send to any customer in 1 click."""

    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        DOCUMENT = "document", "Document"
        VIDEO = "video", "Video"

    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DOCUMENT)
    file = models.FileField(upload_to="shared/%Y/%m/")
    file_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=128, blank=True)
    created_by = models.ForeignKey("accounts.Agent", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
