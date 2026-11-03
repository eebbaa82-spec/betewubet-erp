"""Turn a product template plus chosen parameters into a concrete BOM and routing.

    result = explode(template, {"W": 800, "H": 720, "D": 560, "board": "MDF-WHT-18", ...})
    result.panels       cut parts with exact sizes and edgeband
    result.items        hardware, glue, lacquer ...
    result.operations   minutes per work center
    result.material_totals()  {item_code: qty in base unit} for costing and MRP

The result is plain data (no database rows), so it can be frozen as JSON on an
order line and rebuilt exactly later.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from .formula import FormulaError, evaluate
from .models import BOMLine, Item, ProductTemplate, TemplateParameter

MAX_DEPTH = 6
MM2_PER_M2 = Decimal(1_000_000)


def _d(x, places="0.0001"):
    return Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _plain(x):
    return format(Decimal(x).normalize(), "f")


@dataclass
class PanelLine:
    path: str
    name: str
    item_code: str
    length_mm: Decimal
    width_mm: Decimal
    qty: Decimal
    edge_m: Decimal = Decimal("0")
    edge_item_code: str = ""
    grain_locked: bool = False

    @property
    def area_m2(self):
        return self.length_mm * self.width_mm * self.qty / MM2_PER_M2


@dataclass
class ItemLine:
    path: str
    name: str
    item_code: str
    qty: Decimal


@dataclass
class OperationLine:
    path: str
    template_code: str
    work_center_code: str
    description: str
    minutes: Decimal


@dataclass
class ExplodedBOM:
    template_code: str
    params: dict
    panels: list = field(default_factory=list)
    items: list = field(default_factory=list)
    operations: list = field(default_factory=list)

    def material_totals(self):
        """Total of every item in its base unit: boards in m2, edgeband in m, rest as entered."""
        totals = defaultdict(Decimal)
        for p in self.panels:
            totals[p.item_code] += p.area_m2
            if p.edge_item_code and p.edge_m:
                totals[p.edge_item_code] += p.edge_m
        for i in self.items:
            totals[i.item_code] += i.qty
        return {k: _d(v) for k, v in totals.items()}

    def minutes_by_work_center(self):
        totals = defaultdict(Decimal)
        for op in self.operations:
            totals[op.work_center_code] += op.minutes
        return {k: _d(v, "0.01") for k, v in totals.items()}

    def to_dict(self):
        def clean(obj):
            d = asdict(obj)
            return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}

        return {
            "template_code": self.template_code,
            "params": self.params,
            "panels": [clean(p) for p in self.panels],
            "items": [clean(i) for i in self.items],
            "operations": [clean(o) for o in self.operations],
            "material_totals": {k: str(v) for k, v in self.material_totals().items()},
            "minutes_by_work_center": {k: str(v) for k, v in self.minutes_by_work_center().items()},
        }


def resolve_params(template, given):
    """Apply defaults, check types and ranges. Returns the formula variables.

    Every item parameter also exposes ``<name>_t``: the board thickness in mm,
    so formulas can say ``W - 2*board_t``."""
    given = dict(given or {})
    params = list(template.parameters.all())
    known = {p.name for p in params}
    unknown = set(given) - known
    if unknown:
        raise ValidationError(f"Unknown parameter(s) for {template.code}: {', '.join(sorted(unknown))}")

    values, variables, errors = {}, {}, []
    for p in params:
        raw = given.get(p.name, p.default)
        if raw in (None, ""):
            errors.append(f"{p.label} is required")
            continue
        if p.kind == TemplateParameter.Kind.NUMBER:
            try:
                v = Decimal(str(raw))
            except Exception:
                errors.append(f"{p.label} must be a number")
                continue
            if p.min_value is not None and v < p.min_value:
                errors.append(f"{p.label} must be at least {_plain(p.min_value)}")
            if p.max_value is not None and v > p.max_value:
                errors.append(f"{p.label} must be at most {_plain(p.max_value)}")
            values[p.name] = float(v)
            variables[p.name] = float(v)
        elif p.kind == TemplateParameter.Kind.CHOICE:
            v = str(raw)
            if p.choices and v not in [str(c) for c in p.choices]:
                errors.append(f"{p.label} must be one of {', '.join(map(str, p.choices))}")
            values[p.name] = v
            variables[p.name] = v
        else:  # item
            code = str(raw)
            item = Item.objects.filter(code=code, active=True).first()
            if item is None:
                errors.append(f"{p.label}: no active item {code}")
                continue
            if p.choices and code not in p.choices:
                errors.append(f"{p.label}: {code} is not allowed here")
            if p.item_kind and item.kind != p.item_kind:
                errors.append(f"{p.label}: {code} is not a {p.get_item_kind_display().lower()}")
            values[p.name] = code
            variables[p.name] = code
            variables[f"{p.name}_t"] = float(item.thickness_mm or 0)
    if errors:
        raise ValidationError(errors)
    return values, variables


def explode(template, params=None, qty=1, _path="", _depth=0):
    if isinstance(template, str):
        template = ProductTemplate.objects.get(code=template)
    if _depth > MAX_DEPTH:
        raise ValidationError(f"Sub-assemblies nested deeper than {MAX_DEPTH} levels at {template.code}")

    values, env = resolve_params(template, params)
    result = ExplodedBOM(template_code=template.code, params=values)
    qty = Decimal(str(qty))

    def ev(expr, what, line):
        try:
            return evaluate(expr, env)
        except FormulaError as e:
            raise ValidationError(f"{template.code} / {getattr(line, 'name', line)}: {what}: {e}") from None

    def item_code_for(line, fixed, param):
        if fixed is not None:
            return fixed.code
        if param:
            if param not in env:
                raise ValidationError(f"{template.code} / {line.name}: unknown item parameter '{param}'")
            return env[param]
        return ""

    own_panels = []
    for line in template.bom_lines.select_related("item", "edge_item", "child_template"):
        if line.condition and not ev(line.condition, "condition", line):
            continue
        n = Decimal(str(ev(line.qty_formula, "quantity", line)))
        if n <= 0:
            continue
        path = " > ".join(x for x in (_path, line.component) if x)
        if line.line_type == BOMLine.LineType.PANEL:
            length = _d(ev(line.length_formula, "length", line), "0.1")
            width = _d(ev(line.width_formula, "width", line), "0.1")
            if length <= 0 or width <= 0:
                raise ValidationError(f"{template.code} / {line.name}: size works out to {length} x {width} mm")
            edge_mm = Decimal(str(ev(line.edge_formula, "edgeband", line))) if line.edge_formula else Decimal(0)
            edge_code = item_code_for(line, line.edge_item, line.edge_item_param) if edge_mm else ""
            panel = PanelLine(
                path=path, name=line.name,
                item_code=item_code_for(line, line.item, line.item_param),
                length_mm=length, width_mm=width, qty=n * qty,
                edge_m=_d(edge_mm * n * qty / 1000), edge_item_code=edge_code,
                grain_locked=line.grain_locked,
            )
            result.panels.append(panel)
            own_panels.append(panel)
        elif line.line_type == BOMLine.LineType.ITEM:
            result.items.append(ItemLine(
                path=path, name=line.name,
                item_code=item_code_for(line, line.item, line.item_param), qty=_d(n * qty),
            ))
        else:
            child_params = {k: ev(v, f"parameter {k}", line) for k, v in (line.child_params or {}).items()}
            child = explode(line.child_template, child_params, qty=n * qty,
                            _path=" > ".join(x for x in (path, line.name) if x), _depth=_depth + 1)
            result.panels += child.panels
            result.items += child.items
            result.operations += child.operations

    stats = {
        "n_panels": float(sum(p.qty for p in own_panels) / qty) if qty else 0.0,
        "panel_m2": float(sum(p.area_m2 for p in own_panels) / qty) if qty else 0.0,
        "edge_m": float(sum(p.edge_m for p in own_panels) / qty) if qty else 0.0,
        "front_m2": float(sum(p.area_m2 for p in own_panels if p.path.endswith("Fronts")) / qty) if qty else 0.0,
    }
    env.update(stats)
    for step in template.routing.select_related("work_center"):
        if step.condition and not ev(step.condition, "routing condition", step):
            continue
        minutes = Decimal(str(ev(step.minutes_formula, "minutes", step)))
        if minutes > 0:
            result.operations.append(OperationLine(
                path=_path or template.name, template_code=template.code,
                work_center_code=step.work_center.code,
                description=step.description or step.work_center.name,
                minutes=_d(minutes * qty, "0.01"),
            ))
    return result
