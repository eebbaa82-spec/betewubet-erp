import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.catalog.models import ProductTemplate
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(demo):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("planner"))
    return c


@pytest.fixture
def wo(demo):
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="Hotel"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": 2}, quantity=3)
    price_line(line)
    return confirm(order)[0]


def test_cut_list_groups_every_panel_by_board(client, wo):
    cl = client.get(f"/api/work-orders/{wo.id}/cut-list/").json()
    panels = wo.exploded["panels"]
    assert cl["work_order"] == wo.number and cl["customer"] == "Hotel"
    assert cl["total_pieces"] == sum(int(Decimal(p["qty"])) for p in panels)
    parts = [r for g in cl["materials"] for r in g["parts"]]
    assert len(parts) == len(panels)
    assert len({r["part_id"] for r in parts}) == len(parts)
    assert all(r["part_id"].startswith(f"{wo.number}-P") for r in parts)
    for g in cl["materials"]:
        area = sum(Decimal(p["length_mm"]) * Decimal(p["width_mm"]) * Decimal(p["qty"])
                   for p in panels if p["item_code"] == g["item"]) / Decimal(1_000_000)
        assert Decimal(g["area_m2"]) == area.quantize(Decimal("0.0001"))
        assert g["sheets_estimate"] >= 1
        lengths = [Decimal(r["length_mm"]) for r in g["parts"]]
        assert lengths == sorted(lengths, reverse=True)


def test_cut_list_csv_matches_json(client, wo):
    resp = client.get(f"/api/work-orders/{wo.id}/cut-list/csv/")
    assert resp["Content-Type"].startswith("text/csv")
    assert f"{wo.number}-cut-list.csv" in resp["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    cl = client.get(f"/api/work-orders/{wo.id}/cut-list/").json()
    assert [r["part_id"] for r in rows] == [p["part_id"] for g in cl["materials"] for p in g["parts"]]
    assert sum(int(r["qty"]) for r in rows) == cl["total_pieces"]
    assert {r["grain_locked"] for r in rows} <= {"yes", "no"}


def test_rework_order_without_panels_has_empty_cut_list(client, wo):
    from apps.production.services import report_reject
    op = wo.operations.first()
    report_reject(op, qty=Decimal(1), reason="Chipped edge")
    rework = wo.reworks.get()
    cl = client.get(f"/api/work-orders/{rework.id}/cut-list/").json()
    assert cl["materials"] == [] and cl["total_pieces"] == 0
