from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import Item, ProductTemplate
from apps.inventory.models import Location
from apps.inventory.services import issue
from apps.production import costing
from apps.production.models import WorkOrder
from apps.production.services import start_operation, stop_operation
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line, totals

pytestmark = pytest.mark.django_db


@pytest.fixture
def quote(demo):
    customer = Customer.objects.create(name="Sample customer PLC", tin="0000000000")
    order = SalesOrder.objects.create(customer=customer, order_date=date(2026, 11, 3), due_date=date(2026, 12, 1))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"W": 600, "drawers": 0}, quantity=4)
    price_line(line)
    return order


def test_price_follows_margin_and_vat_is_15_percent(quote):
    line = quote.lines.get()
    assert line.unit_price == (line.estimated_unit_cost / Decimal("0.70")).quantize(Decimal("0.01"))
    t = totals(quote)
    assert Decimal(t["vat"]) == (Decimal(t["subtotal"]) * Decimal("0.15")).quantize(Decimal("0.01"))
    assert Decimal(t["estimated_margin_pct"]) == Decimal("30.00")


def test_locked_price_is_kept_on_reprice(quote):
    line = quote.lines.get()
    line.unit_price, line.price_locked = Decimal("25000"), True
    line.save()
    price_line(line)
    assert line.unit_price == Decimal("25000")


def test_confirm_creates_work_order_with_frozen_bom_and_plan(quote):
    [wo] = confirm(quote)
    assert quote.status == SalesOrder.Status.CONFIRMED
    assert wo.quantity == 4
    assert wo.exploded["params"]["W"] == 600.0
    assert wo.materials.get(item__code="HNG-SC-110").planned_qty == 8  # 1 door x 2 hinges x 4
    assert wo.operations.filter(work_center__code="SAW").exists()
    assert Decimal(wo.estimate["total"]) > 0


def test_actual_cost_comes_from_issues_and_scanned_time(quote):
    [wo] = confirm(quote)
    main = Location.objects.get(code="MAIN")
    hinges = Item.objects.get(code="HNG-SC-110")
    issue(hinges, 8, main, work_order=wo)
    op = wo.operations.first()
    log = start_operation(op)
    stop_operation(op, good_qty=4, finished=True)
    log.refresh_from_db()
    log.started_at = log.ended_at - timedelta(minutes=30)  # pretend the job took 30 minutes
    log.save()
    act = costing.actual(wo)
    assert Decimal(act["material"]) == Decimal("1440.00")  # 8 x 180
    rate = op.work_center.machine_rate + op.work_center.labour_rate
    assert Decimal(act["labour"]) + Decimal(act["machine"]) == (rate / 2).quantize(Decimal("0.01"))
    assert set(costing.variance(wo)) == {"material", "labour", "machine", "overhead", "total"}


def test_cannot_confirm_twice(quote):
    confirm(quote)
    with pytest.raises(Exception, match="already confirmed"):
        confirm(quote)


def test_api_configure_endpoint(demo):
    user = User.objects.create_user("sales", password="x")
    client = APIClient()
    client.force_authenticate(user)
    res = client.post("/api/templates/BASE-CAB/explode/", {"params": {"W": 800, "drawers": 3}, "qty": 2},
                      format="json")
    assert res.status_code == 200, res.data
    body = res.json()
    assert body["template_code"] == "BASE-CAB"
    assert Decimal(body["estimate"]["total"]) > 0
    assert any(m["offcut"] == "OC-00003" for m in body["offcut_matches"])

    bad = client.post("/api/templates/BASE-CAB/explode/", {"params": {"W": 5000}}, format="json")
    assert bad.status_code == 400
    assert "at most 1200" in str(bad.json())


def test_api_requires_login(demo):
    assert APIClient().get("/api/items/").status_code in (401, 403)


def test_api_quote_to_work_order(demo):
    user = User.objects.create_user("sales", password="x")
    client = APIClient()
    client.force_authenticate(user)
    customer = client.post("/api/customers/", {"name": "Sample customer"}, format="json").json()
    order = client.post("/api/sales-orders/", {"customer": customer["id"], "order_date": "2026-11-03"},
                        format="json").json()
    line = client.post("/api/sales-order-lines/", {"order": order["id"], "template_code": "BASE-CAB",
                                                   "configuration": {"W": 900}, "quantity": "2"}, format="json")
    assert line.status_code == 201, line.data
    assert Decimal(line.json()["unit_price"]) > 0
    res = client.post(f"/api/sales-orders/{order['id']}/confirm/")
    assert res.status_code == 200, res.data
    wo = WorkOrder.objects.get(number=res.json()["work_orders"][0])
    cost = client.get(f"/api/work-orders/{wo.id}/cost/").json()
    assert cost["total"]["actual"] == "0.00"
