"""Invoicing, receipts, supplier bills and the reports the accountant needs each month."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.models import CostSettings
from apps.dispatch.models import Delivery
from apps.purchasing.models import PurchaseOrder
from apps.sales.models import SalesOrder

from .models import Q2, FinanceSettings, Invoice, InvoiceLine, Payment, SupplierBill, SupplierPayment, _next

CENT = Decimal("0.01")
BILLABLE_ORDERS = ("confirmed", "drafting", "production", "finishing", "dispatched", "installed")


def _s(v):
    return str(Decimal(v).quantize(Q2))


def describe(sales_line):
    """"Base cabinet (800 x 720 x 560 mm, drawers 2)", the way the configurator shows it."""
    c = {k: (int(v) if isinstance(v, float) and v.is_integer() else v) for k, v in sales_line.configuration.items()}
    dims = " x ".join(str(c[k]) for k in ("W", "H", "D") if k in c)
    rest = [f"{k.replace('_', ' ')} {v}" for k, v in c.items() if k not in ("W", "H", "D")]
    cfg = ", ".join(([f"{dims} mm"] if dims else []) + rest)
    text = sales_line.description or sales_line.template.name
    return f"{text} ({cfg})" if cfg else text


# --- Customer invoices -------------------------------------------------------------------------

def _new_invoice(order, kind, user=None, delivery=None):
    return Invoice.objects.create(customer=order.customer, order=order, kind=kind, delivery=delivery,
                                  vat_rate=CostSettings.current().vat_rate, created_by=user)


@transaction.atomic
def advance_invoice(order, pct=None, user=None):
    """Draft a deposit invoice for a confirmed order."""
    if order.status not in BILLABLE_ORDERS:
        raise ValidationError(f"{order.number} is not a confirmed order.")
    pct = Decimal(pct) if pct is not None else FinanceSettings.current().advance_pct
    if not Decimal(0) < pct <= 1:
        raise ValidationError("The advance must be more than 0% and at most 100% of the order.")
    already = sum((i.subtotal for i in order.invoices.filter(kind=Invoice.Kind.ADVANCE)), Decimal(0))
    amount = (order.subtotal * pct).quantize(Q2)
    if already + amount > order.subtotal:
        raise ValidationError(f"Advances for {order.number} would be more than the order value.")
    inv = _new_invoice(order, Invoice.Kind.ADVANCE, user)
    InvoiceLine.objects.create(invoice=inv, description=f"Advance payment {pct * 100:.0f}% on order {order.number}",
                               quantity=1, unit_price=amount)
    return inv


def advance_left(advance):
    """Part of an issued advance invoice (ex VAT) not yet deducted on a later invoice."""
    used = sum((-l.amount for l in advance.deductions.all()), Decimal(0))
    return advance.subtotal - used


@transaction.atomic
def invoice_delivery(delivery, user=None):
    """Draft the invoice for what went out on a delivery note, less any advance still to deduct."""
    if delivery.status not in (Delivery.Status.OUT, Delivery.Status.DELIVERED):
        raise ValidationError(f"{delivery.number} has not left the factory yet.")
    if Invoice.objects.filter(delivery=delivery).exists():
        raise ValidationError(f"{delivery.number} is already invoiced.")
    inv = _new_invoice(delivery.order, Invoice.Kind.STANDARD, user, delivery=delivery)
    seq = 0
    for dl in delivery.lines.select_related("sales_line__template"):
        seq += 10
        InvoiceLine.objects.create(invoice=inv, sequence=seq, description=describe(dl.sales_line),
                                   quantity=dl.quantity, unit_price=dl.sales_line.unit_price, sales_line=dl.sales_line)
    goods = inv.subtotal
    for adv in delivery.order.invoices.filter(kind=Invoice.Kind.ADVANCE, status=Invoice.Status.ISSUED).order_by("id"):
        take = min(advance_left(adv), goods)
        if take <= 0:
            continue
        seq += 10
        InvoiceLine.objects.create(invoice=inv, sequence=seq, description=f"Less advance invoiced on {adv.number}",
                                   quantity=1, unit_price=-take, advance=adv)
        goods -= take
    return inv


@transaction.atomic
def issue(inv, issue_date=None, fiscal_receipt_no=""):
    """Give the invoice its number and lock it."""
    if inv.status != Invoice.Status.DRAFT:
        raise ValidationError(f"{inv} is already issued.")
    if not inv.lines.exists():
        raise ValidationError("Add at least one line before issuing.")
    if inv.subtotal < 0:
        raise ValidationError("The invoice total cannot be negative.")
    for line in inv.lines.filter(advance__isnull=False):
        if advance_left(line.advance) < 0:
            raise ValidationError(f"{line.advance.number} has already been deducted on another invoice.")
    inv.issue_date = issue_date or date.today()
    inv.due_date = inv.issue_date + timedelta(days=FinanceSettings.current().payment_terms_days)
    inv.vat_rate = CostSettings.current().vat_rate
    inv.fiscal_receipt_no = fiscal_receipt_no or inv.fiscal_receipt_no
    inv.number = _next(Invoice, "INV-")
    inv.status = Invoice.Status.ISSUED
    inv.save()
    return inv


def expected_withholding(inv):
    """Withholding the customer is likely to keep back, if they are a withholding agent."""
    fs = FinanceSettings.current()
    if not inv.customer.withholds_tax or inv.subtotal < fs.withholding_threshold:
        return Decimal(0)
    return (inv.subtotal * fs.withholding_rate).quantize(Q2)


@transaction.atomic
def record_payment(inv, amount, withholding=Decimal(0), on=None, user=None, **extra):
    if inv.status != Invoice.Status.ISSUED:
        raise ValidationError("Issue the invoice before recording a payment.")
    amount, withholding = Decimal(amount), Decimal(withholding)
    if amount < 0 or withholding < 0 or amount + withholding <= 0:
        raise ValidationError("Enter the amount received.")
    if withholding and not extra.get("withholding_receipt_no"):
        raise ValidationError("Enter the withholding receipt number the customer gave you.")
    if amount + withholding > inv.balance + CENT:
        raise ValidationError(f"That is more than the {_s(inv.balance)} ETB still owed on {inv.number}.")
    return Payment.objects.create(invoice=inv, amount=amount, withholding=withholding, date=on or date.today(),
                                  created_by=user, **extra)


def to_invoice():
    """Delivery notes not yet invoiced, and confirmed orders with nothing invoiced yet (for a deposit)."""
    deliveries = (Delivery.objects.filter(status__in=(Delivery.Status.OUT, Delivery.Status.DELIVERED), invoice__isnull=True)
                  .select_related("order__customer").prefetch_related("lines__sales_line"))
    rows = [{"delivery": d.id, "number": d.number, "order": d.order.number, "order_id": d.order_id,
             "customer": d.order.customer.name, "date": (d.delivered_at or d.dispatched_at).date() if (d.delivered_at or d.dispatched_at) else d.scheduled_date,
             "status": d.get_status_display(),
             "value": _s(sum((l.quantity * l.sales_line.unit_price for l in d.lines.all()), Decimal(0)))}
            for d in deliveries]
    orders = (SalesOrder.objects.filter(status__in=BILLABLE_ORDERS, invoices__isnull=True)
              .select_related("customer").prefetch_related("lines").order_by("order_date", "id"))
    pct = FinanceSettings.current().advance_pct
    return {"deliveries": rows,
            "orders": [{"order_id": o.id, "order": o.number, "customer": o.customer.name, "date": o.order_date,
                        "status": o.get_status_display(), "value": _s(o.subtotal), "advance_pct": str(pct),
                        "advance": _s(o.subtotal * pct)} for o in orders if o.subtotal > 0]}


# --- Supplier bills ----------------------------------------------------------------------------

def received_value(po):
    return sum(((l.received_packs * l.price_per_pack).quantize(Q2) for l in po.lines.all()), Decimal(0))


def unbilled_value(po):
    return received_value(po) - sum((b.subtotal for b in po.bills.all()), Decimal(0))


def to_bill():
    pos = PurchaseOrder.objects.filter(status__in=("partial", "received")).select_related("supplier").prefetch_related("lines", "bills")
    return [{"purchase_order": po.id, "number": po.number, "supplier": po.supplier.name,
             "received": _s(received_value(po)), "unbilled": _s(unbilled_value(po))}
            for po in pos if unbilled_value(po) > 0]


def withholding_for(subtotal):
    fs = FinanceSettings.current()
    if not fs.we_withhold or subtotal < fs.withholding_threshold:
        return Decimal(0)
    return (subtotal * fs.withholding_rate).quantize(Q2)


@transaction.atomic
def bill_from_po(po, supplier_invoice_no, bill_date=None, subtotal=None, user=None, notes=""):
    """Book the supplier's invoice for goods received on a purchase order."""
    unbilled = unbilled_value(po)
    subtotal = unbilled if subtotal in (None, "") else Decimal(subtotal)
    if subtotal <= 0:
        raise ValidationError(f"Nothing received on {po.number} is waiting to be billed.")
    if subtotal > unbilled + CENT:
        raise ValidationError(f"Only {_s(unbilled)} ETB received on {po.number} has not been billed yet.")
    return create_bill(po.supplier, supplier_invoice_no, subtotal, bill_date, user=user, purchase_order=po, notes=notes)


