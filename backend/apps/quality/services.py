"""Inspections against checklists. A failed inspection with a failed quantity opens a
non-conformance and a rework order, the same as a reject at a station. Where a final
checklist is active, a job must pass final inspection before it can be put on a delivery note."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.production.services import report_reject

from .models import Checklist, ChecklistItem, Inspection, InspectionResult


def final_checklist():
    return Checklist.objects.filter(stage=Checklist.Stage.FINAL, active=True).first()


def passed_final(work_order):
    if final_checklist() is None:
        return True
    return work_order.inspections.filter(checklist__stage=Checklist.Stage.FINAL, result=Inspection.Result.PASS).exists()


def judge(item, passed=None, value=None):
    if item.kind == ChecklistItem.Kind.MEASURE:
        if value in (None, ""):
            raise ValidationError(f"Enter the measurement for “{item.text}”.")
        value = Decimal(str(value))
        if item.target is None:
            return True if passed is None else bool(passed), value
        return abs(value - item.target) <= (item.tolerance or Decimal(0)), value
    if passed is None:
        raise ValidationError(f"Mark “{item.text}” as passed or failed.")
    return bool(passed), None


@transaction.atomic
def record(work_order, checklist, answers, operation=None, failed_qty=0, notes="", user=None):
    """``answers`` maps item id -> {"passed": bool|None, "value": number|None, "note": str}."""
    if operation is not None and operation.work_order_id != work_order.id:
        raise ValidationError("That step is not on this work order.")
    if checklist.stage == Checklist.Stage.STATION and operation is None:
        operation = work_order.operations.filter(work_center=checklist.work_center).order_by("sequence").first()
    items = list(checklist.items.all())
    missing = [i.text for i in items if i.id not in answers]
    if missing:
        raise ValidationError(f"Answer every check; missing “{missing[0]}”.")
    judged = [(i, *judge(i, answers[i.id].get("passed"), answers[i.id].get("value"))) for i in items]
    ok = all(p for _, p, _ in judged)
    failed_qty = Decimal(failed_qty or 0)
    if ok and failed_qty:
        raise ValidationError("Every check passed, so there is no failed quantity.")
    if not ok and failed_qty > work_order.quantity:
        raise ValidationError(f"The job is for {work_order.quantity:g}; failed quantity cannot be more.")
    insp = Inspection.objects.create(
        work_order=work_order, operation=operation, checklist=checklist, inspector=user, notes=notes,
        result=Inspection.Result.PASS if ok else Inspection.Result.FAIL, failed_qty=failed_qty)
    InspectionResult.objects.bulk_create([
        InspectionResult(inspection=insp, item=i, passed=p, value=v, note=answers[i.id].get("note", "")[:160])
        for i, p, v in judged])
    if not ok and failed_qty > 0:
        at = operation or work_order.operations.order_by("-sequence").first()
        failed = "; ".join(i.text for i, p, _ in judged if not p)
        insp.non_conformance = report_reject(at, failed_qty, f"{checklist.name}: {failed}"[:120], user)
        insp.save(update_fields=["non_conformance"])
    return insp
