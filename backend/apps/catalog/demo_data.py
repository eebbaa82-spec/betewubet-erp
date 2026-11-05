"""Sample master data: units, work centers, materials and parametric templates
(base cabinet with drawer boxes, wardrobe, office desk, bookshelf). Prices are illustrative ETB figures,
not real supplier prices. Used by ``manage.py seed_demo`` and by the tests."""
from datetime import date
from decimal import Decimal

from django.db import models

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
    ("RAIL-25", "Wardrobe rail, oval 25 mm chrome", "hardware", "m", 260, "length", 3),
    ("RAIL-SUP", "Wardrobe rail end support", "hardware", "pcs", 45, None, None),
    ("CBL-GROM", "Cable grommet 60 mm", "hardware", "pcs", 120, None, None),
    ("GLIDE-20", "Furniture glide 20 mm", "hardware", "pcs", 15, None, None),
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
    _wardrobe()
    _desk()
    _bookshelf()


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


WR_DOORS = "(2 if W <= 1000 else (3 if W <= 1500 else 4))"
WR_DOOR_W = f"((W - 4) / {WR_DOORS} - 2)"
BOARD_CHOICES = ["MDF-WHT-18", "CHB-OAK-18", "PLY-BIR-18"]


def _wardrobe():
    t = _template("WARDROBE", "Wardrobe", True, [
        {"name": "W", "label": "Width (mm)", "kind": "number", "default": "1200", "min_value": 600, "max_value": 2400},
        {"name": "H", "label": "Height (mm)", "kind": "number", "default": "2100", "min_value": 1600, "max_value": 2400},
        {"name": "D", "label": "Depth (mm)", "kind": "number", "default": "600", "min_value": 500, "max_value": 650},
        {"name": "board", "label": "Board", "kind": "item", "item_kind": "board", "default": "CHB-OAK-18",
         "choices": BOARD_CHOICES},
        {"name": "front", "label": "Door finish", "kind": "choice", "default": "mel",
         "choices": [["mel", "Same melamine as carcass"], ["lac", "MDF, lacquer sprayed"]]},
        {"name": "shelves", "label": "Shelves", "kind": "number", "default": "2", "min_value": 0, "max_value": 6},
    ])
    carcass = {"component": "Carcass", "line_type": "panel", "item_param": "board", "edge_item": "EB-22-04"}
    door = {"component": "Fronts", "line_type": "panel", "qty_formula": WR_DOORS, "length_formula": "H - 4",
            "width_formula": WR_DOOR_W}
    _lines(t, [
        {**carcass, "name": "Side panel", "qty_formula": "2", "length_formula": "H", "width_formula": "D",
         "edge_formula": "H"},
        {**carcass, "name": "Top and bottom", "qty_formula": "2", "length_formula": "W - 2*board_t",
         "width_formula": "D", "edge_formula": "W - 2*board_t"},
        {**carcass, "name": "Shelf", "qty_formula": "shelves", "condition": "shelves > 0",
         "length_formula": "W - 2*board_t - 2", "width_formula": "D - 60", "edge_formula": "W - 2*board_t - 2"},
        {"component": "Carcass", "name": "Back panel", "line_type": "panel", "item": "HDF-WHT-3",
         "length_formula": "W - 10", "width_formula": "H - 10"},
        {**door, "name": "Door", "condition": "front == 'mel'", "item_param": "board",
         "edge_formula": f"2*((H - 4) + {WR_DOOR_W})", "edge_item": "EB-22-2"},
        {**door, "name": "Door, lacquered", "condition": "front == 'lac'", "item": "MDF-RAW-18"},
        {"component": "Hardware", "name": "Hanging rail", "line_type": "item", "item": "RAIL-25",
         "qty_formula": "(W - 2*board_t) / 1000"},
        {"component": "Hardware", "name": "Rail support", "line_type": "item", "item": "RAIL-SUP", "qty_formula": "2"},
        {"component": "Hardware", "name": "Hinge", "line_type": "item", "item": "HNG-SC-110",
         "qty_formula": f"{WR_DOORS} * (4 if H > 1900 else 3)"},
        {"component": "Hardware", "name": "Bar handle", "line_type": "item", "item": "HDL-BAR-160",
         "qty_formula": WR_DOORS},
        {"component": "Hardware", "name": "Shelf pin", "line_type": "item", "item": "PIN-SHELF",
         "qty_formula": "4*shelves", "condition": "shelves > 0"},
        {"component": "Hardware", "name": "Glide", "line_type": "item", "item": "GLIDE-20", "qty_formula": "4"},
        {"component": "Hardware", "name": "Confirmat screw", "line_type": "item", "item": "SCR-CONF",
         "qty_formula": "16"},
        {"component": "Finish", "name": "White lacquer, 2 coats both sides", "line_type": "item", "item": "LAC-PU",
         "condition": "front == 'lac'", "qty_formula": "(W - 4) * (H - 4) / 1000000 * 2 * 2 * 0.12"},
    ])
    _routing(t, [
        ("SAW", "1.2*n_panels + 6", ""),
        ("EDGE", "0.4*edge_m + 0.5*n_panels", ""),
        ("CNC", "1.8*n_panels + 2", ""),
        ("SAND", f"8*{WR_DOORS}", "front == 'lac'"),
        ("SPRAY", "22*front_m2*2 + 10", "front == 'lac'"),
        ("ASM", f"40 + 5*{WR_DOORS}", ""),
        ("PACK", "15", ""),
    ])