def create_bill(supplier, supplier_invoice_no, subtotal, bill_date=None, user=None, **extra):
    if not supplier_invoice_no.strip():
        raise ValidationError("Enter the supplier's invoice number.")
    if SupplierBill.objects.filter(supplier=supplier, supplier_invoice_no=supplier_invoice_no.strip()).exists():
        raise ValidationError(f"Invoice {supplier_invoice_no} from {supplier.name} is already booked.")
    subtotal = Decimal(subtotal).quantize(Q2)
    bill_date = bill_date or date.today()
    vat = (subtotal * CostSettings.current().vat_rate).quantize(Q2) if supplier.vat_registered else Decimal(0)
    return SupplierBill.objects.create(
        supplier=supplier, supplier_invoice_no=supplier_invoice_no.strip(), bill_date=bill_date,
        due_date=bill_date + timedelta(days=FinanceSettings.current().payment_terms_days),
        subtotal=subtotal, vat=vat, withholding=withholding_for(subtotal), created_by=user, **extra)


@transaction.atomic
def pay_bill(bill, amount, on=None, user=None, **extra):
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Enter the amount paid.")
    if amount > bill.balance + CENT:
        raise ValidationError(f"That is more than the {_s(bill.balance)} ETB still owed on {bill.number}.")
    return SupplierPayment.objects.create(bill=bill, amount=amount, date=on or date.today(), created_by=user, **extra)


