"""Estimated and actual job cost, both broken down the same way so they compare
line by line: material, labour, machine, overhead."""
from decimal import Decimal

from apps.catalog.models import Item
from apps.core.models import CostSettings, WorkCenter
from apps.inventory.models import StockMove
from apps.inventory.services import average_cost

Q = Decimal("0.01")


def _money(x):
    return Decimal(x).quantize(Q)


def _breakdown(material, labour, machine, overhead_pct):
    """Round each part first so the parts always add up to the total shown."""
    material, labour, machine = _money(material), _money(labour), _money(machine)
    overhead = _money((material + labour + machine) * overhead_pct)
    return {
        "material": str(material),
        "labour": str(labour),
        "machine": str(machine),
        "overhead": str(overhead),
        "total": str(material + labour + machine + overhead),
    }


def estimate(exploded):
    """Cost of an ExplodedBOM. Board area is divided by the nesting yield, since
    fresh sheets never nest at 100%."""
    cs = CostSettings.current()
    totals = exploded.material_totals()
    items = {i.code: i for i in Item.objects.filter(code__in=totals)}
    material = Decimal(0)
    lines = []
    for code, qty in totals.items():
        item = items[code]
        needed = qty / cs.nesting_yield if item.kind == Item.Kind.BOARD else qty
        cost = needed * average_cost(item)
        material += cost
        lines.append({"item": code, "qty": str(qty), "with_yield": str(needed.quantize(Decimal("0.0001"))),
                      "cost": str(_money(cost))})

    minutes = exploded.minutes_by_work_center()
    wcs = {w.code: w for w in WorkCenter.objects.filter(code__in=minutes)}
    labour = sum((m / 60 * wcs[c].labour_rate for c, m in minutes.items()), Decimal(0))
    machine = sum((m / 60 * wcs[c].machine_rate for c, m in minutes.items()), Decimal(0))
    return {
        **_breakdown(material, labour, machine, cs.overhead_pct),
        "material_lines": lines,
        "minutes": {k: str(v) for k, v in minutes.items()},
    }


def actual(work_order):
    """Cost booked so far: material issued (less returns and offcuts put back) plus
    scanned time at each work center's rates."""
    cs = CostSettings.current()
    material = Decimal(0)
    for m in StockMove.objects.filter(work_order=work_order):
        if m.kind in (StockMove.Kind.ISSUE, StockMove.Kind.RETURN, StockMove.Kind.OFFCUT):
            material -= m.qty * m.unit_cost
    labour = machine = Decimal(0)
    for op in work_order.operations.select_related("work_center").prefetch_related("time_logs"):
        mins = sum((t.minutes for t in op.time_logs.all()), Decimal(0))
        labour += mins / 60 * op.work_center.labour_rate
        machine += mins / 60 * op.work_center.machine_rate
    return _breakdown(material, labour, machine, cs.overhead_pct)


def variance(work_order):
    est, act = work_order.estimate or {}, actual(work_order)
    keys = ["material", "labour", "machine", "overhead", "total"]
    return {
        k: {"estimate": est.get(k, "0"), "actual": act[k],
            "variance": str(_money(Decimal(act[k]) - Decimal(est.get(k, "0"))))}
        for k in keys
    }
