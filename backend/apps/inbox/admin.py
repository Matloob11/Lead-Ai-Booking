from django.contrib import admin

from .models import AssignmentLog, Contact, Conversation, MediaAsset, Message


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["wa_id", "profile_name", "display_name", "created_at"]
    search_fields = ["wa_id", "profile_name", "display_name"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "number", "contact", "assigned_agent", "status", "unread_count", "session_expires_at", "last_message_at"]
    list_filter = ["status", "number"]
    search_fields = ["contact__wa_id", "contact__profile_name"]
    autocomplete_fields = ["assigned_agent"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "conversation", "direction", "kind", "status", "created_at"]
    list_filter = ["direction", "kind", "status"]
    search_fields = ["wamid", "body"]
    readonly_fields = ["payload"]


@admin.register(AssignmentLog)
class AssignmentLogAdmin(admin.ModelAdmin):
    list_display = ["conversation", "from_agent", "to_agent", "changed_by", "created_at"]


admin.site.register(MediaAsset)
