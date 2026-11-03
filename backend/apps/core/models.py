from decimal import Decimal

from django.db import models


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UOM(models.Model):
    """A unit of measure. Each category has one base unit with ratio 1.

    Item-specific packaging (a 2440x1220 sheet, a 200 m roll) is not a UOM here;
    it lives in catalog.ItemUOMConversion because its size depends on the item.
    """

    class Category(models.TextChoices):
        COUNT = "count", "Count"
        LENGTH = "length", "Length"
        AREA = "area", "Area"
        VOLUME = "volume", "Volume"
        MASS = "mass", "Mass"

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    category = models.CharField(max_length=16, choices=Category.choices)
    ratio_to_base = models.DecimalField(
        max_digits=18, decimal_places=9, default=Decimal("1"),
        help_text="How many base units one of this unit is, e.g. mm = 0.001 m.",
    )

    class Meta:
        ordering = ["category", "code"]
        verbose_name = "unit of measure"

    def __str__(self):
        return self.code

    def to_base(self, qty):
        return Decimal(qty) * self.ratio_to_base


class WorkCenter(models.Model):
    """A machine or station on the shop floor, with its hourly cost rates in ETB."""

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=80)
    machine_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        help_text="Machine overhead, ETB per hour (depreciation, power, tooling).",
    )
    labour_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0"),
        help_text="Loaded operator cost, ETB per hour.",
    )
    hours_per_day = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("8"))

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class CostSettings(models.Model):
    """Company-wide costing parameters. Use CostSettings.current()."""

    overhead_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.12"))
    nesting_yield = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.85"))
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.15"))
    default_margin = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.30"))

    class Meta:
        verbose_name_plural = "cost settings"

    def __str__(self):
        return "Cost settings"

    @classmethod
    def current(cls):
        obj = cls.objects.first()
        return obj or cls()
