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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_name or self.profile_name or self.wa_id


class Conversation(models.Model):
    """One thread between one of our numbers and one customer.

    Every agent assigned to the number can see the thread — a customer may
    reach out to a number directly, so nothing is hidden behind ownership.
    ``assigned_agent`` records who owns the reply, and an admin can move it to
    somebody else without the history going anywhere.
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
    unread_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number", "contact"], name="unique_conversation_per_number")
        ]
        ordering = ["-last_message_at", "-created_at"]
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
    mime_type = models.CharField(max_length=128, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    downloaded = models.BooleanField(default=False)
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

    def __str__(self):
        return f"{self.direction} {self.kind} #{self.pk}"


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
