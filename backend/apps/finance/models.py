"""Customer invoices and receipts, supplier bills and payments.

Amounts are ETB. Invoice lines are ex VAT; VAT is worked out on the invoice total at the
rate in force when it is issued. Withholding tax is what a customer keeps back from a payment
(and hands over a withholding receipt for), or what we keep back from a supplier."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Max

from apps.dispatch.models import Delivery
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.sales.models import Customer, SalesOrder, SalesOrderLine

Q2 = Decimal("0.01")


class FinanceSettings(models.Model):
    """Tax rules and invoice header. Your accountant should confirm these. Use FinanceSettings.current()."""

    company_name = models.CharField(max_length=160, default="Betewubet Home and Office Furniture Manufacturing PLC")
    company_tin = models.CharField("company TIN", max_length=20, blank=True)
    company_vat_no = models.CharField("company VAT registration no.", max_length=30, blank=True)
    company_address = models.TextField(blank=True, default="Addis Ababa, Ethiopia")
    company_phone = models.CharField(max_length=40, blank=True)
    bank_details = models.TextField(blank=True, help_text="Printed on invoices, e.g. bank, branch and account number.")
    withholding_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.03"),
        help_text="Withholding tax on payments for goods. Check the current rate with your accountant.")
    withholding_threshold = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("20000"),
        help_text="Withholding applies when one invoice or bill is at least this amount, ex VAT.")
    we_withhold = models.BooleanField(
        default=True, help_text="We are a withholding agent and keep back withholding tax from supplier payments.")
    payment_terms_days = models.PositiveIntegerField(default=30)
    advance_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.50"),
                                      help_text="Usual deposit asked for on a confirmed order.")

    class Meta:
        verbose_name_plural = "finance settings"

    def __str__(self):
        return "Finance settings"

    @classmethod
    def current(cls):
        return cls.objects.first() or cls()


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    BANK = "bank", "Bank transfer"
    CHEQUE = "cheque", "Cheque"
    MOBILE = "mobile", "Mobile money (telebirr, CBE Birr)"


def _next(model, prefix, field="number"):
    last = model.objects.filter(**{f"{field}__startswith": prefix}).aggregate(m=Max(field))["m"]
    n = int(last.split("-")[1]) + 1 if last else 1
    return f"{prefix}{n:05d}"


class Invoice(models.Model):
    class Kind(models.TextChoices):
        STANDARD = "standard", "Invoice"
        ADVANCE = "advance", "Advance invoice"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"

    number = models.CharField(max_length=20, unique=True, null=True, blank=True,
                              help_text="Given when the invoice is issued, so numbers have no gaps.")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.STANDARD)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices")
    delivery = models.OneToOneField(Delivery, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice")
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    fiscal_receipt_no = models.CharField("FS no.", max_length=40, blank=True,
                                         help_text="Receipt number from the sales register machine, if one is used.")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.15"))
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-id"]

    def __str__(self):
        return self.number or f"Draft invoice {self.pk}"

    @property
    def subtotal(self):
        return sum((l.amount for l in self.lines.all()), Decimal(0)).quantize(Q2)

    @property
    def vat(self):
        return (self.subtotal * self.vat_rate).quantize(Q2)

    @property
    def total(self):
        return self.subtotal + self.vat

    @property
    def paid(self):
        return sum((p.amount + p.withholding for p in self.payments.all()), Decimal(0))

    @property
    def balance(self):
        return self.total - self.paid


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=10)
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(1))
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, help_text="ETB, ex VAT. Negative for deductions.")
    sales_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    advance = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="deductions",
                                help_text="The advance invoice this line deducts.")

    class Meta:
        ordering = ["sequence", "id"]

    @property
    def amount(self):
        return (self.quantity * self.unit_price).quantize(Q2)


class Payment(models.Model):
    """Money received against an invoice. Withholding is the part the customer kept back for tax."""

    number = models.CharField(max_length=20, unique=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Money actually received.")
    withholding = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal(0))
    withholding_receipt_no = models.CharField(max_length=40, blank=True)
    method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.BANK)
    reference = models.CharField(max_length=80, blank=True, help_text="Bank reference or cheque number.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _next(Payment, "RV-")
        super().save(*args, **kwargs)


class SupplierBill(models.Model):
    """A supplier's invoice, usually for goods received on a purchase order."""

    number = models.CharField(max_length=20, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="bills")
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="bills")
    supplier_invoice_no = models.CharField(max_length=40)
    bill_date = models.DateField()
    due_date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    vat = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal(0))
    withholding = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal(0),
                                      help_text="Withholding tax we keep back and pay to the tax office.")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-bill_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["supplier", "supplier_invoice_no"], name="one_bill_per_supplier_invoice")]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _next(SupplierBill, "BILL-")
        super().save(*args, **kwargs)

    @property
    def total(self):
        return self.subtotal + self.vat

    @property
    def payable(self):
        """What we pay the supplier: the total less what we withhold."""
        return self.total - self.withholding

    @property
    def paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal(0))

    @property
    def balance(self):
        return self.payable - self.paid


class SupplierPayment(models.Model):
    number = models.CharField(max_length=20, unique=True, blank=True)
    bill = models.ForeignKey(SupplierBill, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.BANK)
    reference = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = _next(SupplierPayment, "PV-")
        super().save(*args, **kwargs)
