from django.contrib import admin

from .models import NumberAssignment, WabaNumber, WaTemplate


class AssignmentInline(admin.TabularInline):
    model = NumberAssignment
    fk_name = "number"
    extra = 1
    autocomplete_fields = ["agent"]


@admin.register(WabaNumber)
class WabaNumberAdmin(admin.ModelAdmin):
    list_display = ["phone_number", "label", "quality_rating", "verification_status", "is_active", "webhook_configured"]
    list_editable = ["label"]
    list_filter = ["is_active", "quality_rating", "webhook_configured"]
    search_fields = ["phone_number", "phone_number_id", "waba_business_id", "label", "display_name"]
    inlines = [AssignmentInline]


@admin.register(NumberAssignment)
class NumberAssignmentAdmin(admin.ModelAdmin):
    list_display = ["number", "agent", "role", "is_active", "created_at"]
    list_filter = ["is_active", "role"]
    autocomplete_fields = ["number", "agent"]


@admin.register(WaTemplate)
class WaTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "language", "category", "status", "waba_business_id", "synced_at"]
    list_filter = ["status", "category", "language"]
    search_fields = ["name", "waba_business_id"]
