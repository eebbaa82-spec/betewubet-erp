from django.contrib import admin

from .models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierItem


class SupplierItemInline(admin.TabularInline):
    model = SupplierItem
    extra = 1
    fields = ["item", "supplier_code", "pack_name", "pack_qty", "price_per_pack", "min_packs", "preferred"]
    autocomplete_fields = ["item"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "tin", "vat_registered", "phone", "city", "lead_time_days", "active"]
    list_filter = ["active", "vat_registered"]
    search_fields = ["name", "tin"]
    inlines = [SupplierItemInline]


class LineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    fields = ["item", "pack_name", "pack_qty", "packs", "price_per_pack", "received_packs"]
    readonly_fields = ["received_packs"]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "supplier", "status", "order_date", "expected_date"]
    list_filter = ["status", "supplier"]
    search_fields = ["number", "supplier__name"]
    inlines = [LineInline]
