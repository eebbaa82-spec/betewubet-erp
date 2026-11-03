from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import WorkCenter


class Machine(models.Model):
    """A physical machine. Linked to a work center, its running hours come from the
    time scanned at that station, on top of the hours it had when it was set up here."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    work_center = models.ForeignKey(WorkCenter, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="machines")
    make_model = models.CharField(max_length=100, blank=True)
    serial_no = models.CharField(max_length=60, blank=True)
    opening_hours = models.DecimalField(max_digits=10, decimal_places=1, default=Decimal(0),
                                        help_text="Running hours on the meter when it was set up in the system.")
    hours_since = models.DateTimeField(default=timezone.now, help_text="Station time from this moment counts.")
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class MaintenancePlan(models.Model):
    """A recurring service task, due every N running hours, every N days, or whichever comes first."""

    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="plans")
    task = models.CharField(max_length=160)
    instructions = models.TextField(blank=True)
    every_hours = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    every_days = models.PositiveIntegerField(null=True, blank=True)
    last_done_at = models.DateTimeField(default=timezone.now)
    last_done_hours = models.DecimalField(max_digits=10, decimal_places=1, default=Decimal(0))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["machine", "task"]

    def __str__(self):
        return f"{self.machine.code}: {self.task}"

    def clean(self):
        if not self.every_hours and not self.every_days:
            raise ValidationError("Set an interval in running hours, in days, or both.")


class MaintenanceLog(models.Model):
    """A service done, or a breakdown from report to repair."""

    class Kind(models.TextChoices):
        PREVENTIVE = "preventive", "Planned service"
        BREAKDOWN = "breakdown", "Breakdown"

    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="logs")
    plan = models.ForeignKey(MaintenancePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    description = models.CharField(max_length=240)
    machine_down = models.BooleanField(default=False, help_text="The machine cannot run until this is closed.")
    reported_at = models.DateTimeField(default=timezone.now)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    action_taken = models.TextField(blank=True)
    done_by = models.CharField(max_length=80, blank=True, help_text="Technician or service company.")
    parts_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0), help_text="ETB")
    machine_hours = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ["-reported_at", "-id"]

    def __str__(self):
        return f"{self.machine.code} {self.get_kind_display()}: {self.description}"

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def downtime_minutes(self):
        if not self.machine_down:
            return Decimal(0)
        end = self.closed_at or timezone.now()
        return Decimal((end - self.reported_at).total_seconds() / 60).quantize(Decimal("1"))
