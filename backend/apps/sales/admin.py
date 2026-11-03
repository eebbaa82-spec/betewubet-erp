from django.contrib import admin

from .models import Customer, SalesOrder, SalesOrderLine


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "tin", "vat_reg_no", "phone", "city"]
    search_fields = ["name", "tin"]


class LineInline(admin.TabularInline):
    model = SalesOrderLine
    extra = 0
    fields = ["sequence", "template", "configuration", "description", "quantity",
              "estimated_unit_cost", "unit_price", "price_locked"]
    readonly_fields = ["estimated_unit_cost"]


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "order_type", "status", "order_date", "due_date"]
    list_filter = ["status", "order_type"]
    search_fields = ["number", "customer__name"]
    inlines = [LineInline]
