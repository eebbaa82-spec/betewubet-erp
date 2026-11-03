from django.contrib import admin

from .models import UOM, CostSettings, WorkCenter


@admin.register(UOM)
class UOMAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "ratio_to_base"]
    list_filter = ["category"]


@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "machine_rate", "labour_rate", "hours_per_day"]


admin.site.register(CostSettings)
