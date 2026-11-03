"""Machine hours, what service is due, and breakdowns.

Running hours = opening meter hours + time logged at the machine's station since it was set up.
A plan is due when the hours or the days since it was last done reach its interval, and
"due soon" from 90% of the interval."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.production.models import TimeLog

from .models import Machine, MaintenanceLog, MaintenancePlan

SOON = Decimal("0.9")


def machine_hours(machine, now=None):
    now = now or timezone.now()
    total = Decimal(0)
    if machine.work_center_id:
        for log in TimeLog.objects.filter(operation__work_center_id=machine.work_center_id,
                                          started_at__gte=machine.hours_since):
            end = log.ended_at or now
            total += Decimal((end - log.started_at).total_seconds()) / Decimal(3600)
    return (machine.opening_hours + total).quantize(Decimal("0.1"))


def plan_status(plan, hours=None, now=None):
    now = now or timezone.now()
    hours = machine_hours(plan.machine, now) if hours is None else hours
    used_h = hours - plan.last_done_hours
    used_d = Decimal((now - plan.last_done_at).total_seconds()) / Decimal(86400)
    fractions = []
    if plan.every_hours:
        fractions.append(used_h / plan.every_hours)
    if plan.every_days:
        fractions.append(used_d / plan.every_days)
    worst = max(fractions) if fractions else Decimal(0)
    state = "overdue" if worst >= 1 else "soon" if worst >= SOON else "ok"
    due_hours = plan.last_done_hours + plan.every_hours if plan.every_hours else None
    due_date = (plan.last_done_at + timedelta(days=plan.every_days)).date() if plan.every_days else None
    return {
        "id": plan.id, "machine": plan.machine.code, "machine_name": plan.machine.name, "task": plan.task,
        "instructions": plan.instructions,
        "every_hours": str(plan.every_hours) if plan.every_hours else None, "every_days": plan.every_days,
        "last_done_at": plan.last_done_at, "last_done_hours": str(plan.last_done_hours),
        "hours_now": str(hours), "hours_left": str((due_hours - hours).quantize(Decimal("0.1"))) if due_hours else None,
        "due_date": due_date, "used": str(worst.quantize(Decimal("0.01"))), "state": state,
    }


def due_list(now=None):
    now = now or timezone.now()
    hours = {}
    rows = []
    for plan in MaintenancePlan.objects.filter(active=True, machine__active=True).select_related("machine"):
        if plan.machine_id not in hours:
            hours[plan.machine_id] = machine_hours(plan.machine, now)
        rows.append(plan_status(plan, hours[plan.machine_id], now))
    order = {"overdue": 0, "soon": 1, "ok": 2}
    return sorted(rows, key=lambda r: (order[r["state"]], -Decimal(r["used"])))


@transaction.atomic
def complete_plan(plan, done_by="", notes="", parts_cost=0, user=None, now=None):
    now = now or timezone.now()
    hours = machine_hours(plan.machine, now)
    log = MaintenanceLog.objects.create(
        machine=plan.machine, plan=plan, kind=MaintenanceLog.Kind.PREVENTIVE, description=plan.task,
        reported_at=now, reported_by=user, closed_at=now, action_taken=notes, done_by=done_by,
        parts_cost=Decimal(parts_cost or 0), machine_hours=hours)
    plan.last_done_at, plan.last_done_hours = now, hours
    plan.save(update_fields=["last_done_at", "last_done_hours"])
    return log


def report_breakdown(machine, description, machine_down=True, user=None):
    return MaintenanceLog.objects.create(
        machine=machine, kind=MaintenanceLog.Kind.BREAKDOWN, description=description, machine_down=machine_down,
        reported_by=user, machine_hours=machine_hours(machine))


def close_log(log, action_taken="", done_by="", parts_cost=0):
    if not log.is_open:
        raise ValidationError("This record is already closed.")
    log.closed_at = timezone.now()
    log.action_taken, log.done_by, log.parts_cost = action_taken, done_by, Decimal(parts_cost or 0)
    log.save(update_fields=["closed_at", "action_taken", "done_by", "parts_cost"])
    return log


def down_reason(work_center):
    """If every active machine at this station has an open breakdown that stops it, say which."""
    machines = list(Machine.objects.filter(work_center=work_center, active=True))
    if not machines:
        return None
    open_down = {l.machine_id: l for l in MaintenanceLog.objects.filter(
        machine__in=machines, machine_down=True, closed_at__isnull=True).order_by("reported_at")}
    if len(open_down) < len(machines):
        return None
    first = min(open_down.values(), key=lambda l: l.reported_at)
    return f"{work_center.code} is down: {first.description} (reported {timezone.localtime(first.reported_at):%d %b %H:%M})."


def downtime_hours(machine, days=30, now=None):
    now = now or timezone.now()
    since = now - timedelta(days=days)
    total = Decimal(0)
    for log in machine.logs.filter(machine_down=True).exclude(closed_at__lt=since):
        start = max(log.reported_at, since)
        end = log.closed_at or now
        total += Decimal((end - start).total_seconds()) / Decimal(3600)
    return total.quantize(Decimal("0.1"))
