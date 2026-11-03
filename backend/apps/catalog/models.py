from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import UOM, TimeStamped, WorkCenter

from .formula import FormulaError, evaluate


class Item(TimeStamped):
    """A raw material or bought-in part. Only these get static item codes;
    configurable products are ProductTemplates and never get a code per size."""

    class Kind(models.TextChoices):
        BOARD = "board", "Sheet board"
        EDGEBAND = "edgeband", "Edgeband"
        HARDWARE = "hardware", "Hardware"
        FINISH = "finish", "Finish / coating"
        CONSUMABLE = "consumable", "Consumable"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    base_uom = models.ForeignKey(UOM, on_delete=models.PROTECT, help_text="Unit stock is kept in.")
    standard_cost = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0"),
        help_text="ETB per base unit, used for estimates until actual costs exist.",
    )
    thickness_mm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    sheet_length_mm = models.PositiveIntegerField(null=True, blank=True)
    sheet_width_mm = models.PositiveIntegerField(null=True, blank=True)
    track_lots = models.BooleanField(default=True)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    lead_time_days = models.PositiveIntegerField(default=7)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        if self.kind == self.Kind.BOARD:
            if not (self.thickness_mm and self.sheet_length_mm and self.sheet_width_mm):
                raise ValidationError("Boards need thickness and sheet size.")
            if self.base_uom.category != UOM.Category.AREA:
                raise ValidationError("Boards must be stocked in an area unit (m2).")

    @property
    def sheet_area_m2(self):
        if self.sheet_length_mm and self.sheet_width_mm:
            return Decimal(self.sheet_length_mm) * Decimal(self.sheet_width_mm) / Decimal(1_000_000)
        return None


class ItemUOMConversion(models.Model):
    """Item-specific pack sizes: 1 sheet = 2.9768 m2, 1 roll = 200 m, 1 drum = 20 L."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="conversions")
    name = models.CharField(max_length=32, help_text="sheet, roll, drum, box ...")
    base_qty = models.DecimalField(max_digits=14, decimal_places=6, help_text="Base units per one of these.")

    class Meta:
        unique_together = [("item", "name")]

    def __str__(self):
        return f"1 {self.name} of {self.item.code} = {self.base_qty} {self.item.base_uom}"


class ProductTemplate(TimeStamped):
    """A configurable product, e.g. 'Base cabinet' or 'Drawer box'.

    Parameters describe what a salesperson chooses; BOM lines and routing steps
    turn those choices into parts, materials and machine time via formulas."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_sellable = models.BooleanField(
        default=True, help_text="Untick for sub-assemblies used only inside other templates."
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class TemplateParameter(models.Model):
    class Kind(models.TextChoices):
        NUMBER = "number", "Number"
        CHOICE = "choice", "Choice"
        ITEM = "item", "Material (item code)"

    template = models.ForeignKey(ProductTemplate, on_delete=models.CASCADE, related_name="parameters")
    name = models.SlugField(max_length=32, help_text="Used in formulas, e.g. W, H, board.")
    label = models.CharField(max_length=80)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.NUMBER)
    default = models.CharField(max_length=64, blank=True)
    min_value = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    max_value = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    choices = models.JSONField(
        default=list, blank=True,
        help_text='For choice parameters: allowed values, or [value, label] pairs. For item parameters: allowed item codes (empty = any of item_kind).',
    )
    item_kind = models.CharField(max_length=16, choices=Item.Kind.choices, blank=True)
    sequence = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["template", "sequence", "id"]
        unique_together = [("template", "name")]

    def __str__(self):
        return f"{self.template.code}.{self.name}"


class BOMLine(models.Model):
    """One line of a template's bill of materials.

    line_type:
      panel        a cut part from sheet stock. Material comes from ``item`` or the item
                   parameter named in ``item_param``; size from length/width formulas.
      item         a bought-in or bulk item (hinges, glue, lacquer), qty from qty_formula.
      subassembly  another template (e.g. a drawer box), with its parameters set by
                   ``child_params`` formulas evaluated in this template's context.
    """

    class LineType(models.TextChoices):
        PANEL = "panel", "Cut panel"
        ITEM = "item", "Item"
        SUBASSEMBLY = "subassembly", "Sub-assembly"

    template = models.ForeignKey(ProductTemplate, on_delete=models.CASCADE, related_name="bom_lines")
    sequence = models.PositiveIntegerField(default=10)
    component = models.CharField(max_length=40, blank=True, help_text="Grouping label, e.g. Carcass, Fronts.")
    name = models.CharField(max_length=80)
    line_type = models.CharField(max_length=12, choices=LineType.choices)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    item_param = models.CharField(max_length=32, blank=True, help_text="Parameter holding the item code.")
    child_template = models.ForeignKey(
        ProductTemplate, on_delete=models.PROTECT, null=True, blank=True, related_name="used_in"
    )
    child_params = models.JSONField(default=dict, blank=True, help_text='{"W": "W - 2*T - 26", ...}')
    condition = models.CharField(max_length=200, blank=True, help_text="Line is used only when true.")
    qty_formula = models.CharField(max_length=200, default="1")
    length_formula = models.CharField(max_length=200, blank=True, help_text="Panel length, mm.")
    width_formula = models.CharField(max_length=200, blank=True, help_text="Panel width, mm.")
    edge_formula = models.CharField(max_length=200, blank=True, help_text="Edgeband per piece, mm.")
    edge_item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    edge_item_param = models.CharField(max_length=32, blank=True)
    grain_locked = models.BooleanField(default=False, help_text="Panel may not be rotated when nesting.")

    class Meta:
        ordering = ["template", "sequence", "id"]

    def __str__(self):
        return f"{self.template.code}: {self.name}"

    def clean(self):
        if self.line_type in (self.LineType.PANEL, self.LineType.ITEM) and not (self.item or self.item_param):
            raise ValidationError("Choose an item or an item parameter.")
        if self.line_type == self.LineType.PANEL and not (self.length_formula and self.width_formula):
            raise ValidationError("Panels need length and width formulas.")
        if self.line_type == self.LineType.SUBASSEMBLY and not self.child_template:
            raise ValidationError("Choose the sub-assembly template.")
        if self.child_template_id and self.child_template_id == self.template_id:
            raise ValidationError("A template cannot contain itself.")


class RoutingStep(models.Model):
    template = models.ForeignKey(ProductTemplate, on_delete=models.CASCADE, related_name="routing")
    sequence = models.PositiveIntegerField(default=10)
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT)
    description = models.CharField(max_length=120, blank=True)
    minutes_formula = models.CharField(
        max_length=200,
        help_text="Minutes per unit. May use parameters and n_panels, edge_m, front_m2.",
    )
    condition = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["template", "sequence", "id"]

    def __str__(self):
        return f"{self.template.code} {self.sequence} {self.work_center.code}"


def validate_formula(expr, sample_vars):
    try:
        evaluate(expr, sample_vars)
    except FormulaError as e:
        raise ValidationError(str(e)) from None
