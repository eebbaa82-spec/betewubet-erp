from django.contrib import admin

from .models import Delivery, DeliveryLine, Installation


class LineInline(admin.TabularInline):
    model = DeliveryLine
    extra = 0


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ["number", "order", "status", "scheduled_date", "vehicle", "driver", "received_by"]
    list_filter = ["status", "install_required"]
    search_fields = ["number", "order__number", "order__customer__name"]
    inlines = [LineInline]


@admin.register(Installation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ["number", "delivery", "status", "scheduled_date", "crew", "signed_off_by"]
    list_filter = ["status"]
