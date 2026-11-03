from django.contrib import admin

from .models import Location, Lot, Offcut, StockMove


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_offcut_rack"]


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ["code", "item", "supplier_batch", "colour_ref", "received_on"]
    list_filter = ["item__kind"]
    search_fields = ["code", "item__code", "supplier_batch", "colour_ref"]


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ["created_at", "kind", "item", "lot", "location", "qty", "unit_cost", "work_order", "reference"]
    list_filter = ["kind", "location", "item__kind"]
    search_fields = ["item__code", "reference", "work_order__number"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Offcut)
class OffcutAdmin(admin.ModelAdmin):
    list_display = ["code", "item", "length_mm", "width_mm", "lot", "location", "status", "reserved_for"]
    list_filter = ["status", "item"]
    search_fields = ["code", "item__code"]
