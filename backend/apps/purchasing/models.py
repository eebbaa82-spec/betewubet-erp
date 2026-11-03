from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Item

Q2 = Decimal("0.01")


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    tin = models.CharField("TIN", max_length=20, blank=True)
    vat_registered = models.BooleanField(default=True, help_text="Charges 15% VAT on its invoices.")
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    city = models.CharField(max_length=60, blank=True, default="Addis Ababa")
    lead_time_days = models.PositiveIntegerField(default=7)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SupplierItem(models.Model):
    """What a supplier sells us and in which pack: 1 sheet = 2.9768 m2 at ETB 6,500."""

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="supplier_items")
    supplier_code = models.CharField(max_length=40, blank=True)
    pack_name = models.CharField(max_length=24, help_text="sheet, roll, box, drum, pcs ...")
    pack_qty = models.DecimalField(max_digits=14, decimal_places=6, help_text="Base units in one pack.")
    price_per_pack = models.DecimalField(max_digits=14, decimal_places=2, help_text="ETB, before VAT.")
    min_packs = models.PositiveIntegerField(default=1)
    preferred = models.BooleanField(default=False)

    class Meta:
        unique_together = [("supplier", "item")]
        ordering = ["item__code", "-preferred", "price_per_pack"]

    def __str__(self):
        return f"{self.supplier} · {self.item.code} per {self.pack_name}"

    def clean(self):
        if self.pack_qty is not None and self.pack_qty <= 0:
            raise ValidationError({"pack_qty": "Must be more than zero."})


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent to supplier"
        PARTIAL = "partial", "Partly received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    OPEN = (Status.DRAFT, Status.SENT, Status.PARTIAL)

    number = models.CharField(max_length=20, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.number or "PO (unsaved)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"PO-{self.pk:05d}"
            super().save(update_fields=["number"])


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    pack_name = models.CharField(max_length=24)
    pack_qty = models.DecimalField(max_digits=14, decimal_places=6)
    packs = models.DecimalField(max_digits=12, decimal_places=2)
    price_per_pack = models.DecimalField(max_digits=14, decimal_places=2)
    received_packs = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.order} {self.item.code} x {self.packs} {self.pack_name}"

    @property
    def amount(self):
        return (self.packs * self.price_per_pack).quantize(Q2)

    @property
    def open_packs(self):
        return max(self.packs - self.received_packs, Decimal(0))

    @property
    def unit_cost(self):
        """ETB per base unit, which is what the stock ledger records."""
        return (self.price_per_pack / self.pack_qty).quantize(Decimal("0.0001"))
