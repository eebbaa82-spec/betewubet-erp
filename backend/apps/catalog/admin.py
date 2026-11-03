from django.contrib import admin

from .models import BOMLine, Item, ItemUOMConversion, ProductTemplate, RoutingStep, TemplateParameter


class ConversionInline(admin.TabularInline):
    model = ItemUOMConversion
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "kind", "base_uom", "standard_cost", "track_lots", "active"]
    list_filter = ["kind", "active", "track_lots"]
    search_fields = ["code", "name"]
    inlines = [ConversionInline]


class ParameterInline(admin.TabularInline):
    model = TemplateParameter
    extra = 0


class BOMLineInline(admin.StackedInline):
    model = BOMLine
    fk_name = "template"
    extra = 0
    autocomplete_fields = ["item", "edge_item", "child_template"]
    fieldsets = [
        (None, {"fields": [("sequence", "component", "name", "line_type"), "condition", "qty_formula"]}),
        ("Material", {"fields": [("item", "item_param"), ("child_template", "child_params")]}),
        ("Panel size and edgebanding", {"fields": [("length_formula", "width_formula"),
                                                   ("edge_formula", "edge_item", "edge_item_param"),
                                                   "grain_locked"]}),
    ]


class RoutingInline(admin.TabularInline):
    model = RoutingStep
    extra = 0


@admin.register(ProductTemplate)
class ProductTemplateAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_sellable", "active"]
    search_fields = ["code", "name"]
    inlines = [ParameterInline, BOMLineInline, RoutingInline]
