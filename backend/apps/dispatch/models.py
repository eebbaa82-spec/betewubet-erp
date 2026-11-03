from django.conf import settings
from django.db import models

from apps.sales.models import SalesOrder, SalesOrderLine


class Delivery(models.Model):
    """A delivery note: finished goods for one order, on one vehicle, on one day."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        OUT = "out", "Out for delivery"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=20, unique=True, blank=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="deliveries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    scheduled_date = models.DateField()
    vehicle = models.CharField(max_length=40, blank=True, help_text="Plate number or truck name.")
    driver = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    install_required = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField(max_length=80, blank=True, help_text="Who signed for the goods at site.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_date", "-id"]
        verbose_name_plural = "deliveries"

    def __str__(self):
        return self.number or "DN (unsaved)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"DN-{self.pk:05d}"
            super().save(update_fields=["number"])


class DeliveryLine(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name="lines")
    sales_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="delivery_lines")
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["delivery", "sales_line__sequence", "id"]

    def __str__(self):
        return f"{self.delivery} {self.sales_line} x {self.quantity}"


class Installation(models.Model):
    """Fitting at the customer's site after a delivery, signed off by the customer."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        DONE = "done", "Done and signed off"
        SNAGS = "snags", "Return visit needed"

    number = models.CharField(max_length=20, unique=True, blank=True)
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name="installations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    scheduled_date = models.DateField()
    crew = models.CharField(max_length=120, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    signed_off_by = models.CharField(max_length=80, blank=True)
    snags = models.TextField(blank=True, help_text="What still needs fixing, one item per line.")
    notes = models.TextField(blank=True)
    return_visit_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["scheduled_date", "id"]

    def __str__(self):
        return self.number or "IN (unsaved)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"IN-{self.pk:05d}"
            super().save(update_fields=["number"])
