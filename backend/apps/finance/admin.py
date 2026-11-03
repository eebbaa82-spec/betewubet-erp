from django.contrib import admin

from .models import FinanceSettings, Invoice, InvoiceLine, Payment, SupplierBill, SupplierPayment


@admin.register(FinanceSettings)
class FinanceSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not FinanceSettings.objects.exists()


class LineInline(admin.TabularInline):
    model = InvoiceLine
    fk_name = "invoice"
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "status", "customer", "issue_date", "due_date"]
    list_filter = ["status", "kind"]
    inlines = [LineInline]
    readonly_fields = ["number", "status"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["number", "invoice", "date", "amount", "withholding", "method"]


@admin.register(SupplierBill)
class SupplierBillAdmin(admin.ModelAdmin):
    list_display = ["number", "supplier", "supplier_invoice_no", "bill_date", "subtotal", "vat", "withholding"]


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ["number", "bill", "date", "amount", "method"]
