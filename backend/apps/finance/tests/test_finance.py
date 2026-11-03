from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import ProductTemplate
from apps.dispatch.models import Delivery, DeliveryLine
from apps.finance import services
from apps.finance.models import FinanceSettings, Invoice
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier
from apps.inventory.models import Item
from apps.sales.models import Customer, SalesOrder, SalesOrderLine

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def client(demo):
    c = APIClient()
    c.force_authenticate(User.objects.create_user("accountant"))
    return c


@pytest.fixture
def order(demo):
    cust = Customer.objects.create(name="Unity Hotel", tin="0012345678", withholds_tax=True)
    o = SalesOrder.objects.create(customer=cust, order_date=date(2026, 11, 3), status="production")
    tpl = ProductTemplate.objects.get(code="BASE-CAB")
    SalesOrderLine.objects.create(order=o, sequence=10, template=tpl, configuration={"drawers": 2}, quantity=4,
                                  unit_price=D("10000"))
    SalesOrderLine.objects.create(order=o, sequence=20, template=tpl, configuration={"drawers": 0}, quantity=2,
                                  unit_price=D("6000"))
    return o  # subtotal 52,000


def ship(order, quantities):
    d = Delivery.objects.create(order=order, scheduled_date=date.today(), status=Delivery.Status.OUT,
                                dispatched_at=timezone.now())
    for line in order.lines.all():
        if quantities.get(line.sequence):
            DeliveryLine.objects.create(delivery=d, sales_line=line, quantity=quantities[line.sequence])
    return d


def test_delivery_invoice_has_vat_and_number_on_issue(order):
    inv = services.invoice_delivery(ship(order, {10: 4, 20: 2}))
    assert inv.number is None and inv.status == "draft"
    assert inv.subtotal == D("52000.00") and inv.vat == D("7800.00") and inv.total == D("59800.00")
    assert "drawers 2" in inv.lines.first().description
    services.issue(inv, issue_date=date(2026, 11, 5))
    assert inv.number == "INV-00001" and inv.due_date == date(2026, 12, 5)
    inv2 = services.invoice_delivery(ship(order, {10: 1}))
    services.issue(inv2)
    assert inv2.number == "INV-00002"


def test_delivery_cannot_be_invoiced_twice_or_before_it_leaves(order):
    d = ship(order, {10: 1})
    services.invoice_delivery(d)
    with pytest.raises(ValidationError, match="already invoiced"):
        services.invoice_delivery(d)
    d2 = ship(order, {20: 1})
    d2.status = Delivery.Status.PLANNED
    d2.save()
    with pytest.raises(ValidationError, match="has not left"):
        services.invoice_delivery(d2)


def test_advance_is_deducted_from_later_invoices(order):
    adv = services.advance_invoice(order)
    assert adv.subtotal == D("26000.00")
    services.issue(adv)
    inv1 = services.invoice_delivery(ship(order, {10: 2}))          # 20,000 of goods
    assert inv1.subtotal == D("0.00")                                 # fully covered by the advance
    assert inv1.lines.last().advance == adv
    services.issue(inv1)
    inv2 = services.invoice_delivery(ship(order, {10: 2, 20: 2}))   # 32,000 of goods, 6,000 advance left
    assert inv2.subtotal == D("26000.00") and inv2.vat == D("3900.00")
    assert services.advance_left(adv) == 0
    with pytest.raises(ValidationError, match="more than the order"):
        services.advance_invoice(order, D("0.6"))


def test_draft_advance_is_not_deducted(order):
    services.advance_invoice(order)
    inv = services.invoice_delivery(ship(order, {10: 1}))
    assert inv.subtotal == D("10000.00")


def test_payment_with_withholding_clears_invoice(order):
    inv = services.issue(services.invoice_delivery(ship(order, {10: 4, 20: 2})))
    assert services.expected_withholding(inv) == D("1560.00")  # 3% of 52,000
    with pytest.raises(ValidationError, match="withholding receipt"):
        services.record_payment(inv, D("58240"), D("1560"))
    services.record_payment(inv, D("30000"), method="bank", reference="FT123")
    with pytest.raises(ValidationError, match="more than the 29800.00"):
        services.record_payment(inv, D("29801"))
    services.record_payment(inv, D("28240"), D("1560"), withholding_receipt_no="WH-778")
    assert inv.balance == 0


def test_no_withholding_below_threshold_or_for_non_agents(order):
    inv = services.issue(services.invoice_delivery(ship(order, {10: 1})))
    assert services.expected_withholding(inv) == 0
    order.customer.withholds_tax = False
    order.customer.save()
    inv2 = services.issue(services.invoice_delivery(ship(order, {10: 3})))
    assert services.expected_withholding(inv2) == 0


def test_payment_needs_issued_invoice(order):
    inv = services.invoice_delivery(ship(order, {10: 1}))
    with pytest.raises(ValidationError, match="Issue the invoice"):
        services.record_payment(inv, D("100"))


