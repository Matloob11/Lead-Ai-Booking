from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Agent


@admin.register(Agent)
class AgentAdmin(UserAdmin):
    list_display = ["username", "display_name", "bitrix_user_id", "is_wa_admin", "is_active", "last_seen_at"]
    list_filter = ["is_wa_admin", "is_active", "is_staff"]
    search_fields = ["username", "display_name", "bitrix_user_id", "email"]

    fieldsets = UserAdmin.fieldsets + (
        (
            "WhatsApp panel",
            {"fields": ("bitrix_user_id", "bitrix_portal", "display_name", "avatar_url", "is_wa_admin", "last_seen_at")},
        ),
    )