# --- Reports -----------------------------------------------------------------------------------

BUCKETS = [("current", "Not yet due"), ("d30", "1–30 days late"), ("d60", "31–60 days late"),
           ("d90", "61–90 days late"), ("over90", "Over 90 days late")]


def _bucket(days_late):
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "d30"
    if days_late <= 60:
        return "d60"
    if days_late <= 90:
        return "d90"
    return "over90"


def _aging(docs, party, today):
    parties = {}
    for doc, name, due in docs:
        bal = doc.balance
        if bal <= CENT / 2:
            continue
        p = parties.setdefault(name, {"name": name, **{k: Decimal(0) for k, _ in BUCKETS}, "total": Decimal(0), "documents": []})
        late = (today - due).days
        p[_bucket(late)] += bal
        p["total"] += bal
        p["documents"].append({"id": doc.id, "number": doc.number, "due_date": due, "days_late": max(late, 0),
                               "balance": _s(bal)})
    rows = sorted(parties.values(), key=lambda r: -r["total"])
    totals = {k: _s(sum((r[k] for r in rows), Decimal(0))) for k, _ in BUCKETS + [("total", "")]}
    for r in rows:
        for k, _ in BUCKETS + [("total", "")]:
            r[k] = _s(r[k])
    return {"buckets": [{"key": k, "label": l} for k, l in BUCKETS], party: rows, "totals": totals}


def receivables(today=None):
    today = today or date.today()
    invs = Invoice.objects.filter(status=Invoice.Status.ISSUED).select_related("customer").prefetch_related("lines", "payments")
    return _aging(((i, i.customer.name, i.due_date) for i in invs), "customers", today)


def payables(today=None):
    today = today or date.today()
    bills = SupplierBill.objects.select_related("supplier").prefetch_related("payments")
    return _aging(((b, b.supplier.name, b.due_date) for b in bills), "suppliers", today)


def tax_summary(year, month):
    """Monthly figures for the VAT and withholding returns. Your accountant files these."""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    invs = list(Invoice.objects.filter(status=Invoice.Status.ISSUED, issue_date__gte=start, issue_date__lt=end)
                .select_related("customer").prefetch_related("lines"))
    bills = list(SupplierBill.objects.filter(bill_date__gte=start, bill_date__lt=end).select_related("supplier"))
    receipts = Payment.objects.filter(date__gte=start, date__lt=end, withholding__gt=0).select_related("invoice__customer")
    sales = sum((i.subtotal for i in invs), Decimal(0))
    out_vat = sum((i.vat for i in invs), Decimal(0))
    purchases = sum((b.subtotal for b in bills), Decimal(0))
    in_vat = sum((b.vat for b in bills), Decimal(0))
    return {
        "period": start.strftime("%Y-%m"),
        "sales": _s(sales), "output_vat": _s(out_vat), "purchases": _s(purchases), "input_vat": _s(in_vat),
        "vat_payable": _s(out_vat - in_vat),
        "withheld_from_suppliers": _s(sum((b.withholding for b in bills), Decimal(0))),
        "withheld_by_customers": _s(sum((p.withholding for p in receipts), Decimal(0))),
        "invoices": [{"id": i.id, "number": i.number, "date": i.issue_date, "customer": i.customer.name,
                      "tin": i.customer.tin, "fs_no": i.fiscal_receipt_no, "subtotal": _s(i.subtotal), "vat": _s(i.vat)}
                     for i in sorted(invs, key=lambda i: i.number)],
        "bills": [{"id": b.id, "number": b.number, "date": b.bill_date, "supplier": b.supplier.name,
                   "tin": b.supplier.tin, "supplier_invoice_no": b.supplier_invoice_no, "subtotal": _s(b.subtotal),
                   "vat": _s(b.vat), "withholding": _s(b.withholding)} for b in bills],
        "withholding_receipts": [{"payment": p.number, "date": p.date, "customer": p.invoice.customer.name,
                                  "invoice": p.invoice.number, "receipt_no": p.withholding_receipt_no,
                                  "amount": _s(p.withholding)} for p in receipts],
    }
