from django.contrib import admin

from .models import Checklist, ChecklistItem, Inspection, InspectionResult


class ItemInline(admin.TabularInline):
    model = ChecklistItem
    extra = 1
    fields = ["sequence", "text", "kind", "target", "tolerance"]


@admin.register(Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ["name", "stage", "work_center", "active"]
    list_filter = ["stage", "active"]
    inlines = [ItemInline]


class ResultInline(admin.TabularInline):
    model = InspectionResult
    extra = 0
    readonly_fields = ["item", "passed", "value", "note"]


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ["number", "work_order", "checklist", "result", "failed_qty", "inspector", "created_at"]
    list_filter = ["result", "checklist"]
    inlines = [ResultInline]
