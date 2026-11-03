from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.explode import explode
from apps.core.models import CostSettings
from apps.production import costing
from apps.production.services import create_work_order

from .models import SalesOrder

Q = Decimal("0.01")


def price_line(line, margin=None):
    """Estimate one unit of the configured product and set the price from the margin."""
    cs = CostSettings.current()
    if margin is None:
        margin = line.order.target_margin if line.order.target_margin is not None else cs.default_margin
    margin = Decimal(margin)
    if not (0 <= margin < 1):
        raise ValidationError("Margin must be between 0 and 0.99.")
    result = explode(line.template, line.configuration, qty=1)
    est = costing.estimate(result)
    line.configuration = result.params
    line.estimate = est
    line.estimated_unit_cost = Decimal(est["total"])
    if not line.price_locked:
        line.unit_price = (line.estimated_unit_cost / (1 - margin)).quantize(Q)
    line.save()
    return line


def totals(order):
    cs = CostSettings.current()
    subtotal = order.subtotal
    vat = (subtotal * cs.vat_rate).quantize(Q)
    cost = order.estimated_cost
    return {
        "subtotal": str(subtotal),
        "vat_rate": str(cs.vat_rate),
        "vat": str(vat),
        "total": str(subtotal + vat),
        "estimated_cost": str(cost),
        "estimated_margin_pct": str(((subtotal - cost) / subtotal * 100).quantize(Q)) if subtotal else "0",
    }


@transaction.atomic
def confirm(order):
    """Quote -> confirmed order: re-price unlocked lines, then release one work order per line."""
    if order.status != SalesOrder.Status.QUOTE:
        raise ValidationError(f"{order.number} is already {order.get_status_display().lower()}.")
    if not order.lines.exists():
        raise ValidationError("Add at least one line before confirming.")
    work_orders = []
    for line in order.lines.select_related("template"):
        price_line(line)
        work_orders.append(create_work_order(line.template, line.configuration, line.quantity,
                                             sales_line=line, due_date=order.due_date))
    order.status = SalesOrder.Status.CONFIRMED
    order.save(update_fields=["status"])
    return work_orders
