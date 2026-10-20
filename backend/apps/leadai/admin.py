from django.contrib import admin

from .models import (
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiCampaign,
    LeadAiChat,
    LeadAiChatState,
    LeadAiCrmField,
    LeadAiOptOut,
    LeadAiSettings,
    LeadAiShopMedia,
    LeadAiTurn,
)


@admin.register(LeadAiChat)
class LeadAiChatAdmin(admin.ModelAdmin):
    list_display = ("conversation", "active", "confirmed", "campaign", "added_by", "moved_by", "updated_at")
    list_filter = ("active", "confirmed")
    raw_id_fields = ("conversation", "campaign", "added_by", "moved_by")


@admin.register(LeadAiCampaign)
class LeadAiCampaignAdmin(admin.ModelAdmin):
    list_display = ("campaign", "created_at")
    raw_id_fields = ("campaign",)


@admin.register(LeadAiSettings)
class LeadAiSettingsAdmin(admin.ModelAdmin):
    """The emergency switch also lives here, besides the Lead AI screen. The alert
    recipients are set in the screen's AI settings, which check them."""

    list_display = ("assistant_enabled", "office_address", "daily_call_limit", "paused_until", "last_sweep_at", "updated_at")
    readonly_fields = (
        "paused_until", "consecutive_failures", "last_sweep_at", "history", "updated_at", "alert_bitrix_user_ids",
    )


@admin.register(LeadAiChatState)
class LeadAiChatStateAdmin(admin.ModelAdmin):
    list_display = (
        "conversation", "stopped_at", "stop_reason", "paused_at", "handed_over_at", "language",
        # The shops chats' automatic follow-ups (followups.py).
        "followup_due_at", "template_b_sent_at", "nudges", "community", "updated_at",
    )
    raw_id_fields = ("conversation", "paused_by", "responsible_agent")


@admin.register(LeadAiAppointment)
class LeadAiAppointmentAdmin(admin.ModelAdmin):
    list_display = ("conversation", "status", "place", "starts_at", "customer_state", "reminder_sent_at", "crm_synced_at")
    list_filter = ("status", "place")
    raw_id_fields = ("conversation", "reminder_message", "cancelled_by")


@admin.register(LeadAiTurn)
class LeadAiTurnAdmin(admin.ModelAdmin):
    list_display = ("conversation", "status", "reason", "calls", "prompt_tokens", "completion_tokens", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("conversation", "inbound", "reply_message")


@admin.register(LeadAiCrmField)
class LeadAiCrmFieldAdmin(admin.ModelAdmin):
    """What the shops playbook wrote to each Bitrix lead through the Lead fields tool (read only)."""

    list_display = ("conversation", "lead_id", "field", "value", "sent_at", "attempts", "retry_at", "error", "created_at")
    list_filter = ("field",)
    raw_id_fields = ("conversation",)
    readonly_fields = (
        "conversation", "lead_id", "field", "value", "payload", "sent_at", "error", "attempts", "retry_at", "created_at",
    )


@admin.register(LeadAiOptOut)
class LeadAiOptOutAdmin(admin.ModelAdmin):
    """The phones no campaign may message (optout.py). Deleting a row undoes a mistake:
    the phone can be messaged again, and nothing is written to Bitrix (a lead's own
    WhatsApp Opt-out field is changed there, by hand)."""

    list_display = ("phone", "source", "reason", "conversation", "created_at")
    list_filter = ("source",)
    search_fields = ("phone", "reason")
    raw_id_fields = ("conversation",)
    readonly_fields = ("phone", "source", "reason", "conversation", "created_at")

    def has_add_permission(self, request):
        return False  # rows come from the customers' own words, Bitrix or the import

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LeadAiShopMedia)
class LeadAiShopMediaAdmin(admin.ModelAdmin):
    """The shops media library; files are added, replaced and deleted in the Lead AI screen, which
    checks them and their limits (only their order may be changed here)."""

    list_display = ("shop", "kind", "order", "file_name", "size_bytes", "uploaded_by", "updated_at")
    list_filter = ("shop", "kind")
    raw_id_fields = ("asset", "uploaded_by")
    readonly_fields = (
        "shop", "kind", "file", "file_name", "mime_type", "size_bytes", "sha256", "asset", "uploaded_by", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # the screen's delete also removes the stored file (shop_media.delete)


@admin.register(LeadAiAlert)
class LeadAiAlertAdmin(admin.ModelAdmin):
    list_display = ("kind", "priority", "conversation", "agent", "bitrix_user_id", "panel_sent_at", "bitrix_sent_at", "created_at")
    list_filter = ("kind", "priority")
    raw_id_fields = ("conversation", "appointment", "agent")


from .models import LeadAiCommunity, LeadAiDigest  # noqa: E402 - the day-2 models (assistant/digest.py, assistant/communities.py)


@admin.register(LeadAiDigest)
class LeadAiDigestAdmin(admin.ModelAdmin):
    list_display = ("day", "created_at", "sent_to", "errors")
    readonly_fields = ("day", "stats", "text", "sent_to", "errors", "created_at")
    ordering = ("-day",)


@admin.register(LeadAiCommunity)
class LeadAiCommunityAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "shops", "meeting", "updated_at")
    list_filter = ("active", "shops", "meeting")
    search_fields = ("name", "aliases")
    fieldsets = (
        (None, {"fields": ("name", "active", "aliases", "sub_areas", "units")}),
        ("What the assistant may quote", {"fields": ("bands", "facts_text")}),
        ("Meeting point and playbook", {"fields": ("meeting", "meeting_address", "maps_url", "shops", "call_first_sale", "languages", "pf_location_ids")}),
    )
