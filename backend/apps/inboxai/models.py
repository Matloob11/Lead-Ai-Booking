"""Agent-written AI cover for Official API chats.

Lives in its own app so Conversation / Message stay untouched — those models
are mid-edit in other sessions.
"""

from django.conf import settings
from django.db import models


class AgentAiDesk(models.Model):
    """One agent's global cover: which of their chats the AI may answer."""

    class Scope(models.TextChoices):
        OFF = "off", "Off"
        NEW = "new", "New chats"
        ALL = "all", "All my chats"
        SELECTED = "selected", "Selected chats"

    agent = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_desk"
    )
    enabled = models.BooleanField(default=False)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.OFF)
    context = models.TextField(blank=True)
    selected = models.ManyToManyField(
        "inbox.Conversation", blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI desk"
        verbose_name_plural = "AI desks"

    def __str__(self):
        return f"{self.agent} desk ({self.scope})"


class ConversationAiCover(models.Model):
    """Explicit per-chat cover. Beats the owner's desk when enabled."""

    conversation = models.OneToOneField(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="ai_cover"
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_covers"
    )
    enabled = models.BooleanField(default=False)
    context = models.TextField(blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "conversation AI cover"
        verbose_name_plural = "conversation AI covers"

    def __str__(self):
        state = "on" if self.enabled and not self.paused_at else "off"
        return f"cover {self.conversation_id} {state}"


class ConversationHealth(models.Model):
    """AI colour on one Official chat. Same bins as OpenWA Conversation Health."""

    class Colour(models.TextChoices):
        RED = "red", "Red"
        PINK = "pink", "Pink"
        YELLOW = "yellow", "Amber"
        WHITE = "white", "Hot"
        GREEN = "green", "Green"

    conversation = models.OneToOneField(
        "inbox.Conversation", on_delete=models.CASCADE, related_name="ai_health"
    )
    colour = models.CharField(max_length=16, blank=True, default="")
    colour_locked = models.BooleanField(default=False)
    reason = models.TextField(blank=True)
    flags = models.JSONField(default=list, blank=True)
    confidence = models.FloatField(default=0)
    needs_human_review = models.BooleanField(default=False)
    message_count_since_classify = models.PositiveIntegerField(default=0)
    last_classified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "conversation health"
        verbose_name_plural = "conversation health"
        indexes = [models.Index(fields=["colour"], name="inboxai_health_colour")]

    def __str__(self):
        return f"health {self.conversation_id} {self.colour or 'none'}"
