"""Sample master data: units, work centers, materials and two parametric templates
(a base cabinet that contains drawer boxes). Prices are illustrative ETB figures,
not real supplier prices. Used by ``manage.py seed_demo`` and by the tests."""
from datetime import date
from decimal import Decimal

from apps.core.models import UOM, CostSettings, WorkCenter

from .models import BOMLine, Item, ItemUOMConversion, ProductTemplate, RoutingStep, TemplateParameter

SHEET = (2440, 1220)

BOARDS = [
    # code, name, thickness, ETB per sheet
    ("MDF-WHT-18", "MDF 18 mm white melamine", 18, 6500),
    ("CHB-OAK-18", "Chipboard 18 mm oak melamine", 18, 5200),
    ("PLY-BIR-18", "Plywood 18 mm birch", 18, 9800),
    ("MDF-RAW-18", "MDF 18 mm raw, for spraying", 18, 4300),
    ("VEN-OAK-18", "MDF 18 mm oak veneered", 18, 11800),
    ("HDF-WHT-3", "HDF 3 mm white", 3, 1600),
]
OTHER_ITEMS = [
    # code, name, kind, uom, ETB per base unit, pack name, base per pack
    ("EB-22-04", "PVC edgeband 22 x 0.4 mm", "edgeband", "m", 28, "roll", 200),
    ("EB-22-2", "PVC edgeband 22 x 2 mm", "edgeband", "m", 46, "roll", 100),
    ("HNG-SC-110", "Hinge, soft-close 110 deg", "hardware", "pcs", 180, None, None),
    ("SLD-450", "Drawer slide pair, ball-bearing 450 mm", "hardware", "pcs", 950, None, None),
    ("HDL-BAR-160", "Bar handle 160 mm, brushed", "hardware", "pcs", 220, None, None),
    ("HDL-KNOB", "Round knob 30 mm", "hardware", "pcs", 90, None, None),
    ("LEG-100", "Adjustable leg 100 mm", "hardware", "pcs", 60, None, None),
    ("SCR-CONF", "Confirmat screw 7 x 50", "consumable", "pcs", Decimal("2.5"), "box", 500),
    ("SCR-4x16", "Chipboard screw 4 x 16", "consumable", "pcs", Decimal("0.8"), "box", 1000),
    ("PIN-SHELF", "Shelf support pin", "hardware", "pcs", 3, None, None),
    ("GLUE-PVA", "PVA glue D3", "consumable", "L", 320, "can", 5),
    ("LAC-PU", "PU lacquer, white satin", "finish", "L", 1100, "drum", 20),
    ("LAC-CLR", "PU lacquer, clear matt", "finish", "L", 1250, "drum", 20),
]
WORK_CENTERS = [
    ("SAW", "Panel saw", 600), ("EDGE", "Edgebander", 520), ("CNC", "CNC drilling and routing", 900),
    ("SAND", "Sanding", 180), ("SPRAY", "Spray booth", 450), ("ASM", "Assembly", 150), ("PACK", "Packing", 120),
]
OPERATOR_RATE = 95

N_FRONTS = "(drawers if drawers > 0 else (2 if W > 600 else 1))"
DOORS = "(2 if W > 600 else 1)"
DOOR_W = "((W - 4) / (2 if W > 600 else 1) - (2 if W > 600 else 0))"
DF_H = "((H - 4) / drawers - 3)"


