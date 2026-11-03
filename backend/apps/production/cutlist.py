"""Cut list for a work order: every panel to cut, grouped by board, with a part ID per line.

The part ID (``WO-000001-P03``) goes on the panel label as a QR code so the part can be
found again at edgebanding, drilling, assembly and packing. The CSV is a plain layout
that most nesting programs can import (part, material, length, width, qty, grain).
"""
import csv
import io
import math
from decimal import Decimal

from apps.catalog.models import Item
from apps.core.models import CostSettings

CSV_COLUMNS = ["part_id", "material", "length_mm", "width_mm", "qty", "grain_locked",
               "edge_item", "edge_mm_per_piece", "name", "path", "work_order"]


def part_id(wo, n):
    return f"{wo.number}-P{n:02d}"


def cut_list(wo):
    panels = wo.exploded.get("panels", [])
    items = Item.objects.in_bulk({p["item_code"] for p in panels} | {p["edge_item_code"] for p in panels if p.get("edge_item_code")},
                                 field_name="code")
    nest_yield = CostSettings.current().nesting_yield
    line = getattr(wo, "sales_line", None)

    groups = {}
    for n, p in enumerate(panels, start=1):
        qty = Decimal(p["qty"])
        edge_m = Decimal(p.get("edge_m") or 0)
        board = items.get(p["item_code"])
        edge = items.get(p.get("edge_item_code") or "")
        g = groups.setdefault(p["item_code"], {
            "item": p["item_code"], "item_name": board.name if board else p["item_code"],
            "thickness_mm": board.thickness_mm if board else None,
            "sheet": f"{board.sheet_length_mm} x {board.sheet_width_mm}" if board and board.sheet_length_mm else "",
            "pieces": 0, "area_m2": Decimal(0), "parts": [],
        })
        area = Decimal(p["length_mm"]) * Decimal(p["width_mm"]) * qty / Decimal(1_000_000)
        g["pieces"] += int(qty)
        g["area_m2"] += area
        g["parts"].append({
            "part_id": part_id(wo, n), "name": p["name"], "path": p["path"],
            "length_mm": p["length_mm"], "width_mm": p["width_mm"], "qty": int(qty),
            "grain_locked": bool(p.get("grain_locked")),
            "edge_item": p.get("edge_item_code") or "", "edge_name": edge.name if edge else "",
            "edge_mm_per_piece": str(round(edge_m * 1000 / qty)) if qty and edge_m else "0",
        })

    materials = []
    for g in sorted(groups.values(), key=lambda g: g["item"]):
        board = items.get(g["item"])
        sheet_m2 = board.sheet_area_m2 if board else None
        g["sheets_estimate"] = math.ceil(g["area_m2"] / (sheet_m2 * nest_yield)) if sheet_m2 else None
        g["area_m2"] = str(g["area_m2"].quantize(Decimal("0.0001")))
        g["parts"].sort(key=lambda r: (-Decimal(r["length_mm"]), -Decimal(r["width_mm"])))
        materials.append(g)

    return {
        "work_order": wo.number, "product": wo.template.name, "quantity": str(wo.quantity),
        "order_number": line.order.number if line else "", "customer": line.order.customer.name if line else "",
        "due_date": wo.due_date, "nesting_yield": str(nest_yield),
        "total_pieces": sum(g["pieces"] for g in materials), "materials": materials,
    }


def to_csv(cl):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for g in cl["materials"]:
        for r in g["parts"]:
            w.writerow([r["part_id"], g["item"], r["length_mm"], r["width_mm"], r["qty"],
                        "yes" if r["grain_locked"] else "no", r["edge_item"], r["edge_mm_per_piece"],
                        r["name"], r["path"], cl["work_order"]])
    return out.getvalue()
