"""Station scanning. A panel label's QR holds ``WO-000001-P03-2`` (part 3, piece 2); a job
label holds ``WO-000001``. Scanning at a station starts that job's step there if it is not
running, and records which piece passed the step."""
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from . import services
from .cutlist import part_id as make_part_id
from .models import PartScan, WorkOrder, WorkOrderOperation

CODE = re.compile(r"^(WO-\d+)(?:-P(\d+)(?:[-/](\d+))?)?$")


def parse(code):
    m = CODE.match(code.strip().upper())
    if not m:
        raise ValidationError(f"“{code}” is not a job or panel label.")
    wo, part, piece = m.groups()
    return wo, int(part) if part else None, int(piece) if piece else None


def op_path(op):
    return op.description.split(": ", 1)[0]


def owning_operation(ops, panel_path, top_path):
    """The step a panel belongs to: the sub-assembly whose path the panel path starts with,
    otherwise the top-level product's step."""
    best = None
    for op in ops:
        p = op_path(op)
        if panel_path == p or panel_path.startswith(p + " > "):
            if best is None or len(p) > len(op_path(best)):
                best = op
    return best or next((op for op in ops if op_path(op) == top_path), None) or (ops[0] if ops else None)


def pieces_for(op):
    """Total panel pieces that pass this step, by part number."""
    wo = op.work_order
    same_wc = [o for o in wo.operations.all() if o.work_center_id == op.work_center_id]
    out = {}
    for n, p in enumerate(wo.exploded.get("panels", []), start=1):
        if owning_operation(same_wc, p["path"], wo.template.name) == op:
            out[n] = int(float(p["qty"]))
    return out


@transaction.atomic
def scan(work_center, code, user=None):
    number, part_no, piece = parse(code)
    wo = WorkOrder.objects.select_related("template").filter(number=number).first()
    if wo is None:
        raise ValidationError(f"No job {number}. Check the label and scan again.")
    if wo.status in (WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED):
        raise ValidationError(f"{number} is {wo.get_status_display().lower()}.")
    here = list(wo.operations.filter(work_center=work_center).select_related("work_center"))
    if not here:
        nxt = wo.operations.exclude(status=WorkOrderOperation.Status.DONE).select_related("work_center").first()
        where = f" Its next open step is at {nxt.work_center.code}." if nxt else ""
        raise ValidationError(f"{number} has no step at {work_center.code}.{where}")

    panel = None
    if part_no is not None:
        panels = wo.exploded.get("panels", [])
        if not 1 <= part_no <= len(panels):
            raise ValidationError(f"{number} has no part P{part_no:02d}.")
        panel = panels[part_no - 1]
        op = owning_operation(here, panel["path"], wo.template.name)
    else:
        op = next((o for o in here if o.status != WorkOrderOperation.Status.DONE), here[0])
    if op.status == WorkOrderOperation.Status.DONE:
        raise ValidationError(f"{number}: the {work_center.code} step ({op_path(op)}) is already finished.")

    started, switched_from = False, None
    if op.status != WorkOrderOperation.Status.RUNNING:
        from apps.maintenance.services import down_reason
        down = down_reason(work_center)
        if down:
            raise ValidationError(down)
        busy = WorkOrderOperation.objects.filter(work_center=work_center, status=WorkOrderOperation.Status.RUNNING) \
            .exclude(pk=op.pk).select_related("work_order").first()
        if busy and busy.work_order_id != wo.id:
            raise ValidationError(f"{busy.work_order.number} is still running here. Pause or finish it first.")
        if busy:  # same job, another of its steps here (e.g. drawer parts after carcass parts): move the clock over
            services.stop_operation(busy, finished=False, operator=user)
            switched_from = op_path(busy)
        services.start_operation(op, operator=user)
        started = True

    result = {"operation": op.id, "work_order": wo.number, "step": op_path(op), "started": started,
              "switched_from": switched_from, "part": None}
    if panel is not None:
        pid = make_part_id(wo, part_no)
        qty = int(float(panel["qty"]))
        done = set(op.part_scans.filter(part_id=pid).values_list("piece", flat=True))
        if piece is None:  # label without a piece number: take the next one not yet scanned
            piece = next((i for i in range(1, qty + 1) if i not in done), None)
            if piece is None:
                raise ValidationError(f"All {qty} pieces of {pid} ({panel['name']}) are already scanned here.")
        if not 1 <= piece <= qty:
            raise ValidationError(f"{pid} has only {qty} pieces; this label says piece {piece}.")
        if piece in done:
            raise ValidationError(f"{pid} piece {piece} of {qty} ({panel['name']}) was already scanned here.")
        PartScan.objects.create(operation=op, part_id=pid, piece=piece, scanned_by=user)
        result["part"] = {"part_id": pid, "piece": piece, "qty": qty, "name": panel["name"],
                          "length_mm": panel["length_mm"], "width_mm": panel["width_mm"], "material": panel["item_code"]}
    total = sum(pieces_for(op).values())
    result.update(pieces_total=total, pieces_scanned=op.part_scans.count())
    return result