def load():
    CostSettings.objects.get_or_create(pk=1)
    uoms = {}
    for code, name, cat, ratio in [
        ("pcs", "Pieces", "count", 1), ("m", "Metre", "length", 1), ("mm", "Millimetre", "length", "0.001"),
        ("m2", "Square metre", "area", 1), ("L", "Litre", "volume", 1), ("kg", "Kilogram", "mass", 1),
    ]:
        uoms[code], _ = UOM.objects.update_or_create(
            code=code, defaults={"name": name, "category": cat, "ratio_to_base": Decimal(str(ratio))})

    for code, name, rate in WORK_CENTERS:
        WorkCenter.objects.update_or_create(
            code=code, defaults={"name": name, "machine_rate": rate, "labour_rate": OPERATOR_RATE})

    sheet_m2 = Decimal(SHEET[0] * SHEET[1]) / Decimal(1_000_000)
    for code, name, t, price in BOARDS:
        item, _ = Item.objects.update_or_create(code=code, defaults={
            "name": name, "kind": "board", "base_uom": uoms["m2"], "thickness_mm": t,
            "sheet_length_mm": SHEET[0], "sheet_width_mm": SHEET[1],
            "standard_cost": (Decimal(price) / sheet_m2).quantize(Decimal("0.0001")),
        })
        ItemUOMConversion.objects.update_or_create(item=item, name="sheet", defaults={"base_qty": sheet_m2})
    for code, name, kind, uom, cost, pack, per in OTHER_ITEMS:
        item, _ = Item.objects.update_or_create(code=code, defaults={
            "name": name, "kind": kind, "base_uom": uoms[uom], "standard_cost": Decimal(str(cost)),
            "track_lots": kind in ("finish", "edgeband"),
        })
        if pack:
            ItemUOMConversion.objects.update_or_create(item=item, name=pack, defaults={"base_qty": per})

    _drawer_box()
    _base_cabinet()


def _template(code, name, sellable, params):
    t, _ = ProductTemplate.objects.update_or_create(code=code, defaults={"name": name, "is_sellable": sellable})
    t.parameters.all().delete()
    t.bom_lines.all().delete()
    t.routing.all().delete()
    for i, p in enumerate(params):
        TemplateParameter.objects.create(template=t, sequence=(i + 1) * 10, **p)
    return t


def _lines(t, lines):
    items = {i.code: i for i in Item.objects.all()}
    for i, ln in enumerate(lines):
        ln = dict(ln)
        for key in ("item", "edge_item"):
            if ln.get(key):
                ln[key] = items[ln[key]]
        if ln.get("child_template"):
            ln["child_template"] = ProductTemplate.objects.get(code=ln["child_template"])
        line = BOMLine(template=t, sequence=(i + 1) * 10, **ln)
        line.full_clean()
        line.save()


def _routing(t, steps):
    wcs = {w.code: w for w in WorkCenter.objects.all()}
    for i, (wc, formula, cond) in enumerate(steps):
        RoutingStep.objects.create(template=t, sequence=(i + 1) * 10, work_center=wcs[wc],
                                   minutes_formula=formula, condition=cond)


def _drawer_box():
    t = _template("DRAWER-BOX", "Drawer box", False, [
        {"name": "W", "label": "Outside width (mm)", "kind": "number", "min_value": 150, "max_value": 1200},
        {"name": "D", "label": "Depth (mm)", "kind": "number", "min_value": 200, "max_value": 600},
        {"name": "H", "label": "Side height (mm)", "kind": "number", "min_value": 60, "max_value": 300},
        {"name": "board", "label": "Board", "kind": "item", "item_kind": "board", "default": "MDF-WHT-18"},
    ])
    _lines(t, [
        {"name": "Drawer side", "line_type": "panel", "item_param": "board", "qty_formula": "2",
         "length_formula": "D", "width_formula": "H", "edge_formula": "D", "edge_item": "EB-22-04"},
        {"name": "Drawer front/back", "line_type": "panel", "item_param": "board", "qty_formula": "2",
         "length_formula": "W - 2*board_t", "width_formula": "H", "edge_formula": "W - 2*board_t",
         "edge_item": "EB-22-04"},
        {"name": "Drawer bottom", "line_type": "panel", "item": "HDF-WHT-3",
         "length_formula": "W", "width_formula": "D"},
        {"name": "Drawer slide pair", "line_type": "item", "item": "SLD-450"},
        {"name": "Screws", "line_type": "item", "item": "SCR-4x16", "qty_formula": "8"},
    ])
    _routing(t, [("SAW", "1.2*n_panels", ""), ("EDGE", "0.4*edge_m + 0.5*n_panels", ""),
                 ("CNC", "1.8*n_panels", ""), ("ASM", "8", "")])


