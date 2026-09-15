from django.contrib import admin

from .models import AgentAiDesk, ConversationAiCover, ConversationHealth


@admin.register(AgentAiDesk)
class AgentAiDeskAdmin(admin.ModelAdmin):
    list_display = ("agent", "enabled", "scope", "updated_at")
    list_filter = ("enabled", "scope")
    search_fields = ("agent__display_name", "agent__username")
    filter_horizontal = ("selected",)
    readonly_fields = ("updated_at",)


@admin.register(ConversationHealth)
class ConversationHealthAdmin(admin.ModelAdmin):
    list_display = ("conversation", "colour", "colour_locked", "last_classified_at", "updated_at")
    list_filter = ("colour", "colour_locked")
    search_fields = ("conversation__contact__wa_id", "reason")
    readonly_fields = ("updated_at", "last_classified_at")
