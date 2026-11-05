from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import ProductTemplate
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


def test_sign_in_flow(demo):
    User.objects.create_user("abebe", password="s3cret-pass")
    client = APIClient(enforce_csrf_checks=True)
    assert client.get("/api/auth/me/").json() == {"user": None}
    assert "csrftoken" in client.cookies
    token = client.cookies["csrftoken"].value
    bad = client.post("/api/auth/login/", {"username": "abebe", "password": "nope"}, format="json",
                      HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400
    ok = client.post("/api/auth/login/", {"username": "abebe", "password": "s3cret-pass"}, format="json",
                     HTTP_X_CSRFTOKEN=token)
    assert ok.json()["user"]["username"] == "abebe"
    assert client.get("/api/items/").status_code == 200


def test_choice_parameters_accept_value_label_pairs(demo):
    client = APIClient()
    client.force_authenticate(User.objects.create_user("u"))
    t = client.get("/api/templates/BASE-CAB/").json()
    front = next(p for p in t["parameters"] if p["name"] == "front")
    assert front["choices"][1] == ["lac", "MDF, lacquer sprayed"]
    res = client.post("/api/templates/BASE-CAB/explode/", {"params": {"front": "lac"}}, format="json")
    assert res.status_code == 200
    bad = client.post("/api/templates/BASE-CAB/explode/", {"params": {"front": "gold"}}, format="json")
    assert "must be one of mel, lac, ven" in str(bad.json())


def test_confirmed_order_lines_are_locked(demo):
    client = APIClient()
    client.force_authenticate(User.objects.create_user("u"))
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="C"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"))
    price_line(line)
    confirm(order)
    assert client.patch(f"/api/sales-order-lines/{line.id}/", {"quantity": "9"}, format="json").status_code == 400
    assert client.delete(f"/api/sales-order-lines/{line.id}/").status_code == 400


def test_page_size_and_filters(demo):
    client = APIClient()
    client.force_authenticate(User.objects.create_user("u"))
    assert len(client.get("/api/items/?page_size=500").json()["results"]) == 23
    assert all(i["kind"] == "board" for i in client.get("/api/items/?kind=board").json()["results"])
    codes = [t["code"] for t in client.get("/api/templates/?sellable=1").json()["results"]]
    assert codes == ["BASE-CAB", "BOOKSHELF", "DESK", "WARDROBE"]