def _base_cabinet():
    t = _template("BASE-CAB", "Base cabinet", True, [
        {"name": "W", "label": "Width (mm)", "kind": "number", "default": "800", "min_value": 300, "max_value": 1200},
        {"name": "H", "label": "Height (mm)", "kind": "number", "default": "720", "min_value": 400, "max_value": 2200},
        {"name": "D", "label": "Depth (mm)", "kind": "number", "default": "560", "min_value": 300, "max_value": 650},
        {"name": "board", "label": "Carcass board", "kind": "item", "item_kind": "board", "default": "MDF-WHT-18",
         "choices": ["MDF-WHT-18", "CHB-OAK-18", "PLY-BIR-18"]},
        {"name": "front", "label": "Front finish", "kind": "choice", "default": "mel", "choices": [["mel", "Same melamine as carcass"], ["lac", "MDF, lacquer sprayed"],
                     ["ven", "Oak veneer, clear lacquer"]]},
        {"name": "drawers", "label": "Drawers (0 = doors)", "kind": "number", "default": "3",
         "min_value": 0, "max_value": 4},
        {"name": "handle", "label": "Handle", "kind": "choice", "default": "bar", "choices": [["bar", "Bar handle 160 mm"], ["knob", "Round knob"],
                     ["gola", "Handleless, routed grip"]]},
    ])
    carcass = {"component": "Carcass", "line_type": "panel", "item_param": "board", "edge_item": "EB-22-04"}
    fronts = {"component": "Fronts", "line_type": "panel"}
    door = {"qty_formula": DOORS, "length_formula": "H - 4", "width_formula": DOOR_W}
    dfront = {"qty_formula": "drawers", "length_formula": "W - 4", "width_formula": DF_H}
    _lines(t, [
        {**carcass, "name": "Side panel", "qty_formula": "2", "length_formula": "H", "width_formula": "D",
         "edge_formula": "H"},
        {**carcass, "name": "Bottom", "length_formula": "W - 2*board_t", "width_formula": "D",
         "edge_formula": "W - 2*board_t"},
        {**carcass, "name": "Top rail", "qty_formula": "2", "length_formula": "W - 2*board_t", "width_formula": "100",
         "edge_formula": "W - 2*board_t"},
        {"component": "Carcass", "name": "Back panel", "line_type": "panel", "item": "HDF-WHT-3",
         "length_formula": "W - 10", "width_formula": "H - 10"},
        {**carcass, "name": "Shelf", "condition": "drawers == 0", "length_formula": "W - 2*board_t - 2",
         "width_formula": "D - 40", "edge_formula": "W - 2*board_t - 2"},
        {**fronts, **door, "name": "Door", "condition": "drawers == 0 and front == 'mel'", "item_param": "board",
         "edge_formula": f"2*((H - 4) + {DOOR_W})", "edge_item": "EB-22-2"},
        {**fronts, **door, "name": "Door, lacquered", "condition": "drawers == 0 and front == 'lac'",
         "item": "MDF-RAW-18"},
        {**fronts, **door, "name": "Door, oak veneer", "condition": "drawers == 0 and front == 'ven'",
         "item": "VEN-OAK-18", "grain_locked": True},
        {**fronts, **dfront, "name": "Drawer front", "condition": "drawers > 0 and front == 'mel'",
         "item_param": "board", "edge_formula": f"2*((W - 4) + {DF_H})", "edge_item": "EB-22-2"},
        {**fronts, **dfront, "name": "Drawer front, lacquered", "condition": "drawers > 0 and front == 'lac'",
         "item": "MDF-RAW-18"},
        {**fronts, **dfront, "name": "Drawer front, oak veneer", "condition": "drawers > 0 and front == 'ven'",
         "item": "VEN-OAK-18", "grain_locked": True},
        {"component": "Drawers", "name": "Drawer box", "line_type": "subassembly", "condition": "drawers > 0",
         "child_template": "DRAWER-BOX",
         "qty_formula": "drawers", "child_params": {
             "W": "W - 2*board_t - 26", "D": "D - 60", "H": f"min(140, {DF_H} - 40)", "board": "board"}},
        {"component": "Hardware", "name": "Hinge", "line_type": "item", "item": "HNG-SC-110",
         "condition": "drawers == 0", "qty_formula": f"{DOORS} * (3 if H > 900 else 2)"},
        {"component": "Hardware", "name": "Bar handle", "line_type": "item", "item": "HDL-BAR-160",
         "condition": "handle == 'bar'", "qty_formula": N_FRONTS},
        {"component": "Hardware", "name": "Knob", "line_type": "item", "item": "HDL-KNOB",
         "condition": "handle == 'knob'", "qty_formula": N_FRONTS},
        {"component": "Hardware", "name": "Leg", "line_type": "item", "item": "LEG-100", "qty_formula": "4"},
        {"component": "Hardware", "name": "Confirmat screw", "line_type": "item", "item": "SCR-CONF",
         "qty_formula": "12"},
        {"component": "Hardware", "name": "Shelf pin", "line_type": "item", "item": "PIN-SHELF",
         "condition": "drawers == 0", "qty_formula": "4"},
        {"component": "Finish", "name": "Glue", "line_type": "item", "item": "GLUE-PVA", "qty_formula": "0.05"},
        {"component": "Finish", "name": "White lacquer, 2 coats both sides", "line_type": "item", "item": "LAC-PU",
         "condition": "front == 'lac'", "qty_formula": "(W - 4) * (H - 4) / 1000000 * 2 * 2 * 0.12"},
        {"component": "Finish", "name": "Clear lacquer, 2 coats both sides", "line_type": "item",
         "item": "LAC-CLR", "condition": "front == 'ven'",
         "qty_formula": "(W - 4) * (H - 4) / 1000000 * 2 * 2 * 0.10"},
    ])
    _routing(t, [
        ("SAW", "1.2*n_panels + 4", ""),
        ("EDGE", "0.4*edge_m + 0.5*n_panels", ""),
        ("CNC", f"1.8*n_panels + (6*{N_FRONTS} if handle == 'gola' else 0)", ""),
        ("SAND", f"6*{N_FRONTS}", "front != 'mel'"),
        ("SPRAY", "22*front_m2*2 + 8", "front != 'mel'"),
        ("ASM", f"25 + (6*{DOORS} if drawers == 0 else 0)", ""),
        ("PACK", "10", ""),
    ])