@pytest.fixture
def po(demo):
    sup = Supplier.objects.create(name="Merkato Board Traders", vat_registered=True)
    po = PurchaseOrder.objects.create(supplier=sup, order_date=date(2026, 11, 1), status="partial")
    item = Item.objects.first()
    PurchaseOrderLine.objects.create(order=po, item=item, pack_name="sheet", pack_qty=1, packs=20,
                                     price_per_pack=D("2500"), received_packs=12)
    return po


def test_bill_from_po_is_limited_to_received_and_withholds(po):
    assert services.to_bill()[0]["unbilled"] == "30000.00"
    bill = services.bill_from_po(po, "MBT-1001", date(2026, 11, 4))
    assert bill.subtotal == D("30000.00") and bill.vat == D("4500.00") and bill.withholding == D("900.00")
    assert bill.payable == D("33600.00") and bill.due_date == date(2026, 12, 4)
    assert services.to_bill() == []
    with pytest.raises(ValidationError, match="Nothing received"):
        services.bill_from_po(po, "MBT-1002")
    po.lines.update(received_packs=20)
    with pytest.raises(ValidationError, match="Only 20000.00"):
        services.bill_from_po(po, "MBT-1002", subtotal=D("25000"))
    with pytest.raises(ValidationError, match="already booked"):
        services.bill_from_po(po, "MBT-1001")
    small = services.bill_from_po(po, "MBT-1002", subtotal=D("15000"))
    assert small.withholding == 0
    services.pay_bill(bill, D("33600"))
    assert bill.balance == 0
    with pytest.raises(ValidationError, match="more than"):
        services.pay_bill(bill, D("1"))


def test_aging_buckets(order):
    inv = services.issue(services.invoice_delivery(ship(order, {10: 1})), issue_date=date(2026, 9, 1))  # due 1 Oct
    inv2 = services.issue(services.invoice_delivery(ship(order, {20: 1})), issue_date=date(2026, 11, 1))
    r = services.receivables(today=date(2026, 11, 15))
    [row] = r["customers"]
    assert row["d60"] == "11500.00" and row["current"] == "6900.00" and row["total"] == "18400.00"
    services.record_payment(inv, D("11500"))
    assert services.receivables(today=date(2026, 11, 15))["totals"]["d60"] == "0.00"
    assert inv2.balance == D("6900.00")


def test_tax_summary(order, po):
    services.issue(services.invoice_delivery(ship(order, {10: 4, 20: 2})), issue_date=date(2026, 11, 5))
    services.bill_from_po(po, "MBT-1001", date(2026, 11, 4))
    t = services.tax_summary(2026, 11)
    assert t["output_vat"] == "7800.00" and t["input_vat"] == "4500.00" and t["vat_payable"] == "3300.00"
    assert t["withheld_from_suppliers"] == "900.00" and t["invoices"][0]["tin"] == "0012345678"
    assert services.tax_summary(2026, 10)["sales"] == "0.00"


def test_api_flow(client, order, po):
    d = ship(order, {10: 4, 20: 2})
    assert client.get("/api/finance/to-invoice/").json()["deliveries"][0]["value"] == "52000.00"
    r = client.post("/api/invoices/", {"delivery": d.id}, format="json")
    assert r.status_code == 201, r.json()
    inv = r.json()
    assert inv["payment_status"] == "draft" and inv["total"] == "59800.00"
    r = client.post(f"/api/invoices/{inv['id']}/lines/", {"description": "Delivery and installation",
                                                          "quantity": "1", "unit_price": "2000"}, format="json")
    assert r.json()["subtotal"] == "54000.00"
    r = client.post(f"/api/invoices/{inv['id']}/issue/", {"fiscal_receipt_no": "FS-0042"}, format="json")
    assert r.json()["number"] == "INV-00001" and r.json()["expected_withholding"] == "1620.00"
    assert client.delete(f"/api/invoices/{inv['id']}/").status_code == 400
    r = client.post(f"/api/invoices/{inv['id']}/payments/", {"amount": "60480", "withholding": "1620",
                                                             "withholding_receipt_no": "WH-1"}, format="json")
    assert r.status_code == 201 and r.json()["payment_status"] == "paid"
    r = client.post(f"/api/invoices/{inv['id']}/payments/", {"amount": "5"}, format="json")
    assert r.status_code == 400 and "more than" in r.json()["detail"][0]
    r = client.post("/api/invoices/", {"advance_for": order.id, "advance_pct": "0.3"}, format="json")
    assert r.json()["subtotal"] == "15600.00" and r.json()["kind"] == "advance"
    assert client.delete(f"/api/invoices/{r.json()['id']}/").status_code == 204
    r = client.post("/api/supplier-bills/", {"purchase_order": po.id, "supplier_invoice_no": "MBT-1"}, format="json")
    assert r.status_code == 201 and r.json()["payable"] == "33600.00"
    r = client.post(f"/api/supplier-bills/{r.json()['id']}/payments/", {"amount": "33600"}, format="json")
    assert r.json()["balance"] == "0.00"
    assert client.get("/api/finance/aging/receivables/").json()["totals"]["total"] == "0.00"
    assert client.get("/api/finance/tax/?year=2026&month=13").status_code == 400
    assert D(client.get("/api/finance/settings/").json()["withholding_rate"]) == D("0.03")
