from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.explode import explode
from apps.catalog.models import Item, ProductTemplate
from apps.core.models import WorkCenter

from . import costing
from .models import NonConformance, TimeLog, WorkOrder, WorkOrderMaterial, WorkOrderOperation


@transaction.atomic
def create_work_order(template, configuration, quantity, sales_line=None, due_date=None):
    """Explode the configuration, freeze it on a new work order with planned
    materials and operations, and store the cost estimate."""
    if isinstance(template, str):
        template = ProductTemplate.objects.get(code=template)
    result = explode(template, configuration, qty=quantity)
    wo = WorkOrder.objects.create(
        template=template,
        configuration=result.params, quantity=quantity, sales_line=sales_line, due_date=due_date,
        exploded=result.to_dict(), estimate=costing.estimate(result),
    )
    items = {i.code: i for i in Item.objects.filter(code__in=result.material_totals())}
    WorkOrderMaterial.objects.bulk_create([
        WorkOrderMaterial(work_order=wo, item=items[c], planned_qty=q) for c, q in result.material_totals().items()
    ])
    wcs = {w.code: w for w in WorkCenter.objects.all()}
    merged = {}
    for op in result.operations:
        key = (op.path, op.work_center_code, op.description)
        merged[key] = merged.get(key, 0) + op.minutes
    WorkOrderOperation.objects.bulk_create([
        WorkOrderOperation(work_order=wo, sequence=(i + 1) * 10, work_center=wcs[wc],
                           description=f"{path}: {desc}", planned_minutes=mins)
        for i, ((path, wc, desc), mins) in enumerate(merged.items())
    ])
    return wo


@transaction.atomic
def start_operation(operation, operator=None):
    if operation.time_logs.filter(ended_at__isnull=True).exists():
        return operation.time_logs.get(ended_at__isnull=True)
    operation.status = WorkOrderOperation.Status.RUNNING
    operation.save(update_fields=["status"])
    wo = operation.work_order
    if wo.status in (WorkOrder.Status.PLANNED, WorkOrder.Status.RELEASED):
        wo.status = WorkOrder.Status.IN_PROGRESS
        wo.save(update_fields=["status"])
    return TimeLog.objects.create(operation=operation, operator=operator, started_at=timezone.now())


@transaction.atomic
def stop_operation(operation, good_qty=0, rejected_qty=0, reject_reason="", finished=False, operator=None):
    """Close the running time log. Rejected parts open a non-conformance and a rework order."""
    log = operation.time_logs.filter(ended_at__isnull=True).first()
    if log:
        log.ended_at = timezone.now()
        log.good_qty, log.rejected_qty, log.reject_reason = good_qty, rejected_qty, reject_reason
        log.save()
    if rejected_qty and Decimal(rejected_qty) > 0:
        report_reject(operation, Decimal(rejected_qty), reject_reason or "Not stated", operator)
    operation.status = WorkOrderOperation.Status.DONE if finished else WorkOrderOperation.Status.PAUSED
    operation.save(update_fields=["status"])
    wo = operation.work_order
    if finished and not wo.operations.exclude(status=WorkOrderOperation.Status.DONE).exists():
        wo.status = WorkOrder.Status.DONE
        wo.save(update_fields=["status"])
    return log


def report_reject(operation, qty, reason, operator=None):
    """Open a non-conformance and a single-purpose rework work order that redoes the
    rejected quantity at the station where the defect was found."""
    wo = operation.work_order
    per_unit = operation.planned_minutes / wo.quantity if wo.quantity else operation.planned_minutes
    rework = WorkOrder.objects.create(
        template=wo.template, configuration=wo.configuration, quantity=qty, sales_line=wo.sales_line,
        due_date=wo.due_date, rework_of=wo, status=WorkOrder.Status.RELEASED,
        exploded={"rework_of": wo.number, "reason": reason},
    )
    WorkOrderOperation.objects.create(
        work_order=rework, sequence=10, work_center=operation.work_center,
        description=f"Rework for {wo.number}: {reason}", planned_minutes=(per_unit * qty).quantize(Decimal("0.01")),
    )
    return NonConformance.objects.create(
        work_order=wo, operation=operation, qty=qty, reason=reason, reported_by=operator, rework_order=rework,
    )
