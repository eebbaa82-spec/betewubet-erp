from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalog import demo_data
from apps.catalog.models import Item, ProductTemplate
from apps.inventory.models import Location, StockMove
from apps.inventory.services import issue, on_hand
from apps.purchasing import services
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(demo):
    demo_data.load_suppliers()


@pytest.fixture
def client(setup):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("buyer"))
    return c


def rows():
    return {r["item"]: r for r in services.shortages()}


def confirm_cabinets(qty, drawers=2):
    order = SalesOrder.objects.create(customer=Customer.objects.create(name="Office"), order_date=date(2026, 11, 3))
    line = SalesOrderLine.objects.create(order=order, template=ProductTemplate.objects.get(code="BASE-CAB"),
                                         configuration={"drawers": drawers}, quantity=qty)
    price_line(line)
    return confirm(order)[0]


def test_reorder_level_alone_creates_a_shortage(setup):
    r = rows()["SLD-450"]
    assert Decimal(r["in_stock"]) == 38 and Decimal(r["required"]) == 0
    assert Decimal(r["short"]) == 2
    assert r["supplier"] == "Merkato Hardware Supply" and r["suggested_packs"] == 2
    assert "MDF-WHT-18" not in rows()


def test_open_work_orders_add_to_the_shortage_and_issues_reduce_it(setup):
    wo = confirm_cabinets(30)
    need = wo.materials.get(item__code="SLD-450").planned_qty
    r = rows()["SLD-450"]
    assert Decimal(r["required"]) == need
    assert Decimal(r["short"]) == need + 40 - 38
    issue(Item.objects.get(code="SLD-450"), 10, Location.objects.get(code="MAIN"), work_order=wo)
    r = rows()["SLD-450"]
    assert Decimal(r["required"]) == need - 10
    assert Decimal(r["in_stock"]) == 28
    assert Decimal(r["short"]) == need + 40 - 38  # used 10, and 10 fewer still needed


def test_board_shortage_ignores_offcut_rack_and_buys_whole_sheets(setup):
    wo = confirm_cabinets(60)
    mdf = Item.objects.get(code="MDF-WHT-18")
    r = rows()["MDF-WHT-18"]
    assert Decimal(r["in_stock"]) == on_hand(mdf, Location.objects.get(code="MAIN"))
    assert r["pack_name"] == "sheet" and r["supplier"] == "Addis Board Trading"
    sheets = r["suggested_packs"]
    assert (sheets - 1) * Decimal(r["pack_qty"]) < Decimal(r["short"]) <= sheets * Decimal(r["pack_qty"])
    assert Decimal(r["required"]) == wo.materials.get(item=mdf).planned_qty


def test_draft_orders_group_by_supplier_and_clear_the_shortage(setup):
    confirm_cabinets(30)
    before = rows()
    orders = services.draft_orders()
    by_supplier = {po.supplier.name: po for po in orders}
    assert len(by_supplier) == len(orders)
    drafted = {ln.item.code for po in orders for ln in po.lines.all()}
    assert drafted == {k for k, r in before.items() if r["supplier"]}
    assert all(po.status == "draft" and po.expected_date > po.order_date for po in orders)
    assert rows() == {}  # everything short is now on order
    assert services.draft_orders() == []


def test_receive_against_order_books_stock_at_po_price(setup):
    Item.objects.filter(code="EB-22-04").update(reorder_level=2000)
    services.draft_orders(items={"SLD-450", "EB-22-04"})
    po = PurchaseOrder.objects.get(lines__item__code="SLD-450")
    line = po.lines.get(item__code="SLD-450")
    main = Location.objects.get(code="MAIN")
    with pytest.raises(ValidationError, match="only sent orders"):
        services.receive_line(line, 1, main)
    po.status = "sent"
    po.save()
    move = services.receive_line(line, 1, main)
    assert move.reference == po.number and move.kind == StockMove.Kind.RECEIPT
    assert move.unit_cost == line.price_per_pack / line.pack_qty
    po.refresh_from_db()
    assert po.status == "partial"
    with pytest.raises(ValidationError, match="still open"):
        services.receive_line(line, 5, main)
    services.receive_line(line, line.open_packs, main)
    eb = po.lines.get(item__code="EB-22-04")
    with pytest.raises(ValidationError, match="lot-tracked"):
        services.receive_line(eb, 1, main)
    services.receive_line(eb, eb.packs, main, lot_code="L-EB-NEW", colour_ref="W-01")
    po.refresh_from_db()
    assert po.status == "received"
    assert on_hand(Item.objects.get(code="SLD-450")) == 38 + line.packs * line.pack_qty
    assert Item.objects.get(code="EB-22-04").lots.filter(code="L-EB-NEW", colour_ref="W-01").exists()


def test_purchase_order_api_flow(client):
    sup = Supplier.objects.get(name="Merkato Hardware Supply")
    resp = client.post("/api/purchase-orders/", {
        "supplier": sup.id, "order_date": "2026-11-03",
        "lines": [{"item": "HNG-SC-110", "packs": "50"}, {"item": "SCR-CONF", "packs": "4"}],
    }, format="json")
    assert resp.status_code == 201, resp.json()
    po = resp.json()
    assert po["number"].startswith("PO-") and po["status"] == "draft"
    conf = next(ln for ln in po["lines"] if ln["item"] == "SCR-CONF")
    assert conf["pack_name"] == "box" and Decimal(conf["pack_qty"]) == 500
    t = po["totals"]
    assert Decimal(t["vat"]) == (Decimal(t["subtotal"]) * Decimal("0.15")).quantize(Decimal("0.01"))
    assert Decimal(t["total"]) == Decimal(t["subtotal"]) + Decimal(t["vat"])

    bad = client.post("/api/purchase-orders/", {"supplier": sup.id, "order_date": "2026-11-03",
                                               "lines": [{"item": "MDF-WHT-18", "packs": "1"}]}, format="json")
    assert bad.status_code == 400 and "no price" in str(bad.json())

    pid = po["id"]
    assert client.post(f"/api/purchase-orders/{pid}/send/").json()["status"] == "sent"
    assert client.patch(f"/api/purchase-orders/{pid}/", {"notes": "x"}, format="json").status_code == 400
    hinge = next(ln for ln in po["lines"] if ln["item"] == "HNG-SC-110")
    r = client.post(f"/api/purchase-orders/{pid}/receive/", {"line": hinge["id"], "packs": "20", "location": "MAIN"},
                    format="json")
    assert r.status_code == 200 and r.json()["status"] == "partial"
    assert client.post(f"/api/purchase-orders/{pid}/cancel/").status_code == 400
    assert client.delete(f"/api/purchase-orders/{pid}/").status_code == 405


def test_shortage_api_and_draft_endpoint(client):
    data = client.get("/api/purchasing/shortages/").json()
    assert any(r["item"] == "SLD-450" for r in data)
    made = client.post("/api/purchasing/draft-orders/", {"items": ["SLD-450"]}, format="json")
    assert made.status_code == 201
    assert [m["supplier"] for m in made.json()] == ["Merkato Hardware Supply"]
    assert not any(r["item"] == "SLD-450" for r in client.get("/api/purchasing/shortages/").json())
