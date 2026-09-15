from django.contrib import admin

from .models import FeedbackAttachment, FeedbackReport


class FeedbackAttachmentInline(admin.TabularInline):
    model = FeedbackAttachment
    extra = 0
    readonly_fields = ("kind", "file_name", "mime_type", "size_bytes", "created_at")


@admin.register(FeedbackReport)
class FeedbackReportAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "status", "created_at", "solved_at", "solved_by")
    list_filter = ("status",)
    search_fields = ("body", "agent__display_name", "agent__username")
    readonly_fields = ("created_at", "solved_at")
    inlines = [FeedbackAttachmentInline]
