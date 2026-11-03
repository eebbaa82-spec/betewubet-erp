from decimal import Decimal

from django.db import models

from apps.catalog.models import ProductTemplate
from apps.core.models import TimeStamped

Q = Decimal("0.01")


class Customer(TimeStamped):
    name = models.CharField(max_length=160)
    tin = models.CharField("TIN", max_length=20, blank=True, help_text="Taxpayer identification number.")
    vat_reg_no = models.CharField("VAT registration no.", max_length=30, blank=True)
    withholds_tax = models.BooleanField(
        "withholding agent", default=False,
        help_text="Deducts withholding tax from payments and gives a withholding receipt.")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=60, default="Addis Ababa")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SalesOrder(TimeStamped):
    class OrderType(models.TextChoices):
        MTO = "mto", "Make to order"
        MTS = "mts", "Make to stock"
        CONTRACT = "contract", "Contract / fit-out project"

    class Status(models.TextChoices):
        QUOTE = "quote", "Quote"
        CONFIRMED = "confirmed", "Confirmed"
        DRAFTING = "drafting", "CAD drafting"
        PRODUCTION = "production", "In production"
        FINISHING = "finishing", "Finishing"
        DISPATCHED = "dispatched", "Dispatched"
        INSTALLED = "installed", "Installed"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=20, unique=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    order_type = models.CharField(max_length=10, choices=OrderType.choices, default=OrderType.MTO)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUOTE)
    order_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    site_address = models.TextField(blank=True)
    target_margin = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-order_date", "-id"]

    def __str__(self):
        return f"{self.number} {self.customer}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            prefix = "Q" if self.status == self.Status.QUOTE else "SO"
            self.number = f"{prefix}-{self.pk:06d}"
            super().save(update_fields=["number"])

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines.all()), Decimal(0)).quantize(Q)

    @property
    def estimated_cost(self):
        return sum((line.estimated_unit_cost * line.quantity for line in self.lines.all()), Decimal(0)).quantize(Q)


class SalesOrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=10)
    template = models.ForeignKey(ProductTemplate, on_delete=models.PROTECT)
    configuration = models.JSONField(default=dict, help_text="Parameter values chosen for this line.")
    description = models.CharField(max_length=200, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    estimated_unit_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), help_text="ETB, ex VAT.")
    price_locked = models.BooleanField(default=False, help_text="Keep a hand-entered price when re-pricing.")
    estimate = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order", "sequence", "id"]

    def __str__(self):
        return f"{self.order.number} {self.sequence} {self.template.code}"

    @property
    def line_total(self):
        return (self.unit_price * self.quantity).quantize(Q)
