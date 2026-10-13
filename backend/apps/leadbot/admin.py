from django.contrib import admin

from .models import LeadAutomation


@admin.register(LeadAutomation)
class LeadAutomationAdmin(admin.ModelAdmin):
    list_display = ("bitrix_lead_id", "state", "customer_phone", "updated_at")
    list_filter = ("state",)
    search_fields = ("bitrix_lead_id", "customer_phone", "last_error")
    raw_id_fields = ("conversation", "number", "agent")
