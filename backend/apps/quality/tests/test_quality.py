from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalog import demo_data
from apps.catalog.models import ProductTemplate
from apps.dispatch import services as dispatch
from apps.production.models import NonConformance, WorkOrder
from apps.quality import services
from apps.quality.models import Checklist
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(demo):
    demo_data.load_checklists()


@pytest.fixture
def client(setup):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("inspector"))
    return c


@pytest.fixture
def wo(setup):
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="Clinic"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": 2}, quantity=3)
    price_line(line)
    return confirm(order)[0]


def answers(cl, fail=(), values=None):
    values = values or {}
    return {i.id: {"passed": i.text not in fail, "value": values.get(i.text, i.target)} for i in cl.items.all()}


def final():
    return Checklist.objects.get(stage="final")


def test_measurement_judged_against_tolerance(wo):
    cnc = Checklist.objects.get(name="CNC drilling check")
    ok = services.record(wo, cnc, answers(cnc, values={"System hole distance from front edge (mm)": Decimal("37.4")}))
    assert ok.result == "pass" and ok.operation.work_center.code == "CNC"
    bad = services.record(wo, cnc, answers(cnc, values={"Hinge cup depth (mm)": Decimal("13")}))
    assert bad.result == "fail" and bad.non_conformance is None
    with pytest.raises(ValidationError, match="measurement"):
        services.record(wo, cnc, answers(cnc, values={"Hinge cup depth (mm)": ""}))


def test_failed_quantity_opens_ncr_and_rework_at_the_station(wo):
    edge = Checklist.objects.get(name="Edgebanding check")
    insp = services.record(wo, edge, answers(edge, fail={"Edge fully bonded, no gaps"}), failed_qty=1)
    ncr = insp.non_conformance
    assert ncr.operation.work_center.code == "EDGE" and "Edge fully bonded" in ncr.reason
    assert ncr.rework_order.operations.get().work_center.code == "EDGE"
    with pytest.raises(ValidationError, match="no failed quantity"):
        services.record(wo, edge, answers(edge), failed_qty=1)
    with pytest.raises(ValidationError, match="cannot be more"):
        services.record(wo, edge, answers(edge, fail={"No glue squeeze-out on faces"}), failed_qty=5)
    with pytest.raises(ValidationError, match="Answer every check"):
        services.record(wo, edge, {})


def test_final_inspection_gates_dispatch(wo):
    WorkOrder.objects.filter(pk=wo.pk).update(status="done")
    wo.refresh_from_db()
    line = wo.sales_line
    st = dispatch.line_status(line)
    assert st["ready"] == "0.00" and st["awaiting_inspection"] == "3.00"
    assert [r["number"] for r in dispatch.ready_to_ship()] == [line.order.number]
    with pytest.raises(ValidationError, match="waiting for final inspection"):
        dispatch.create_delivery(line.order, [(line, 1)], date(2026, 11, 5))
    fail = services.record(wo, final(), answers(final(), fail={"Doors and drawers aligned, gaps even"}), failed_qty=1)
    assert fail.non_conformance.operation.work_center.code == "PACK"
    assert not services.passed_final(wo)
    services.record(wo, final(), answers(final()))
    assert services.passed_final(wo)
    assert dispatch.line_status(line)["ready"] == "3.00"
    dispatch.create_delivery(line.order, [(line, 3)], date(2026, 11, 5))


def test_no_final_checklist_means_no_gate(wo):
    Checklist.objects.filter(stage="final").update(active=False)
    WorkOrder.objects.filter(pk=wo.pk).update(status="done")
    assert dispatch.line_status(wo.sales_line)["ready"] == "3.00"


def test_api(client, wo):
    edge = client.get("/api/checklists/?work_center=EDGE").json()
    assert len(edge) == 1 and len(edge[0]["items"]) == 3
    items = edge[0]["items"]
    r = client.post("/api/inspections/", {
        "work_order": wo.id, "checklist": edge[0]["id"], "failed_qty": "2", "notes": "Batch from morning shift",
        "answers": [{"item": items[0]["id"], "passed": False, "note": "gap on 2 doors"},
                    {"item": items[1]["id"], "passed": True}, {"item": items[2]["id"], "passed": True}]},
        format="json")
    assert r.status_code == 201, r.json()
    d = r.json()
    assert d["number"].startswith("QC-") and d["result"] == "fail" and d["work_center"] == "EDGE"
    assert d["non_conformance"] == NonConformance.objects.get().number and d["rework_order"]
    assert d["results"][0]["note"] == "gap on 2 doors"
    assert client.get(f"/api/inspections/?work_order={wo.id}").json()["count"] == 1

    assert client.get("/api/quality/awaiting-final/").json() == []
    WorkOrder.objects.filter(pk=wo.pk).update(status="done")
    waiting = client.get("/api/quality/awaiting-final/").json()
    assert [w["number"] for w in waiting] == [wo.number]
