from django.contrib import admin

from .models import ApiCall, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "phone_number_id", "attempts", "received_at", "processed_at"]
    list_filter = ["status"]
    search_fields = ["phone_number_id", "dedupe_key"]
    readonly_fields = ["payload", "received_at", "processed_at"]


@admin.register(ApiCall)
class ApiCallAdmin(admin.ModelAdmin):
    list_display = ["method", "path", "status_code", "duration_ms", "created_at"]
    list_filter = ["method", "status_code"]
    readonly_fields = ["request_body", "response_body"]
