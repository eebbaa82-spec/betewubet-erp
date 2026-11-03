from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import ProductTemplate
from apps.production import scanning
from apps.production.models import PartScan, WorkOrderOperation
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(demo):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("saw-operator"))
    return c


@pytest.fixture
def wo(demo):
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="Bank"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": 2}, quantity=2)
    price_line(line)
    return confirm(order)[0]


def part_no(wo, name):
    return next(n for n, p in enumerate(wo.exploded["panels"], 1) if p["name"] == name)


def scan(client, wc, code):
    return client.post(f"/api/work-centers/{wc}/scan/", {"code": code}, format="json")


def test_parse_labels():
    assert scanning.parse("wo-000012-p03-2") == ("WO-000012", 3, 2)
    assert scanning.parse("WO-000012-P03") == ("WO-000012", 3, None)
    assert scanning.parse(" WO-000012 ") == ("WO-000012", None, None)
    with pytest.raises(Exception):
        scanning.parse("hello")


def test_every_panel_piece_belongs_to_exactly_one_step_per_station(wo):
    for wc in ("SAW", "EDGE", "CNC"):
        ops = wo.operations.filter(work_center__code=wc)
        counted = {}
        for op in ops:
            for n, q in scanning.pieces_for(op).items():
                assert n not in counted
                counted[n] = q
        assert sum(counted.values()) == sum(int(float(p["qty"])) for p in wo.exploded["panels"])
    drawer_saw = wo.operations.get(work_center__code="SAW", description__startswith="Drawers")
    assert set(scanning.pieces_for(drawer_saw)) == {
        n for n, p in enumerate(wo.exploded["panels"], 1) if p["path"].startswith("Drawers")}


def test_scanning_a_panel_starts_its_step_and_records_the_piece(client, wo):
    n = part_no(wo, "Side panel")
    r = scan(client, "SAW", f"{wo.number}-P{n:02d}-1")
    assert r.status_code == 200, r.json()
    d = r.json()
    assert d["started"] and d["step"] == "Base cabinet"
    assert d["part"]["name"] == "Side panel" and d["part"]["piece"] == 1 and d["part"]["qty"] == 4
    op = WorkOrderOperation.objects.get(pk=d["operation"])
    assert op.status == "running" and op.work_center.code == "SAW"
    assert d["pieces_scanned"] == 1 and d["pieces_total"] == sum(scanning.pieces_for(op).values())

    again = scan(client, "SAW", f"{wo.number}-P{n:02d}-1")
    assert again.status_code == 400 and "already scanned" in str(again.json())
    no_piece = scan(client, "SAW", f"{wo.number}-P{n:02d}").json()
    assert no_piece["part"]["piece"] == 2 and not no_piece["started"]
    assert scan(client, "SAW", f"{wo.number}-P{n:02d}-9").status_code == 400

    listed = client.get("/api/operations/?work_center=SAW&open=1").json()["results"]
    row = next(o for o in listed if o["id"] == op.id)
    assert row["pieces_scanned"] == 2 and row["pieces_total"] == d["pieces_total"]


def test_drawer_part_switches_to_the_drawer_step_of_the_same_job(client, wo):
    first = scan(client, "SAW", f"{wo.number}-P{part_no(wo, 'Bottom'):02d}-1").json()
    d = scan(client, "SAW", f"{wo.number}-P{part_no(wo, 'Drawer side'):02d}-1").json()
    assert d["step"] == "Drawers > Drawer box" and d["started"] and d["switched_from"] == "Base cabinet"
    carcass = WorkOrderOperation.objects.get(pk=first["operation"])
    assert carcass.status == "paused" and carcass.time_logs.filter(ended_at__isnull=True).count() == 0
    assert WorkOrderOperation.objects.filter(status="running").get().pk == d["operation"]


def test_another_job_running_blocks_the_station(client, wo, demo):
    other = confirm_another()
    scan(client, "SAW", f"{wo.number}-P01-1")
    r = scan(client, "SAW", f"{other.number}-P01-1")
    assert r.status_code == 400 and f"{wo.number} is still running here" in str(r.json())


def confirm_another():
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="School"), order_date=date(2026, 11, 4))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": 0}, quantity=1)
    price_line(line)
    return confirm(order)[0]


def test_wrong_station_finished_step_and_unknown_codes(client, wo):
    assert "no step at SPRAY" in str(scan(client, "SPRAY", wo.number).json())
    assert "No job" in str(scan(client, "SAW", "WO-999999").json())
    assert "no part P99" in str(scan(client, "SAW", f"{wo.number}-P99").json())
    assert "not a job or panel label" in str(scan(client, "SAW", "SO-000001").json())
    d = scan(client, "PACK", wo.number).json()
    client.post(f"/api/operations/{d['operation']}/stop/", {"finished": True}, format="json")
    assert "already finished" in str(scan(client, "PACK", wo.number).json())
    assert PartScan.objects.count() == 0
