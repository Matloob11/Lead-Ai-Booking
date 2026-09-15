from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AccessRequest, Agent


@admin.register(Agent)
class AgentAdmin(UserAdmin):
    list_display = ["username", "display_name", "community", "bitrix_user_id", "is_wa_admin", "is_bitrix_admin", "is_active", "last_seen_at"]
    list_filter = ["is_wa_admin", "is_bitrix_admin", "is_active", "is_staff"]
    search_fields = ["username", "display_name", "bitrix_user_id", "email"]

    fieldsets = UserAdmin.fieldsets + (
        (
            "WhatsApp panel",
            {
                "fields": (
                    "bitrix_user_id",
                    "bitrix_portal",
                    "display_name",
                    "community",
                    "avatar_url",
                    "is_wa_admin",
                    "is_bitrix_admin",
                    "last_seen_at",
                )
            },
        ),
    )


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display = ["agent", "status", "created_at", "resolved_at", "resolved_by"]
    list_filter = ["status"]
    search_fields = ["agent__display_name", "agent__username", "message"]
    readonly_fields = ["created_at"]
