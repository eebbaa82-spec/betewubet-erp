"""Dispatch: what is finished and not yet shipped, delivery notes, proof of delivery, installation.

Ready to ship for an order line = quantity on its finished work orders (rework orders not
counted twice) minus what is already on live delivery notes."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.sales.models import SalesOrder

from .models import Delivery, DeliveryLine, Installation

LIVE = (Delivery.Status.PLANNED, Delivery.Status.OUT, Delivery.Status.DELIVERED)


def _finished(line):
    return list(line.work_orders.filter(status="done", rework_of__isnull=True))


def made_qty(line):
    """Finished and, where a final checklist is in use, passed final inspection."""
    from apps.quality.services import passed_final

    return sum((wo.quantity for wo in _finished(line) if passed_final(wo)), Decimal(0))


def awaiting_inspection_qty(line):
    from apps.quality.services import passed_final

    return sum((wo.quantity for wo in _finished(line) if not passed_final(wo)), Decimal(0))


def shipped_qty(line, exclude_delivery=None):
    qs = line.delivery_lines.filter(delivery__status__in=LIVE)
    if exclude_delivery is not None:
        qs = qs.exclude(delivery=exclude_delivery)
    return qs.aggregate(t=Sum("quantity"))["t"] or Decimal(0)


def _q(v):
    return str(Decimal(v).quantize(Decimal("0.01")))


def line_status(line):
    made, shipped = made_qty(line), shipped_qty(line)
    return {"line": line.id, "sequence": line.sequence, "product": line.template.name,
            "description": line.description, "configuration": line.configuration,
            "ordered": _q(line.quantity), "made": _q(made), "shipped": _q(shipped),
            "awaiting_inspection": _q(awaiting_inspection_qty(line)),
            "ready": _q(max(made - shipped, Decimal(0)))}


def ready_to_ship():
    orders = SalesOrder.objects.exclude(status__in=["quote", "cancelled"]).filter(
        lines__work_orders__status="done").distinct().select_related("customer")
    out = []
    for o in orders:
        lines = [line_status(l) for l in o.lines.select_related("template")]
        if any(Decimal(l["ready"]) > 0 or Decimal(l["awaiting_inspection"]) > 0 for l in lines):
            out.append({"order": o.id, "number": o.number, "customer": o.customer.name,
                        "address": o.site_address or o.customer.address, "phone": o.customer.phone,
                        "due_date": o.due_date, "lines": lines})
    return out


@transaction.atomic
def create_delivery(order, lines, scheduled_date, user=None, **fields):
    """``lines`` is a list of (SalesOrderLine, quantity)."""
    lines = [(l, Decimal(q)) for l, q in lines if Decimal(q) > 0]
    if not lines:
        raise ValidationError("Choose at least one item to deliver.")
    for line, qty in lines:
        if line.order_id != order.id:
            raise ValidationError(f"Line {line.sequence} is not on {order.number}.")
        ready = made_qty(line) - shipped_qty(line)
        if qty > ready:
            waiting = awaiting_inspection_qty(line)
            extra = f" {waiting:g} more are waiting for final inspection." if waiting else ""
            raise ValidationError(f"Only {ready:g} of {line.template.name} (line {line.sequence}) are finished and not yet shipped.{extra}")
    fields.setdefault("address", order.site_address or order.customer.address)
    fields.setdefault("contact_phone", order.customer.phone)
    d = Delivery.objects.create(order=order, scheduled_date=scheduled_date, created_by=user, **fields)
    DeliveryLine.objects.bulk_create([DeliveryLine(delivery=d, sales_line=l, quantity=q) for l, q in lines])
    return d


def _move(d, allowed, to):
    if d.status not in allowed:
        raise ValidationError(f"{d.number} is {d.get_status_display().lower()}.")
    d.status = to


def _update_order(order):
    """Dispatched once everything ordered has left the factory; installed once it is all
    delivered and no installation visit is still outstanding."""
    lines = list(order.lines.all())
    if not lines or any(shipped_qty(l) < l.quantity for l in lines):
        return
    live = order.deliveries.filter(status__in=LIVE)
    new = SalesOrder.Status.DISPATCHED
    if live.filter(install_required=True).exists() and not live.exclude(status=Delivery.Status.DELIVERED).exists() \
            and not Installation.objects.filter(delivery__order=order, status=Installation.Status.SCHEDULED).exists():
        new = SalesOrder.Status.INSTALLED
    if order.status != new:
        order.status = new
        order.save(update_fields=["status"])


@transaction.atomic
def dispatch(d):
    _move(d, [Delivery.Status.PLANNED], Delivery.Status.OUT)
    d.dispatched_at = timezone.now()
    d.save(update_fields=["status", "dispatched_at"])
    _update_order(d.order)
    return d


@transaction.atomic
def deliver(d, received_by, install_date=None, crew=""):
    if not received_by.strip():
        raise ValidationError("Enter the name of the person who received the goods.")
    _move(d, [Delivery.Status.OUT], Delivery.Status.DELIVERED)
    d.delivered_at, d.received_by = timezone.now(), received_by.strip()
    d.save(update_fields=["status", "delivered_at", "received_by"])
    if d.install_required:
        Installation.objects.create(delivery=d, crew=crew,
                                    scheduled_date=install_date or timezone.localdate() + timedelta(days=1))
    _update_order(d.order)
    return d


@transaction.atomic
def cancel(d):
    _move(d, [Delivery.Status.PLANNED], Delivery.Status.CANCELLED)
    d.save(update_fields=["status"])
    return d


@transaction.atomic
def complete_installation(job, signed_off_by, snags="", notes="", return_date=None):
    if job.status != Installation.Status.SCHEDULED:
        raise ValidationError(f"{job.number} is already {job.get_status_display().lower()}.")
    if not signed_off_by.strip():
        raise ValidationError("Enter the name of the customer's person who signed off.")
    job.completed_at, job.signed_off_by = timezone.now(), signed_off_by.strip()
    job.snags, job.notes = snags.strip(), notes
    job.status = Installation.Status.SNAGS if job.snags else Installation.Status.DONE
    job.save()
    follow_up = None
    if job.snags:
        follow_up = Installation.objects.create(
            delivery=job.delivery, crew=job.crew, return_visit_of=job, notes=f"Return visit for: {job.snags}",
            scheduled_date=return_date or timezone.localdate() + timedelta(days=2))
    _update_order(job.delivery.order)
    return job, follow_up
