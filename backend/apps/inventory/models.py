from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Item


class Location(models.Model):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=80)
    is_offcut_rack = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Lot(models.Model):
    """A receipt batch. Holds the supplier batch and colour or dye-lot reference so a
    project can be kept to one veneer or paint batch."""

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="lots")
    code = models.CharField(max_length=32)
    supplier_batch = models.CharField(max_length=64, blank=True)
    colour_ref = models.CharField(max_length=64, blank=True, help_text="Dye lot, shade or colour code.")
    received_on = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["item", "received_on", "code"]
        unique_together = [("item", "code")]

    def __str__(self):
        return f"{self.item.code} / {self.code}"


class StockMove(models.Model):
    """The stock ledger. Rows are never edited or deleted; corrections are new rows.

    ``qty`` is signed and always in the item's base unit (m2 for boards, m for edgeband).
    On-hand quantity and stock value are sums over this table."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        ISSUE = "issue", "Issue to work order"
        RETURN = "return", "Return from work order"
        OFFCUT = "offcut", "Offcut put back to stock"
        SCRAP = "scrap", "Scrap"
        ADJUST = "adjust", "Count adjustment"
        TRANSFER = "transfer", "Transfer"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="moves")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, null=True, blank=True, related_name="moves")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="moves")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    qty = models.DecimalField(max_digits=16, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, help_text="ETB per base unit.")
    work_order = models.ForeignKey(
        "production.WorkOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="stock_moves"
    )
    reference = models.CharField(max_length=64, blank=True, help_text="GRN, PO or count sheet number.")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["item", "location", "lot"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.qty} {self.item.base_uom} {self.item.code}"

    @property
    def value(self):
        return self.qty * self.unit_cost

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Stock moves cannot be changed. Post a correcting move instead.")
        if self.item.track_lots and self.lot is None and self.kind != self.Kind.ADJUST:
            raise ValidationError(f"{self.item.code} is lot-tracked; choose a lot.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock moves cannot be deleted. Post a correcting move instead.")


class Offcut(models.Model):
    """A usable leftover piece of board with its own label, size and rack location.

    Its area is also in the stock ledger (an OFFCUT move), so the board's on-hand m2
    stays correct; this row adds the exact dimensions needed to cut from it."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved for a work order"
        USED = "used", "Used"
        SCRAPPED = "scrapped", "Scrapped"

    code = models.CharField(max_length=16, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="offcuts")
    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, null=True, blank=True)
    length_mm = models.PositiveIntegerField()
    width_mm = models.PositiveIntegerField()
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    source_work_order = models.ForeignKey(
        "production.WorkOrder", on_delete=models.SET_NULL, null=True, blank=True, related_name="offcuts_made"
    )
    reserved_for = models.ForeignKey(
        "production.WorkOrder", on_delete=models.SET_NULL, null=True, blank=True, related_name="offcuts_reserved"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item", "-length_mm", "-width_mm"]

    def __str__(self):
        return f"{self.code} {self.item.code} {self.length_mm}x{self.width_mm}"

    @property
    def area_m2(self):
        return Decimal(self.length_mm) * Decimal(self.width_mm) / Decimal(1_000_000)

    def fits(self, length_mm, width_mm, grain_locked=False):
        if self.length_mm >= length_mm and self.width_mm >= width_mm:
            return True
        return not grain_locked and self.length_mm >= width_mm and self.width_mm >= length_mm
