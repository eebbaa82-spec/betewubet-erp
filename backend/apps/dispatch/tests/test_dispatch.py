from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalog.models import ProductTemplate
from apps.dispatch import services
from apps.dispatch.models import Delivery, Installation
from apps.production.models import WorkOrder
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(demo):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("dispatcher"))
    return c


@pytest.fixture
def order(demo):
    cust = Customer.objects.create(name="Unity Hotel", phone="0911000000", address="Bole, Addis Ababa")
    o = SalesOrder.objects.create(customer=cust, order_date=date(2026, 11, 3), site_address="Bole road, 3rd floor")
    for seq, (drawers, qty) in enumerate([(2, 4), (0, 2)], start=1):
        line = SalesOrderLine.objects.create(order=o, sequence=seq * 10, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                             configuration={"drawers": drawers}, quantity=qty)
        price_line(line)
    confirm(o)
    return o


def finish(order, seq):
    WorkOrder.objects.filter(sales_line__order=order, sales_line__sequence=seq).update(status="done")


def lines(order):
    return {l.sequence: l for l in order.lines.all()}


def test_only_finished_work_shows_as_ready(order):
    assert services.ready_to_ship() == []
    finish(order, 10)
    [row] = services.ready_to_ship()
    by = {l["sequence"]: l for l in row["lines"]}
    assert by[10]["ready"] == "4.00" and by[20]["ready"] == "0.00"
    assert row["address"] == "Bole road, 3rd floor"


def test_cannot_ship_more_than_finished_and_not_shipped(order):
    finish(order, 10)
    l = lines(order)
    with pytest.raises(ValidationError, match="Only 0"):
        services.create_delivery(order, [(l[20], 1)], date(2026, 11, 5))
    services.create_delivery(order, [(l[10], 3)], date(2026, 11, 5))
    with pytest.raises(ValidationError, match="Only 1"):
        services.create_delivery(order, [(l[10], 2)], date(2026, 11, 6))
    d = services.create_delivery(order, [(l[10], 1)], date(2026, 11, 6))
    services.cancel(d)  # cancelled notes free the quantity again
    assert services.line_status(l[10])["ready"] == "1.00"


def test_full_flow_to_installed_with_a_return_visit(order):
    finish(order, 10)
    finish(order, 20)
    l = lines(order)
    d = services.create_delivery(order, [(l[10], 4), (l[20], 2)], date(2026, 11, 5), install_required=True,
                                 vehicle="3-A12345", driver="Dawit")
    assert d.address == "Bole road, 3rd floor" and d.contact_phone == "0911000000"
    services.dispatch(d)
    order.refresh_from_db()
    assert order.status == "dispatched"
    with pytest.raises(ValidationError, match="name"):
        services.deliver(d, " ")
    services.deliver(d, "Hirut (site manager)", crew="Team A")
    job = Installation.objects.get(delivery=d)
    assert job.crew == "Team A" and job.status == "scheduled"
    order.refresh_from_db()
    assert order.status == "dispatched"
    job, follow = services.complete_installation(job, "Hirut", snags="Door 3 hinge needs adjusting")
    assert job.status == "snags" and follow.status == "scheduled" and follow.return_visit_of == job
    order.refresh_from_db()
    assert order.status == "dispatched"
    services.complete_installation(follow, "Hirut")
    order.refresh_from_db()
    assert order.status == "installed"
    with pytest.raises(ValidationError, match="already"):
        services.complete_installation(follow, "Hirut")


def test_partial_delivery_keeps_order_open(order):
    finish(order, 10)
    services.dispatch(services.create_delivery(order, [(lines(order)[10], 4)], date(2026, 11, 5)))
    order.refresh_from_db()
    assert order.status == "confirmed"


def test_delivery_api(client, order):
    finish(order, 10)
    ready = client.get("/api/dispatch/ready/").json()
    line_id = next(l["line"] for l in ready[0]["lines"] if l["sequence"] == 10)
    r = client.post("/api/deliveries/", {"order": order.id, "scheduled_date": "2026-11-05", "vehicle": "3-A12345",
                                         "install_required": True, "lines": [{"line": line_id, "quantity": "2"}]},
                    format="json")
    assert r.status_code == 201, r.json()
    d = r.json()
    assert d["number"].startswith("DN-") and d["lines"][0]["quantity"] == "2.00" and d["customer"] == "Unity Hotel"
    too_many = client.post("/api/deliveries/", {"order": order.id, "lines": [{"line": line_id, "quantity": "3"}]},
                           format="json")
    assert too_many.status_code == 400
    assert client.patch(f"/api/deliveries/{d['id']}/", {"driver": "Dawit"}, format="json").json()["driver"] == "Dawit"
    assert client.post(f"/api/deliveries/{d['id']}/deliver/", {"received_by": "x"}, format="json").status_code == 400
    assert client.post(f"/api/deliveries/{d['id']}/dispatch/").json()["status"] == "out"
    assert client.patch(f"/api/deliveries/{d['id']}/", {"driver": "Other"}, format="json").status_code == 400
    done = client.post(f"/api/deliveries/{d['id']}/deliver/", {"received_by": "Hirut", "install_date": "2026-11-06"},
                       format="json").json()
    assert done["status"] == "delivered" and done["installations"][0]["scheduled_date"] == "2026-11-06"
    job = done["installations"][0]["id"]
    res = client.post(f"/api/installations/{job}/complete/", {"signed_off_by": "Hirut", "snags": "Scratch on top"},
                      format="json").json()
    assert res["status"] == "snags" and res["follow_up"]["return_visit_of"] == res["number"]
    assert Delivery.objects.get(pk=d["id"]).received_by == "Hirut"
    assert client.post("/api/installations/", {}, format="json").status_code == 400
