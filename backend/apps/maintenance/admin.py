from django.contrib import admin

from .models import Machine, MaintenanceLog, MaintenancePlan


class PlanInline(admin.TabularInline):
    model = MaintenancePlan
    extra = 1
    fields = ["task", "every_hours", "every_days", "last_done_at", "last_done_hours", "active"]


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "work_center", "make_model", "serial_no", "active"]
    list_filter = ["active", "work_center"]
    search_fields = ["code", "name", "serial_no"]
    inlines = [PlanInline]


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ["machine", "kind", "description", "machine_down", "reported_at", "closed_at", "parts_cost"]
    list_filter = ["kind", "machine_down", "machine"]
    search_fields = ["description", "action_taken", "done_by"]
