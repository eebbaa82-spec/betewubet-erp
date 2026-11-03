from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import Item, ProductTemplate
from apps.inventory.models import Lot
from apps.inventory.services import on_hand
from apps.production.models import NonConformance, WorkOrder
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(demo):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("floor"))
    return c


@pytest.fixture
def wo(demo):
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="C"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": 0}, quantity=4)
    price_line(line)
    return confirm(order)[0]


def test_stock_summary_shows_packs_lots_and_value(client):
    rows = {r["code"]: r for r in client.get("/api/stock/").json()}
    mdf = rows["MDF-WHT-18"]
    full_sheets = Decimal(mdf["on_hand"]) - Decimal(mdf["in_offcuts"])
    assert mdf["pack"] == "sheet"
    assert (full_sheets / Decimal(mdf["pack_size"])).quantize(Decimal("0.01")) == 46
    assert mdf["lots"][0]["code"] == "L-MDF-WHT-18-01"
    assert Decimal(mdf["in_offcuts"]) == Decimal("1.4980")
    assert Decimal(mdf["value"]) == pytest.approx(Decimal(mdf["on_hand"]) * Decimal(mdf["unit_cost"]), rel=Decimal("0.0001"))


def test_receive_in_rolls_converts_to_metres_and_creates_lot(client):
    res = client.post("/api/stock/receive/", {
        "item": "EB-22-04", "qty": "3", "unit": "roll", "unit_cost": "5600", "location": "MAIN",
        "lot_code": "EB-2611-07", "colour_ref": "White W100"}, format="json")
    assert res.status_code == 201, res.data
    assert Decimal(res.json()["qty"]) == 600  # 3 rolls x 200 m
    assert Decimal(res.json()["unit_cost"]) == 28  # 5,600 per roll / 200 m
    assert Lot.objects.get(code="EB-2611-07").colour_ref == "White W100"


def test_receive_needs_lot_for_lot_tracked_items(client):
    res = client.post("/api/stock/receive/", {"item": "LAC-PU", "qty": "1", "unit": "drum", "unit_cost": "22000",
                                              "location": "MAIN"}, format="json")
    assert res.status_code == 400 and "lot-tracked" in str(res.json())


def test_issue_to_work_order_books_actual_material(client, wo):
    res = client.post("/api/stock/issue/", {"work_order": wo.number, "item": "HNG-SC-110", "qty": "8",
                                            "location": "MAIN"}, format="json")
    assert res.status_code == 201, res.data
    data = client.get(f"/api/work-orders/{wo.id}/").json()
    hinges = next(m for m in data["materials"] if m["item"] == "HNG-SC-110")
    assert Decimal(hinges["issued_qty"]) == 8
    assert client.get(f"/api/work-orders/{wo.id}/cost/").json()["material"]["actual"] == "1440.00"


def test_issue_picks_oldest_lot_for_lot_tracked_items(client, wo):
    res = client.post("/api/stock/issue/", {"work_order": wo.number, "item": "EB-22-04", "qty": "10",
                                            "location": "MAIN"}, format="json")
    assert res.status_code == 201, res.data
    assert on_hand(Item.objects.get(code="EB-22-04")) == 1830


def test_register_offcut_from_work_order(client, wo):
    res = client.post("/api/offcuts/register/", {"item": "MDF-WHT-18", "length_mm": 900, "width_mm": 450,
                                                 "location": "OC-RACK", "work_order": wo.number}, format="json")
    assert res.status_code == 201, res.data
    assert res.json()["source_work_order_number"] == wo.number
    small = client.post("/api/offcuts/register/", {"item": "MDF-WHT-18", "length_mm": 900, "width_mm": 200,
                                                   "location": "OC-RACK"}, format="json")
    assert small.status_code == 400


def test_station_flow_with_reject_opens_ncr_and_rework(client, wo):
    ops = client.get("/api/operations/?work_center=EDGE&open=1").json()["results"]
    op = next(o for o in ops if o["work_order"] == wo.number)
    assert op["customer"] == "C" and op["product"] == "Base cabinet"
    assert client.post(f"/api/operations/{op['id']}/start/").status_code == 200
    running = client.get(f"/api/operations/{op['id']}/").json()
    assert running["status"] == "running" and running["running_since"]

    other = next(o for o in ops if o["id"] != op["id"]) if len(ops) > 1 else None
    if other:
        assert client.post(f"/api/operations/{other['id']}/start/").status_code == 400

    no_reason = client.post(f"/api/operations/{op['id']}/stop/", {"rejected_qty": "1", "finished": True},
                            format="json")
    assert no_reason.status_code == 400
    res = client.post(f"/api/operations/{op['id']}/stop/", {
        "good_qty": "3", "rejected_qty": "1", "reject_reason": "Edge chipped", "finished": True}, format="json")
    assert res.status_code == 200, res.data
    body = res.json()
    ncr = NonConformance.objects.get(number=body["non_conformance"])
    rework = WorkOrder.objects.get(number=body["rework_order"])
    assert ncr.qty == 1 and rework.rework_of == wo and rework.quantity == 1
    assert rework.operations.get().work_center.code == "EDGE"
    queue = client.get("/api/operations/?work_center=EDGE&open=1").json()["results"]
    assert any(o["work_order"] == rework.number and o["is_rework"] for o in queue)
    assert all(o["id"] != op["id"] for o in queue)


def test_work_centers_and_work_order_lookup(client, wo):
    codes = [w["code"] for w in client.get("/api/work-centers/").json()]
    assert "SAW" in codes and "SPRAY" in codes
    found = client.get(f"/api/work-orders/?number={wo.number.lower()}").json()["results"]
    assert [w["number"] for w in found] == [wo.number]
