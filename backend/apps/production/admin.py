from django.contrib import admin

from .models import TimeLog, WorkOrder, WorkOrderMaterial, WorkOrderOperation


class MaterialInline(admin.TabularInline):
    model = WorkOrderMaterial
    extra = 0


class OperationInline(admin.TabularInline):
    model = WorkOrderOperation
    extra = 0


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "template", "quantity", "status", "due_date", "sales_line"]
    list_filter = ["status"]
    search_fields = ["number"]
    readonly_fields = ["exploded", "estimate"]
    inlines = [MaterialInline, OperationInline]


@admin.register(TimeLog)
class TimeLogAdmin(admin.ModelAdmin):
    list_display = ["operation", "operator", "started_at", "ended_at", "good_qty", "rejected_qty"]
