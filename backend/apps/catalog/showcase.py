"""A made-up but realistic month in the factory, so every screen has something to show.

Seven customers with orders at every stage (quotes, deposits, production, inspection,
delivery, installation, invoices paid and overdue), purchase orders and supplier bills,
station inspections and machine service history. Everything is dated relative to today.
All names, TINs and prices are invented. Load it on an empty database with
``manage.py seed_showcase``."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog import demo_data
from apps.catalog.models import ProductTemplate
from apps.dispatch import services as dispatch
from apps.dispatch.models import Delivery, Installation
from apps.finance import services as finance
from apps.finance.models import Invoice, Payment, SupplierBill, SupplierPayment
from apps.inventory.models import Location, StockMove
from apps.inventory.services import issue, on_hand
from apps.maintenance import services as maintenance
from apps.maintenance.models import MaintenanceLog, MaintenancePlan
from apps.production.models import NonConformance, TimeLog, WorkOrder, WorkOrderOperation
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierItem
from apps.purchasing.services import receive_line
from apps.quality import services as quality
from apps.quality.models import Checklist, Inspection
from apps.sales.models import Customer, SalesOrder, SalesOrderLine
from apps.sales.services import confirm, price_line

D = Decimal
STAFF = [
    ("abebe", "Abebe", "Girma"), ("tigist", "Tigist", "Bekele"), ("meron", "Meron", "Haile"),
    ("yonas", "Yonas", "Tadesse"), ("selam", "Selam", "Worku"),
]
CUSTOMERS = {
    "tsehay": dict(name="Tsehay Software PLC", tin="0061234507", vat_reg_no="11223344", withholds_tax=True,
                   phone="0911 223 344", address="Kazanchis, Africa Avenue, 6th floor, Addis Ababa"),
    "bole": dict(name="Bole Rise Apartments", tin="0072345618", vat_reg_no="22334455", withholds_tax=True,
                 phone="0912 334 455", address="Bole Atlas, behind the bank, Addis Ababa"),
    "yeka": dict(name="Yeka Valley Academy", tin="0083456729", phone="0913 445 566",
                 address="Yeka sub-city, Woreda 9, Addis Ababa"),
    "hiwot": dict(name="W/ro Hiwot Tesfaye", phone="0914 556 677", address="CMC, Sunshine villas no. 41"),
    "kidus": dict(name="Kidus Family Clinic", tin="0094567830", vat_reg_no="33445566", withholds_tax=True,
                  phone="0915 667 788", address="Piassa, Churchill Road, Addis Ababa"),
    "dawit": dict(name="Ato Dawit Alemu", phone="0916 778 899", address="Gerji, condominium block 12"),
    "sunrise": dict(name="Sunrise Guest House", tin="0105678941", vat_reg_no="44556677", withholds_tax=False,
                    phone="0462 201 122", address="Lake road, Hawassa", city="Hawassa"),
}


class Clock:
    def __init__(self):
        self.today = timezone.localdate()

    def day(self, ago):
        return self.today - timedelta(days=ago)

    def at(self, ago, hour=9, minute=0):
        return timezone.make_aware(datetime.combine(self.day(ago), time(hour, minute)))


def load():
    if SalesOrder.objects.exists():
        raise ValidationError("The showcase needs an empty database: there are already sales orders.")
    demo_data.load()
    demo_data.load_stock()
    demo_data.load_suppliers()
    demo_data.load_machines()
    demo_data.load_checklists()
    c = Clock()
    staff = _staff()
    cust = {k: Customer.objects.create(**v) for k, v in CUSTOMERS.items()}
    _purchasing(c, staff)
    _maintenance(c)
    # oldest first, so invoice numbers run in date order
    _yeka(c, cust["yeka"], staff)
    _tsehay(c, cust["tsehay"], staff)
    _bole(c, cust["bole"], staff)
    _hiwot(c, cust["hiwot"], staff)
    _kidus(c, cust["kidus"], staff)
    _quote(c, cust["dawit"], 3, [("BASE-CAB", {"W": 600, "front": "ven", "drawers": 0, "handle": "knob",
                                               "board": "PLY-BIR-18"}, 2)], "Kitchen corner, oak veneer doors")
    _quote(c, cust["sunrise"], 1, [("WARDROBE", {"W": 1000, "H": 2000, "board": "CHB-OAK-18", "shelves": 2}, 10)],
           "Ten guest rooms, delivery to Hawassa to be priced separately")


# --- helpers -----------------------------------------------------------------------------------

def _staff():
    users = {}
    for username, first, last in STAFF:
        u, created = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last})
        if created:
            u.set_unusable_password()
            u.save()
        users[username] = u
    return users


def _order(c, customer, ago, lines, due_in, notes="", site=""):
    o = SalesOrder.objects.create(customer=customer, order_date=c.day(ago), due_date=c.day(-due_in), notes=notes,
                                  site_address=site or customer.address)
    for seq, (code, cfg, qty) in enumerate(lines, start=1):
        line = SalesOrderLine.objects.create(order=o, sequence=seq * 10, template=ProductTemplate.objects.get(code=code),
                                             configuration=cfg, quantity=qty)
        price_line(line)
    return o


def _quote(c, customer, ago, lines, notes):
    return _order(c, customer, ago, lines, due_in=30, notes=notes)


def _confirm(o):
    wos = confirm(o)
    return {wo.sales_line.sequence: wo for wo in wos}


def _run(op, ago, hour, operator, factor=1.0, finish=True):
    """Book one finished (or paused) spell of work on a step, back-dated."""
    start = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=ago), time(hour)))
    minutes = float(op.planned_minutes) * factor
    TimeLog.objects.create(operation=op, operator=operator, started_at=start,
                           ended_at=start + timedelta(minutes=minutes), good_qty=op.work_order.quantity if finish else 0)
    op.status = WorkOrderOperation.Status.DONE if finish else WorkOrderOperation.Status.PAUSED
    op.save(update_fields=["status"])
    wo = op.work_order
    wo.status = WorkOrder.Status.DONE if not wo.operations.exclude(status="done").exists() else WorkOrder.Status.IN_PROGRESS
    wo.save(update_fields=["status"])


def _build(wo, first_day, operators, factors=(1.1, 0.95, 1.05, 1.2, 0.9, 1.0, 0.85), upto=None):
    """Work every step (or the first ``upto``), one or two steps a day from ``first_day`` days ago."""
    ops = list(wo.operations.order_by("sequence"))[:upto]
    for i, op in enumerate(ops):
        _run(op, max(first_day - i // 2, 0), 8 + (i % 2) * 4, operators[i % len(operators)], factors[i % len(factors)])
    _issue_materials(wo)


def _issue_materials(wo):
    main = Location.objects.get(code="MAIN")
    for m in wo.materials.select_related("item"):
        if StockMove.objects.filter(work_order=wo, item=m.item).exists():
            continue
        qty = m.planned_qty
        lot = None
        if m.item.track_lots:
            lot = next((l for l in m.item.lots.order_by("id") if on_hand(m.item, main, l) >= qty), None)
            if lot is None:
                continue
        if on_hand(m.item, main, lot) >= qty:
            issue(m.item, qty, main, work_order=wo, lot=lot)


def _answers(checklist, fail=None, note="", values=None):
    out = {}
    for it in checklist.items.all():
        if it.kind == "measure":
            out[it.id] = {"value": (values or {}).get(it.sequence, it.target)}
        else:
            out[it.id] = {"passed": it.sequence != fail, "note": note if it.sequence == fail else ""}
    return out


def _inspect(wo, checklist, ago, user, operation=None, fail=None, note="", failed_qty=0, values=None, hour=15):
    insp = quality.record(wo, checklist, _answers(checklist, fail, note, values), operation=operation,
                          failed_qty=failed_qty, notes=note, user=user)
    when = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=ago), time(hour)))
    Inspection.objects.filter(pk=insp.pk).update(created_at=when)
    if insp.non_conformance_id:
        NonConformance.objects.filter(pk=insp.non_conformance_id).update(created_at=when)
    return insp


def _final(wo, ago, user, **kw):
    return _inspect(wo, quality.final_checklist(), ago, user, **kw)


def _ship(c, order, lines, ago, received_by, install=True, crew="", driver="Kebede", vehicle="3-A41722"):
    d = dispatch.create_delivery(order, lines, c.day(ago), install_required=install, driver=driver, vehicle=vehicle)
    dispatch.dispatch(d)
    dispatch.deliver(d, received_by, install_date=c.day(ago - 1) if install else None, crew=crew)
    Delivery.objects.filter(pk=d.pk).update(dispatched_at=c.at(ago, 8), delivered_at=c.at(ago, 11))
    d.refresh_from_db()
    return d


def _install(c, d, ago, signed_by, snags="", return_in=None):
    job = d.installations.get()
    job, follow = dispatch.complete_installation(job, signed_by, snags=snags,
                                                 return_date=c.day(-return_in) if return_in is not None else None)
    Installation.objects.filter(pk=job.pk).update(completed_at=c.at(ago, 16))
    return follow


def _invoice(c, inv, ago, fs=""):
    return finance.issue(inv, issue_date=c.day(ago), fiscal_receipt_no=fs)


def _pay(c, inv, ago, amount=None, method="bank", reference="", withholding=D(0), receipt=""):
    if amount is None:
        amount = inv.balance - withholding
    p = finance.record_payment(inv, amount, withholding, on=c.day(ago), method=method, reference=reference,
                               withholding_receipt_no=receipt)
    return p


# --- purchasing and maintenance ------------------------------------------------------------------

def _po(c, supplier, ago, lines, status="sent"):
    sup = Supplier.objects.get(name=supplier)
    po = PurchaseOrder.objects.create(supplier=sup, order_date=c.day(ago), status=status,
                                      expected_date=c.day(ago - sup.lead_time_days))
    for code, packs in lines:
        si = SupplierItem.objects.get(supplier=sup, item__code=code)
        PurchaseOrderLine.objects.create(order=po, item=si.item, pack_name=si.pack_name, pack_qty=si.pack_qty,
                                         packs=packs, price_per_pack=si.price_per_pack)
    return po


def _receive(po, lot_prefix, share=None):
    main = Location.objects.get(code="MAIN")
    for i, line in enumerate(po.lines.select_related("item")):
        packs = line.packs if share is None else share.get(line.item.code, 0)
        if packs:
            receive_line(line, packs, main, lot_code=f"{lot_prefix}-{i + 1:02d}" if line.item.track_lots else "")


def _purchasing(c, staff):
    boards = _po(c, "Addis Board Trading", 45, [("MDF-WHT-18", 40), ("CHB-OAK-18", 60), ("HDF-WHT-3", 30),
                                                ("MDF-RAW-18", 10)])
    _receive(boards, "L-ABT-0412")
    bill = finance.bill_from_po(boards, "ABT/2026/0412", c.day(40))
    finance.pay_bill(bill, bill.payable, on=c.day(20), method="bank", reference="CBE FT 2026-1187")

    hardware = _po(c, "Merkato Hardware Supply", 30, [("SLD-450", 80), ("HNG-SC-110", 150), ("EB-22-2", 6),
                                                      ("EB-22-04", 8), ("GLIDE-20", 200), ("HDL-BAR-160", 60)])
    _receive(hardware, "L-MHS-0977")
    finance.bill_from_po(hardware, "MHS-0977", c.day(27))

    paint = _po(c, "Ethio Paints and Finishes", 5, [("LAC-PU", 3), ("LAC-CLR", 1), ("GLUE-PVA", 4)])
    _receive(paint, "L-EPF-2231", share={"LAC-PU": 2, "GLUE-PVA": 4})

    _po(c, "Kality Panel Imports", 3, [("CHB-OAK-18", 60), ("PLY-BIR-18", 15)])
    # reorder levels that the open orders push below, so the shortage list has something to suggest
    from apps.catalog.models import Item
    for code, level in [("CBL-GROM", 40), ("RAIL-25", 60), ("HDL-KNOB", 160), ("LAC-CLR", 30)]:
        Item.objects.filter(code=code).update(reorder_level=D(level))


def _maintenance(c):
    for code, task, ago in [("SAW-01", "Change main and scoring blades", 34), ("EDGE-01", "Sharpen or replace trimming knives", 26),
                            ("COMP-01", "Change compressor oil and oil filter", 61), ("CNC-01", "Clean vacuum table and check pump filter", 19)]:
        plan = MaintenancePlan.objects.get(machine__code=code, task=task)
        maintenance.complete_plan(plan, done_by="Yonas Tadesse", notes="Done as planned.", now=c.at(ago, 7, 30))
    edge = maintenance.report_breakdown(MaintenancePlan.objects.get(machine__code="EDGE-01", task__startswith="Clean").machine,
                                        "Glue pot heater not reaching temperature")
    MaintenanceLog.objects.filter(pk=edge.pk).update(reported_at=c.at(9, 10), closed_at=c.at(9, 15),
                                                      action_taken="Replaced the glue pot thermostat.",
                                                      done_by="Hailu Electric (outside technician)", parts_cost=D("2800"))
    saw = maintenance.report_breakdown(MaintenancePlan.objects.filter(machine__code="SAW-01").first().machine,
                                       "Scoring blade motor tripping the breaker", machine_down=False)
    MaintenanceLog.objects.filter(pk=saw.pk).update(reported_at=c.at(1, 14))


# --- the customers' orders ---------------------------------------------------------------------

def _tsehay(c, cust, s):
    """Office fit-out: delivered, installed, deposit and final invoice paid (with withholding)."""
    o = _order(c, cust, 40, [("DESK", {"W": 1400, "D": 700, "board": "CHB-OAK-18", "drawers": 3}, 8),
                             ("BOOKSHELF", {"W": 900, "H": 1800, "board": "CHB-OAK-18", "shelves": 4}, 4)],
               due_in=-20, notes="Open-plan office, 6th floor. Lift available after 6 pm.")
    wos = _confirm(o)
    adv = _invoice(c, finance.advance_invoice(o, D("0.5")), 39, "FS-00211")
    _pay(c, adv, 37, reference="Awash FT 26-03311")
    _build(wos[10], 32, [s["abebe"], s["tigist"]])
    _build(wos[20], 30, [s["tigist"], s["abebe"]])
    saw = Checklist.objects.get(work_center__code="SAW")
    _inspect(wos[10], saw, 32, s["meron"], operation=wos[10].operations.filter(work_center__code="SAW").order_by("sequence").last(), values={10: D("0.5")})
    nc = _final(wos[10], 26, s["meron"], fail=40, note="Scratch on the top of one desk", failed_qty=1)
    rework = WorkOrder.objects.get(pk=nc.non_conformance.rework_order_id)
    _run(rework.operations.get(), 25, 10, s["abebe"], 1.3)
    _final(wos[10], 24, s["meron"])
    _final(wos[20], 24, s["meron"])
    lines = list(o.lines.all())
    d = _ship(c, o, [(l, l.quantity) for l in lines], 22, "Ato Samuel (office manager)", crew="Team A (Yonas)")
    _install(c, d, 21, "Ato Samuel")
    inv = _invoice(c, finance.invoice_delivery(d), 22, "FS-00248")
    wh = finance.expected_withholding(inv)
    _pay(c, inv, 8, withholding=wh, receipt="WHT-TS-0031", reference="Dashen FT 26-11873")


def _bole(c, cust, s):
    """Kitchens and wardrobes for six flats: kitchens installed with a snag, wardrobes waiting for final inspection."""
    o = _order(c, cust, 25, [("BASE-CAB", {"W": 800, "board": "MDF-WHT-18", "drawers": 3, "handle": "bar"}, 12),
                             ("WARDROBE", {"W": 1200, "H": 2100, "board": "CHB-OAK-18", "shelves": 2}, 4)],
               due_in=3, notes="Units 2A to 4B. Site contact: Ato Getachew 0912 000 111.",
               site="Bole Atlas, Bole Rise building B, Addis Ababa")
    wos = _confirm(o)
    adv = _invoice(c, finance.advance_invoice(o, D("0.4")), 21, "FS-00251")
    _pay(c, adv, 19, method="cheque", reference="CBE chq 00451872")
    _build(wos[10], 16, [s["tigist"], s["abebe"]])
    edge = Checklist.objects.get(work_center__code="EDGE")
    _inspect(wos[10], edge, 15, s["meron"], operation=wos[10].operations.filter(work_center__code="EDGE").order_by("sequence").last(), fail=30,
             note="Glue squeeze-out on two panels, cleaned at the station")
    _final(wos[10], 10, s["meron"])
    _build(wos[20], 6, [s["abebe"], s["tigist"]])
    cab = o.lines.get(sequence=10)
    d = _ship(c, o, [(cab, cab.quantity)], 8, "Ato Getachew (site engineer)", crew="Team B (Dereje)")
    _install(c, d, 7, "Ato Getachew", snags="Two drawer fronts misaligned in unit 4B", return_in=1)
    inv = _invoice(c, finance.invoice_delivery(d), 8, "FS-00264")
    _pay(c, inv, 3, amount=D("50000"), reference="Abyssinia FT 26-55120")


def _yeka(c, cust, s):
    """School library shelves: delivered two months ago, invoice part paid and overdue."""
    o = _order(c, cust, 80, [("BOOKSHELF", {"W": 900, "H": 1800, "board": "MDF-WHT-18", "shelves": 4}, 20)],
               due_in=-65, notes="Library, ground floor.")
    wos = _confirm(o)
    _build(wos[10], 72, [s["abebe"], s["tigist"]])
    _final(wos[10], 69, s["meron"])
    line = o.lines.get()
    d = _ship(c, o, [(line, line.quantity)], 68, "W/ro Almaz (librarian)", install=False)
    inv = _invoice(c, finance.invoice_delivery(d), 68, "FS-00163")
    _pay(c, inv, 30, amount=(inv.total / 2).quantize(D("1")), method="bank", reference="CBE FT 26-07714")


def _hiwot(c, cust, s):
    """A private home: wardrobe in the spray booth now, kitchen cabinets paused at the edgebander."""
    o = _order(c, cust, 12, [("WARDROBE", {"W": 1800, "H": 2200, "board": "MDF-WHT-18", "front": "lac", "shelves": 3}, 1),
                             ("BASE-CAB", {"W": 600, "board": "MDF-WHT-18", "front": "lac", "drawers": 0, "handle": "gola"}, 3)],
               due_in=10, notes="White lacquer, satin. Customer will collect the handles sample on Friday.")
    wos = _confirm(o)
    adv = _invoice(c, finance.advance_invoice(o, D("0.5")), 7, "FS-00266")
    _pay(c, adv, 7, method="cash", reference="Cash at showroom")
    _build(wos[10], 6, [s["abebe"], s["tigist"]], upto=4)
    spray = wos[10].operations.filter(work_center__code="SPRAY").order_by("sequence").last()
    spray.status = WorkOrderOperation.Status.RUNNING
    spray.save(update_fields=["status"])
    TimeLog.objects.create(operation=spray, operator=s["tigist"], started_at=timezone.now() - timedelta(minutes=35))
    cnc = Checklist.objects.get(work_center__code="CNC")
    _inspect(wos[10], cnc, 4, s["meron"], operation=wos[10].operations.filter(work_center__code="CNC").order_by("sequence").last(),
             values={10: D("37.2"), 20: D("12.1")})
    cab_ops = list(wos[20].operations.order_by("sequence"))
    _run(cab_ops[0], 2, 9, s["abebe"], 1.0)
    _run(cab_ops[1], 1, 14, s["tigist"], 0.5, finish=False)
    _issue_materials(wos[20])


def _kidus(c, cust, s):
    """Clinic desks: confirmed, released to the floor, deposit invoice still a draft."""
    o = _order(c, cust, 6, [("DESK", {"W": 1200, "D": 650, "board": "CHB-OAK-18", "drawers": 0, "grommet": "yes"}, 6)],
               due_in=14, notes="Reception and consulting rooms.")
    _confirm(o)
    finance.advance_invoice(o, D("0.5"))