def load_stock():
    """Opening stock, lots and a few offcuts so the inventory screens have data."""
    from apps.inventory.models import Location, Lot
    from apps.inventory.services import receive, register_offcut

    main, _ = Location.objects.get_or_create(code="MAIN", defaults={"name": "Main store"})
    rack, _ = Location.objects.get_or_create(code="OC-RACK", defaults={"name": "Offcut rack", "is_offcut_rack": True})
    if Lot.objects.exists():
        return
    sheet_m2 = Decimal(SHEET[0] * SHEET[1]) / Decimal(1_000_000)
    for code, sheets in [("MDF-WHT-18", 46), ("CHB-OAK-18", 22), ("PLY-BIR-18", 9), ("MDF-RAW-18", 31),
                         ("VEN-OAK-18", 6), ("HDF-WHT-3", 40)]:
        item = Item.objects.get(code=code)
        lot = Lot.objects.create(item=item, code=f"L-{code}-01", received_on=date(2026, 10, 15))
        receive(item, sheet_m2 * sheets, item.standard_cost, main, lot=lot, reference="OPENING")
    for code, qty in [("EB-22-04", 1840), ("EB-22-2", 620), ("HNG-SC-110", 420), ("SLD-450", 38),
                      ("HDL-BAR-160", 260), ("HDL-KNOB", 140), ("LEG-100", 600), ("SCR-CONF", 5200),
                      ("SCR-4x16", 8000), ("PIN-SHELF", 900), ("GLUE-PVA", 35), ("LAC-PU", 68), ("LAC-CLR", 22)]:
        item = Item.objects.get(code=code)
        lot = Lot.objects.create(item=item, code=f"L-{code}-01", received_on=date(2026, 10, 15)) \
            if item.track_lots else None
        receive(item, qty, item.standard_cost, main, lot=lot, reference="OPENING")
    for code, L, W in [("MDF-WHT-18", 1180, 580), ("MDF-WHT-18", 760, 540), ("MDF-WHT-18", 720, 560),
                       ("CHB-OAK-18", 1620, 610), ("HDF-WHT-3", 1300, 780)]:
        item = Item.objects.get(code=code)
        register_offcut(item, L, W, rack, lot=item.lots.first())
