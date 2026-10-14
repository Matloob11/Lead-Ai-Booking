from django.contrib import admin

from .models import (
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiCampaign,
    LeadAiChat,
    LeadAiChatState,
    LeadAiCrmField,
    LeadAiSettings,
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
    list_display = ("conversation", "stopped_at", "stop_reason", "paused_at", "handed_over_at", "language", "updated_at")
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


@admin.register(LeadAiAlert)
class LeadAiAlertAdmin(admin.ModelAdmin):
    list_display = ("kind", "priority", "conversation", "agent", "bitrix_user_id", "panel_sent_at", "bitrix_sent_at", "created_at")
    list_filter = ("kind", "priority")
    raw_id_fields = ("conversation", "appointment", "agent")
