"""Purchasing: what we are short of, draft orders for it, and receiving against orders.

Shortage for an item = what open work orders still need
                       + the item's reorder level
                       - what is in stock (offcut racks not counted)
                       - what is already on open purchase orders.
"""
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import Item
from apps.core.models import CostSettings
from apps.inventory.models import Lot, StockMove
from apps.inventory.services import receive

from .models import PurchaseOrder, PurchaseOrderLine, SupplierItem

Q4 = Decimal("0.0001")
OPEN_WO = ("planned", "released", "in_progress")


def _sums(qs, key, value):
    return {r[key]: r["t"] or Decimal(0) for r in qs.values(key).annotate(t=Sum(value))}


def requirements():
    """Base-unit quantity each item still needs for open work orders (planned minus issued)."""
    from apps.production.models import WorkOrderMaterial

    planned = _sums(WorkOrderMaterial.objects.filter(work_order__status__in=OPEN_WO), "item_id", "planned_qty")
    used = _sums(StockMove.objects.filter(work_order__status__in=OPEN_WO,
                                          kind__in=[StockMove.Kind.ISSUE, StockMove.Kind.RETURN]), "item_id", "qty")
    # Issues are negative in the ledger, returns positive, so planned + net moves is what is left to issue.
    return {i: max(q + used.get(i, Decimal(0)), Decimal(0)) for i, q in planned.items()}


def on_order():
    out = defaultdict(Decimal)
    for ln in PurchaseOrderLine.objects.filter(order__status__in=PurchaseOrder.OPEN):
        out[ln.item_id] += ln.open_packs * ln.pack_qty
    return out


def best_source(item):
    return item.supplier_items.select_related("supplier").filter(supplier__active=True) \
        .order_by("-preferred", "price_per_pack").first()


def shortages():
    need = requirements()
    ordered = on_order()
    stock = _sums(StockMove.objects.exclude(location__is_offcut_rack=True), "item_id", "qty")
    items = Item.objects.filter(active=True).select_related("base_uom").order_by("kind", "code")
    rows = []
    for item in items:
        required = need.get(item.id, Decimal(0))
        reorder = item.reorder_level or Decimal(0)
        if not required and not item.reorder_level:
            continue
        in_stock = stock.get(item.id, Decimal(0))
        incoming = ordered.get(item.id, Decimal(0))
        short = required + reorder - in_stock - incoming
        if short <= 0:
            continue
        src = best_source(item)
        packs = None
        if src:
            packs = max(math.ceil(short / src.pack_qty), src.min_packs)
        rows.append({
            "item": item.code, "item_name": item.name, "kind": item.kind, "uom": item.base_uom.code,
            "required": str(required.quantize(Q4)), "reorder_level": str(reorder.quantize(Q4)),
            "in_stock": str(in_stock.quantize(Q4)), "on_order": str(incoming.quantize(Q4)),
            "short": str(short.quantize(Q4)),
            "supplier": src.supplier.name if src else None, "supplier_id": src.supplier_id if src else None,
            "pack_name": src.pack_name if src else None, "pack_qty": str(src.pack_qty) if src else None,
            "suggested_packs": packs,
            "price_per_pack": str(src.price_per_pack) if src else None,
            "amount": str((src.price_per_pack * packs).quantize(Decimal("0.01"))) if src else None,
        })
    return rows


@transaction.atomic
def draft_orders(user=None, items=None):
    """One draft purchase order per supplier for the current shortages.

    ``items`` limits it to those item codes. Items with no supplier are skipped."""
    by_supplier = defaultdict(list)
    for row in shortages():
        if row["supplier_id"] and (items is None or row["item"] in items):
            by_supplier[row["supplier_id"]].append(row)
    today = timezone.localdate()
    orders = []
    for supplier_id, rows in by_supplier.items():
        src0 = SupplierItem.objects.select_related("supplier").get(supplier_id=supplier_id, item__code=rows[0]["item"])
        po = PurchaseOrder.objects.create(
            supplier_id=supplier_id, order_date=today, created_by=user,
            expected_date=today + timedelta(days=src0.supplier.lead_time_days),
            notes="Drafted from shortages.")
        for r in rows:
            src = SupplierItem.objects.get(supplier_id=supplier_id, item__code=r["item"])
            PurchaseOrderLine.objects.create(
                order=po, item=src.item, pack_name=src.pack_name, pack_qty=src.pack_qty,
                packs=r["suggested_packs"], price_per_pack=src.price_per_pack)
        orders.append(po)
    return orders


def totals(po):
    vat_rate = CostSettings.current().vat_rate if po.supplier.vat_registered else Decimal(0)
    subtotal = sum((ln.amount for ln in po.lines.all()), Decimal(0))
    vat = (subtotal * vat_rate).quantize(Decimal("0.01"))
    return {"subtotal": str(subtotal), "vat_rate": str(vat_rate), "vat": str(vat), "total": str(subtotal + vat)}


@transaction.atomic
def receive_line(line, packs, location, lot_code="", colour_ref="", supplier_batch="", user=None):
    """Book goods received against a PO line into stock at the PO price."""
    po = PurchaseOrder.objects.select_for_update().get(pk=line.order_id)
    line.refresh_from_db()
    packs = Decimal(packs)
    if po.status not in (PurchaseOrder.Status.SENT, PurchaseOrder.Status.PARTIAL):
        raise ValidationError(f"{po.number} is {po.get_status_display().lower()}; only sent orders can be received.")
    if packs <= 0:
        raise ValidationError("Received quantity must be more than zero.")
    if packs > line.open_packs:
        raise ValidationError(f"Only {line.open_packs} {line.pack_name} of {line.item.code} are still open on {po.number}.")
    item = line.item
    lot = None
    if item.track_lots:
        if not lot_code:
            raise ValidationError(f"{item.code} is lot-tracked; enter the lot or batch.")
        lot, _ = Lot.objects.get_or_create(item=item, code=lot_code, defaults={
            "supplier_batch": supplier_batch, "colour_ref": colour_ref, "received_on": timezone.localdate()})
    move = receive(item, (packs * line.pack_qty).quantize(Q4), line.unit_cost, location, lot=lot,
                   reference=po.number, user=user)
    line.received_packs += packs
    line.save(update_fields=["received_packs"])
    lines = list(po.lines.all())
    po.status = PurchaseOrder.Status.RECEIVED if all(ln.open_packs == 0 for ln in lines) else PurchaseOrder.Status.PARTIAL
    po.save(update_fields=["status"])
    return move