def _desk():
    t = _template("DESK", "Office desk", True, [
        {"name": "W", "label": "Width (mm)", "kind": "number", "default": "1400", "min_value": 1000, "max_value": 2000},
        {"name": "D", "label": "Depth (mm)", "kind": "number", "default": "700", "min_value": 600, "max_value": 900},
        {"name": "H", "label": "Height (mm)", "kind": "number", "default": "750", "min_value": 700, "max_value": 780},
        {"name": "board", "label": "Board", "kind": "item", "item_kind": "board", "default": "CHB-OAK-18",
         "choices": BOARD_CHOICES},
        {"name": "drawers", "label": "Pedestal drawers (0 = none)", "kind": "number", "default": "3",
         "min_value": 0, "max_value": 3},
        {"name": "grommet", "label": "Cable grommet", "kind": "choice", "default": "yes",
         "choices": [["yes", "Yes"], ["no", "No"]]},
    ])
    panel = {"component": "Desk", "line_type": "panel", "item_param": "board", "edge_item": "EB-22-2"}
    _lines(t, [
        {**panel, "name": "Top", "length_formula": "W", "width_formula": "D", "edge_formula": "2*(W + D)"},
        {**panel, "name": "Side panel", "qty_formula": "2", "length_formula": "H - board_t",
         "width_formula": "D - 50", "edge_formula": "2*(H - board_t)"},
        {**panel, "name": "Modesty panel", "length_formula": "W - 2*board_t", "width_formula": "350",
         "edge_formula": "W - 2*board_t"},
        {**panel, "name": "Pedestal side", "condition": "drawers > 0", "length_formula": "H - board_t - 20",
         "width_formula": "D - 100", "edge_formula": "H - board_t - 20"},
        {"component": "Fronts", "name": "Drawer front", "line_type": "panel", "item_param": "board",
         "edge_item": "EB-22-2", "condition": "drawers > 0", "qty_formula": "drawers",
         "length_formula": "396", "width_formula": "((H - board_t - 60) / drawers - 3)",
         "edge_formula": "2*(396 + (H - board_t - 60) / drawers - 3)"},
        {"component": "Drawers", "name": "Drawer box", "line_type": "subassembly", "condition": "drawers > 0",
         "child_template": "DRAWER-BOX", "qty_formula": "drawers",
         "child_params": {"W": "360", "D": "D - 160", "H": "100", "board": "board"}},
        {"component": "Hardware", "name": "Bar handle", "line_type": "item", "item": "HDL-BAR-160",
         "condition": "drawers > 0", "qty_formula": "drawers"},
        {"component": "Hardware", "name": "Cable grommet", "line_type": "item", "item": "CBL-GROM",
         "condition": "grommet == 'yes'"},
        {"component": "Hardware", "name": "Glide", "line_type": "item", "item": "GLIDE-20", "qty_formula": "4"},
        {"component": "Hardware", "name": "Confirmat screw", "line_type": "item", "item": "SCR-CONF",
         "qty_formula": "12 + (8 if drawers > 0 else 0)"},
    ])
    _routing(t, [
        ("SAW", "1.2*n_panels + 4", ""),
        ("EDGE", "0.4*edge_m + 0.5*n_panels", ""),
        ("CNC", "1.8*n_panels + (4 if grommet == 'yes' else 0)", ""),
        ("ASM", "20", ""),
        ("PACK", "12", ""),
    ])


