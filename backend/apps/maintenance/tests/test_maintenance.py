from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog import demo_data
from apps.catalog.models import ProductTemplate
from apps.core.models import WorkCenter
from apps.maintenance import services
from apps.maintenance.models import Machine, MaintenanceLog, MaintenancePlan
from apps.production.models import TimeLog
from apps.production.services import create_work_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def machines(demo):
    demo_data.load_machines()
    Machine.objects.update(hours_since=timezone.now() - timedelta(days=30))


@pytest.fixture
def client(machines):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("tech"))
    return c


def saw():
    return Machine.objects.get(code="SAW-01")


def log_time(wc_code, hours, start=None):
    wo = create_work_order(ProductTemplate.objects.get(code="BASE-CAB"), {"drawers": 0}, 1)
    op = wo.operations.filter(work_center__code=wc_code).first()
    start = start or timezone.now() - timedelta(hours=hours + 1)
    return TimeLog.objects.create(operation=op, started_at=start, ended_at=start + timedelta(hours=hours))


def test_hours_are_meter_plus_station_time_since_setup(machines):
    assert services.machine_hours(saw()) == Decimal("4210.0")
    log_time("SAW", 2.5)
    assert services.machine_hours(saw()) == Decimal("4212.5")
    # time before the machine was set up does not count
    log_time("SAW", 3, start=saw().hours_since - timedelta(days=2))
    assert services.machine_hours(saw()) == Decimal("4212.5")
    assert services.machine_hours(Machine.objects.get(code="COMP-01")) == Decimal("9100.0")


def test_due_by_hours_or_days_whichever_first(machines):
    rows = {r["task"]: r for r in services.due_list()}
    blades = rows["Change main and scoring blades"]          # 38 of 40 h used
    assert blades["state"] == "soon" and Decimal(blades["hours_left"]) == 2
    assert rows["Clean and lubricate sliding carriage"]["state"] == "overdue"  # 8 of 7 days
    assert rows["Clean glue pot and pressure rollers"]["state"] == "ok"
    log_time("SAW", 3)
    blades = {r["task"]: r for r in services.due_list()}["Change main and scoring blades"]
    assert blades["state"] == "overdue" and Decimal(blades["hours_left"]) == -1
    states = [r["state"] for r in services.due_list()]
    assert states == sorted(states, key=["overdue", "soon", "ok"].index)


def test_marking_done_restarts_the_interval(client):
    plan = MaintenancePlan.objects.get(task="Clean and lubricate sliding carriage")
    r = client.post(f"/api/maintenance-plans/{plan.id}/done/", {"done_by": "Abebe", "notes": "Rails cleaned",
                                                                 "parts_cost": "350"}, format="json")
    assert r.status_code == 201 and r.json()["kind"] == "preventive" and not r.json()["is_open"]
    plan.refresh_from_db()
    assert plan.last_done_hours == Decimal("4210.0")
    assert services.plan_status(plan)["state"] == "ok"
    assert MaintenanceLog.objects.get(plan=plan).parts_cost == 350


def test_breakdown_stops_the_station_until_closed(client):
    wo = create_work_order(ProductTemplate.objects.get(code="BASE-CAB"), {"drawers": 0}, 1)
    op = wo.operations.filter(work_center__code="SAW").first()
    r = client.post("/api/machines/SAW-01/breakdown/", {"description": "Scoring blade motor not starting"}, format="json")
    assert r.status_code == 201 and r.json()["machine_down"]
    assert client.get("/api/machines/SAW-01/").json()["state"] == "down"

    start = client.post(f"/api/operations/{op.id}/start/")
    assert start.status_code == 400 and "SAW is down" in str(start.json())
    scan = client.post("/api/work-centers/SAW/scan/", {"code": wo.number}, format="json")
    assert scan.status_code == 400 and "SAW is down" in str(scan.json())

    log_id = r.json()["id"]
    assert client.post(f"/api/maintenance-logs/{log_id}/close/", {}, format="json").status_code == 400
    closed = client.post(f"/api/maintenance-logs/{log_id}/close/",
                         {"action_taken": "Replaced motor capacitor", "parts_cost": "1200"}, format="json")
    assert closed.status_code == 200 and closed.json()["closed_at"]
    assert client.post(f"/api/operations/{op.id}/start/").status_code == 200


def test_breakdown_without_stopping_and_downtime(machines):
    m = saw()
    services.report_breakdown(m, "Dust extraction weak", machine_down=False)
    assert services.down_reason(m.work_center) is None
    log = services.report_breakdown(m, "Fence jammed")
    MaintenanceLog.objects.filter(pk=log.pk).update(reported_at=timezone.now() - timedelta(hours=3))
    log.refresh_from_db()
    services.close_log(log, "Freed and greased")
    assert services.downtime_hours(m) == Decimal("3.0")
    with pytest.raises(Exception):
        services.close_log(log, "again")


def test_station_with_no_machines_is_never_down(machines):
    assert services.down_reason(WorkCenter.objects.get(code="ASM")) is None


def test_machine_list_and_due_api(client):
    rows = client.get("/api/machines/").json()
    assert [m["code"] for m in rows] == ["CNC-01", "COMP-01", "EDGE-01", "SAW-01", "SPRAY-01"]
    by = {m["code"]: m for m in rows}
    assert by["SAW-01"]["state"] == "overdue" and by["SAW-01"]["hours"] == "4210.0"
    assert len(by["COMP-01"]["plans"]) == 2
    due = client.get("/api/maintenance/due/").json()
    assert due[0]["state"] == "overdue"
    bad = client.post("/api/maintenance-plans/", {"machine": "SAW-01", "task": "Nothing"}, format="json")
    assert bad.status_code == 400
