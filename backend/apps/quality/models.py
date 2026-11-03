from django.conf import settings
from django.db import models

from apps.core.models import WorkCenter
from apps.production.models import NonConformance, WorkOrder, WorkOrderOperation


class Checklist(models.Model):
    """What to check at a station, or at final inspection before a job may ship."""

    class Stage(models.TextChoices):
        STATION = "station", "At a station"
        FINAL = "final", "Final inspection before dispatch"

    name = models.CharField(max_length=100)
    stage = models.CharField(max_length=8, choices=Stage.choices, default=Stage.STATION)
    work_center = models.ForeignKey(WorkCenter, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name="checklists", help_text="For station checklists.")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["stage", "work_center__code", "name"]

    def __str__(self):
        return self.name


class ChecklistItem(models.Model):
    class Kind(models.TextChoices):
        PASS_FAIL = "pass_fail", "Pass / fail"
        MEASURE = "measure", "Measurement"

    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="items")
    sequence = models.PositiveIntegerField(default=10)
    text = models.CharField(max_length=160)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PASS_FAIL)
    target = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="mm")
    tolerance = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="± mm")

    class Meta:
        ordering = ["checklist", "sequence", "id"]

    def __str__(self):
        return self.text


class Inspection(models.Model):
    class Result(models.TextChoices):
        PASS = "pass", "Passed"
        FAIL = "fail", "Failed"

    number = models.CharField(max_length=20, unique=True, blank=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.PROTECT, related_name="inspections")
    operation = models.ForeignKey(WorkOrderOperation, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="inspections")
    checklist = models.ForeignKey(Checklist, on_delete=models.PROTECT, related_name="inspections")
    result = models.CharField(max_length=4, choices=Result.choices)
    failed_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    non_conformance = models.ForeignKey(NonConformance, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="+")
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.number} {self.work_order} {self.get_result_display()}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"QC-{self.pk:05d}"
            super().save(update_fields=["number"])


class InspectionResult(models.Model):
    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="results")
    item = models.ForeignKey(ChecklistItem, on_delete=models.PROTECT)
    passed = models.BooleanField()
    value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["inspection", "item__sequence"]
