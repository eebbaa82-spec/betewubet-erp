from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Item, ProductTemplate
from apps.core.models import WorkCenter


class WorkOrder(models.Model):
    """The costing unit: material issues and shop-floor time all post against it."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        RELEASED = "released", "Released to floor"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=20, unique=True, blank=True)
    sales_line = models.ForeignKey(
        "sales.SalesOrderLine", on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders"
    )
    template = models.ForeignKey(ProductTemplate, on_delete=models.PROTECT)
    configuration = models.JSONField(default=dict)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    due_date = models.DateField(null=True, blank=True)
    exploded = models.JSONField(default=dict, help_text="BOM and routing frozen at creation.")
    estimate = models.JSONField(default=dict, help_text="Estimated cost breakdown in ETB at creation.")
    rework_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reworks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.number or f"WO (unsaved) {self.template.code}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"WO-{self.pk:06d}"
            super().save(update_fields=["number"])


class WorkOrderMaterial(models.Model):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="materials")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=16, decimal_places=4, help_text="In the item's base unit.")

    class Meta:
        unique_together = [("work_order", "item")]

    def __str__(self):
        return f"{self.work_order} {self.item.code} {self.planned_qty}"


class WorkOrderOperation(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        DONE = "done", "Done"

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="operations")
    sequence = models.PositiveIntegerField()
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT)
    description = models.CharField(max_length=160)
    planned_minutes = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)

    class Meta:
        ordering = ["work_order", "sequence"]

    def __str__(self):
        return f"{self.work_order} #{self.sequence} {self.work_center.code}"


class TimeLog(models.Model):
    """One start-to-stop span scanned at a station."""

    operation = models.ForeignKey(WorkOrderOperation, on_delete=models.CASCADE, related_name="time_logs")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    good_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    rejected_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    reject_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-started_at"]

    @property
    def minutes(self):
        if not self.ended_at:
            return Decimal("0")
        return Decimal((self.ended_at - self.started_at).total_seconds() / 60).quantize(Decimal("0.01"))


class NonConformance(models.Model):
    """A rejected part or batch reported at a station. It opens a rework work order."""

    number = models.CharField(max_length=20, unique=True, blank=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="non_conformances")
    operation = models.ForeignKey(WorkOrderOperation, on_delete=models.PROTECT, related_name="non_conformances")
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=120)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    rework_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} {self.reason}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"NCR-{self.pk:05d}"
            super().save(update_fields=["number"])
