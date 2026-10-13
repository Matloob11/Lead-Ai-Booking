from django.contrib import admin

from .models import Campaign, CampaignBatch, CampaignRecipient


@admin.register(CampaignBatch)
class CampaignBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "template_name", "crm_target", "per_number_cap", "total", "leftover", "created_at")
    search_fields = ("name", "template_name")
    readonly_fields = ("created_at", "cancelled_at", "column_map", "skipped_numbers", "warnings")


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