def _bookshelf():
    t = _template("BOOKSHELF", "Bookshelf", True, [
        {"name": "W", "label": "Width (mm)", "kind": "number", "default": "900", "min_value": 400, "max_value": 1200},
        {"name": "H", "label": "Height (mm)", "kind": "number", "default": "1800", "min_value": 800, "max_value": 2200},
        {"name": "D", "label": "Depth (mm)", "kind": "number", "default": "300", "min_value": 250, "max_value": 400},
        {"name": "board", "label": "Board", "kind": "item", "item_kind": "board", "default": "MDF-WHT-18",
         "choices": BOARD_CHOICES},
        {"name": "shelves", "label": "Adjustable shelves", "kind": "number", "default": "4", "min_value": 1,
         "max_value": 7},
    ])
    carcass = {"component": "Carcass", "line_type": "panel", "item_param": "board", "edge_item": "EB-22-04"}
    _lines(t, [
        {**carcass, "name": "Side panel", "qty_formula": "2", "length_formula": "H", "width_formula": "D",
         "edge_formula": "H"},
        {**carcass, "name": "Top and bottom", "qty_formula": "2", "length_formula": "W - 2*board_t",
         "width_formula": "D", "edge_formula": "W - 2*board_t"},
        {**carcass, "name": "Shelf", "qty_formula": "shelves", "length_formula": "W - 2*board_t - 2",
         "width_formula": "D - 20", "edge_formula": "W - 2*board_t - 2"},
        {"component": "Carcass", "name": "Back panel", "line_type": "panel", "item": "HDF-WHT-3",
         "length_formula": "W - 10", "width_formula": "H - 10"},
        {"component": "Hardware", "name": "Shelf pin", "line_type": "item", "item": "PIN-SHELF",
         "qty_formula": "4*shelves"},
        {"component": "Hardware", "name": "Glide", "line_type": "item", "item": "GLIDE-20", "qty_formula": "4"},
        {"component": "Hardware", "name": "Confirmat screw", "line_type": "item", "item": "SCR-CONF",
         "qty_formula": "8"},
    ])
    _routing(t, [
        ("SAW", "1.2*n_panels + 3", ""),
        ("EDGE", "0.4*edge_m + 0.5*n_panels", ""),
        ("CNC", "1.5*n_panels", ""),
        ("ASM", "15", ""),
        ("PACK", "8", ""),
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
                      ("HDL-BAR-160", 260), ("HDL-KNOB", 140), ("LEG-100", 600), ("RAIL-25", 60), ("RAIL-SUP", 80), ("CBL-GROM", 40),
                      ("GLIDE-20", 400), ("SCR-CONF", 5200),
                      ("SCR-4x16", 8000), ("PIN-SHELF", 900), ("GLUE-PVA", 35), ("LAC-PU", 68), ("LAC-CLR", 22)]:
        item = Item.objects.get(code=code)
        lot = Lot.objects.create(item=item, code=f"L-{code}-01", received_on=date(2026, 10, 15)) \
            if item.track_lots else None
        receive(item, qty, item.standard_cost, main, lot=lot, reference="OPENING")
    for code, L, W in [("MDF-WHT-18", 1180, 580), ("MDF-WHT-18", 760, 540), ("MDF-WHT-18", 720, 560),
                       ("CHB-OAK-18", 1620, 610), ("HDF-WHT-3", 1300, 780)]:
        item = Item.objects.get(code=code)
        register_offcut(item, L, W, rack, lot=item.lots.first())


SUPPLIERS = [
    # name, TIN, lead days, kinds or item codes it sells, price factor vs standard cost
    ("Addis Board Trading", "0012345671", 5, ("board",), Decimal("1.00")),
    ("Kality Panel Imports", "0023456782", 21, ("board",), Decimal("0.93")),
    ("Merkato Hardware Supply", "0034567893", 3, ("hardware", "consumable", "edgeband"), Decimal("1.00")),
    ("Ethio Paints and Finishes", "0045678904", 7, ("finish", "GLUE-PVA"), Decimal("1.00")),
]
REORDER_LEVELS = {"SLD-450": 40, "HNG-SC-110": 200, "EB-22-04": 400, "LAC-PU": 40, "GLUE-PVA": 10,
                  "MDF-WHT-18": Decimal("29.7680"), "SCR-CONF": 2000}


def load_suppliers():
    """Sample suppliers with pack prices (sample figures, not real quotes) and reorder levels."""
    from apps.purchasing.models import Supplier, SupplierItem

    for code, level in REORDER_LEVELS.items():
        Item.objects.filter(code=code).update(reorder_level=Decimal(str(level)))
    for name, tin, days, sells, factor in SUPPLIERS:
        sup, _ = Supplier.objects.update_or_create(name=name, defaults={"tin": tin, "lead_time_days": days})
        items = Item.objects.filter(models.Q(kind__in=sells) | models.Q(code__in=sells)).prefetch_related("conversions")
        for item in items:
            conv = item.conversions.first()
            pack_name, pack_qty = (conv.name, conv.base_qty) if conv else (item.base_uom.code, Decimal(1))
            SupplierItem.objects.update_or_create(supplier=sup, item=item, defaults={
                "pack_name": pack_name, "pack_qty": pack_qty,
                "price_per_pack": (item.standard_cost * pack_qty * factor).quantize(Decimal("1")),
                "min_packs": 10 if item.kind == "board" and factor < 1 else 1,
                "preferred": factor == 1,
            })


MACHINES = [
    # code, name, work center, make/model, meter hours, [(task, every hours, every days, done hours ago, done days ago)]
    ("SAW-01", "Sliding table panel saw", "SAW", "Sample 3200 mm sliding saw", 4210, [
        ("Change main and scoring blades", 40, None, 38, 6),
        ("Clean and lubricate sliding carriage", None, 7, 30, 8),
    ]),
    ("EDGE-01", "Edgebander", "EDGE", "Sample single-sided edgebander", 3120, [
        ("Clean glue pot and pressure rollers", 30, 7, 12, 3),
        ("Sharpen or replace trimming knives", 120, None, 60, 20),
    ]),
    ("CNC-01", "CNC drilling and routing centre", "CNC", "Sample 3-axis nesting router", 2650, [
        ("Grease spindle and linear guides", 100, None, 97, 15),
        ("Clean vacuum table and check pump filter", None, 14, 40, 5),
    ]),
    ("SPRAY-01", "Spray booth", "SPRAY", "Sample dry-filter booth", 1800, [
        ("Replace booth exhaust filters", None, 14, 50, 13),
    ]),
    ("COMP-01", "Air compressor", None, "Sample 7.5 kW screw compressor", 9100, [
        ("Drain water from tank and dryer", None, 1, 8, 2),
        ("Change compressor oil and oil filter", 2000, 180, 900, 60),
    ]),
]


def load_machines():
    """Sample machines and service plans; some are due now so the maintenance screen has data."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.maintenance.models import Machine, MaintenancePlan

    now = timezone.now()
    for code, name, wc, model, meter, plans in MACHINES:
        m, _ = Machine.objects.update_or_create(code=code, defaults={
            "name": name, "work_center": WorkCenter.objects.filter(code=wc).first() if wc else None,
            "make_model": model, "opening_hours": Decimal(meter), "hours_since": now})
        for task, hours, days, hours_ago, days_ago in plans:
            MaintenancePlan.objects.update_or_create(machine=m, task=task, defaults={
                "every_hours": Decimal(hours) if hours else None, "every_days": days,
                "last_done_hours": Decimal(meter - hours_ago), "last_done_at": now - timedelta(days=days_ago)})


CHECKLISTS = [
    # name, stage, work center, [(text, kind, target, tolerance)]
    ("Panel saw check", "station", "SAW", [
        ("Diagonals equal (difference, mm)", "measure", 0, 1),
        ("No chipping on visible edges", "pass_fail", None, None),
    ]),
    ("Edgebanding check", "station", "EDGE", [
        ("Edge fully bonded, no gaps", "pass_fail", None, None),
        ("Edge trimmed flush, no overhang", "pass_fail", None, None),
        ("No glue squeeze-out on faces", "pass_fail", None, None),
    ]),
    ("CNC drilling check", "station", "CNC", [
        ("System hole distance from front edge (mm)", "measure", 37, "0.5"),
        ("Hinge cup depth (mm)", "measure", 12, "0.5"),
        ("Holes on 32 mm pitch, none missing", "pass_fail", None, None),
    ]),
    ("Final inspection", "final", None, [
        ("Overall size matches the order (W x H x D)", "pass_fail", None, None),
        ("Doors and drawers aligned, gaps even", "pass_fail", None, None),
        ("Hardware complete and working", "pass_fail", None, None),
        ("No scratches, chips or finish defects", "pass_fail", None, None),
        ("Packed with corner protection and label attached", "pass_fail", None, None),
    ]),
]


def load_checklists():
    """Sample station and final inspection checklists (examples to adapt to the factory's standards)."""
    from apps.quality.models import Checklist, ChecklistItem

    for name, stage, wc, items in CHECKLISTS:
        cl, _ = Checklist.objects.update_or_create(name=name, defaults={
            "stage": stage, "work_center": WorkCenter.objects.filter(code=wc).first() if wc else None})
        for seq, (text, kind, target, tol) in enumerate(items, start=1):
            ChecklistItem.objects.update_or_create(checklist=cl, text=text, defaults={
                "sequence": seq * 10, "kind": kind,
                "target": Decimal(str(target)) if target is not None else None,
                "tolerance": Decimal(str(tol)) if tol is not None else None})
