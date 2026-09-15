from django.contrib import admin

from .models import Campaign, CampaignRecipient


class RecipientInline(admin.TabularInline):
    model = CampaignRecipient
    extra = 0
    readonly_fields = (
        "phone",
        "name",
        "status",
        "owner_data_id",
        "owner_data_created",
        "conversation",
        "error_detail",
        "sent_at",
    )


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "number", "template", "total", "sent", "failed", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)
    inlines = [RecipientInline]
    readonly_fields = ("created_at", "started_at", "finished_at", "sent", "failed", "skipped")
