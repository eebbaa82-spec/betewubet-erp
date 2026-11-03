from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Sum

from .models import Offcut, StockMove


def on_hand(item, location=None, lot=None):
    qs = StockMove.objects.filter(item=item)
    if location is not None:
        qs = qs.filter(location=location)
    if lot is not None:
        qs = qs.filter(lot=lot)
    return qs.aggregate(t=Sum("qty"))["t"] or Decimal("0")


def average_cost(item):
    """Weighted average cost of receipts, falling back to the item's standard cost."""
    agg = StockMove.objects.filter(item=item, kind=StockMove.Kind.RECEIPT, qty__gt=0).aggregate(
        q=Sum("qty"), v=Sum(F("qty") * F("unit_cost"), output_field=DecimalField(max_digits=20, decimal_places=6))
    )
    if not agg["q"]:
        return item.standard_cost
    return (agg["v"] / agg["q"]).quantize(Decimal("0.0001"))


@transaction.atomic
def receive(item, qty, unit_cost, location, lot=None, reference="", user=None):
    if Decimal(qty) <= 0:
        raise ValidationError("Receipt quantity must be positive.")
    return StockMove.objects.create(
        item=item, lot=lot, location=location, kind=StockMove.Kind.RECEIPT,
        qty=Decimal(qty), unit_cost=Decimal(unit_cost), reference=reference, created_by=user,
    )


@transaction.atomic
def issue(item, qty, location, work_order=None, lot=None, user=None, allow_negative=False):
    qty = Decimal(qty)
    if qty <= 0:
        raise ValidationError("Issue quantity must be positive.")
    available = on_hand(item, location, lot)
    if not allow_negative and available < qty:
        raise ValidationError(f"Only {available} {item.base_uom} of {item.code} at {location}.")
    return StockMove.objects.create(
        item=item, lot=lot, location=location, kind=StockMove.Kind.ISSUE, qty=-qty,
        unit_cost=average_cost(item), work_order=work_order, created_by=user,
    )


def next_offcut_code():
    last = Offcut.objects.order_by("-id").values_list("code", flat=True).first()
    n = int(last.split("-")[1]) + 1 if last else 1
    return f"OC-{n:05d}"


@transaction.atomic
def register_offcut(item, length_mm, width_mm, location, lot=None, work_order=None, user=None):
    """Put a leftover piece back into stock. Pieces under the minimum size are refused."""
    minimum = settings.ERP["MIN_OFFCUT_MM"]
    if min(length_mm, width_mm) < minimum:
        raise ValidationError(f"Pieces smaller than {minimum} x {minimum} mm are scrap, not offcuts.")
    offcut = Offcut.objects.create(
        code=next_offcut_code(), item=item, lot=lot, length_mm=length_mm, width_mm=width_mm,
        location=location, source_work_order=work_order,
    )
    StockMove.objects.create(
        item=item, lot=lot, location=location, kind=StockMove.Kind.OFFCUT,
        qty=offcut.area_m2, unit_cost=average_cost(item), work_order=work_order,
        reference=offcut.code, created_by=user,
    )
    return offcut


def match_offcuts(panels, reserve_for=None):
    """Assign available offcuts to panels, largest panel first, smallest fitting offcut.

    ``panels`` is a list of catalog.explode.PanelLine. Returns a list of
    (panel_index, offcut) pairs, one per piece taken from an offcut. With
    ``reserve_for`` (a WorkOrder) the offcuts are marked reserved for it."""
    pieces = []
    for idx, p in enumerate(panels):
        for _ in range(int(p.qty)):
            pieces.append((idx, p))
    pieces.sort(key=lambda t: t[1].length_mm * t[1].width_mm, reverse=True)

    codes = {p.item_code for p in panels}
    pool = list(Offcut.objects.filter(item__code__in=codes, status=Offcut.Status.AVAILABLE).select_related("item"))
    pool.sort(key=lambda o: o.length_mm * o.width_mm)
    taken, matches = set(), []
    for idx, p in pieces:
        for o in pool:
            if o.id in taken or o.item.code != p.item_code:
                continue
            if o.fits(p.length_mm, p.width_mm, p.grain_locked):
                taken.add(o.id)
                matches.append((idx, o))
                break
    if reserve_for is not None:
        Offcut.objects.filter(id__in=taken).update(status=Offcut.Status.RESERVED, reserved_for=reserve_for)
    return matches
