import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Aging, AgingRow, api, ApiError, InvoiceDetail, InvoiceRow, Page, PaymentStatus, SupplierBill, TaxSummary, ToBill, ToInvoice } from "../api";
import { dec2, today } from "../format";

export const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Could not reach the server.");
export const etb = (v: string | number) => dec2(v);

export const PAY_LABEL: Record<PaymentStatus, string> = {
  draft: "Draft", unpaid: "Not paid", part_paid: "Part paid", paid: "Paid", overdue: "Overdue",
};
export const payChip = (s: PaymentStatus) => (s === "paid" ? "okc" : s === "overdue" ? "bad" : "");

type Tab = "to-invoice" | "invoices" | "bills" | "reports";
const TABS: [Tab, string][] = [["to-invoice", "To invoice"], ["invoices", "Invoices"], ["bills", "Supplier bills"], ["reports", "Balances and tax"]];

export default function Finance() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "to-invoice";
  return (
    <section className="stack">
      <div>
        <h2>Finance</h2>
        <p className="lead">Invoice what has been delivered, take deposits on confirmed orders, record what customers pay
          and what we owe suppliers. Amounts are in ETB; VAT and withholding follow the rates in finance settings,
          which your accountant should confirm.</p>
      </div>
      <div className="tabs small-tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setParams({ tab: k })}>{label}</button>
        ))}
      </div>
      {tab === "to-invoice" && <ToInvoiceTab />}
      {tab === "invoices" && <InvoicesTab />}
      {tab === "bills" && <BillsTab />}
      {tab === "reports" && <ReportsTab />}
    </section>
  );
}

function ToInvoiceTab() {
  const nav = useNavigate();
  const [data, setData] = useState<ToInvoice | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<ToInvoice>("/api/finance/to-invoice/").then(setData).catch((e) => setError(errText(e))); }, []);
  const create = async (body: unknown) => {
    setBusy(true); setError("");
    try { const inv = await api<InvoiceDetail>("/api/invoices/", { method: "POST", body }); nav(`/finance/invoices/${inv.id}`); }
    catch (e) { setError(errText(e)); setBusy(false); }
  };
  if (!data) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;
  return (
    <div className="stack">
      {error && <p className="error">{error}</p>}
      <div className="panel">
        <h3>Delivered, not yet invoiced</h3>
        {data.deliveries.length === 0 ? <p className="muted">Every delivery note that has left the factory is invoiced.</p> : (
          <div className="tbl"><table>
            <thead><tr><th>Delivery note</th><th>Customer</th><th>Date</th><th className="num">Value ex VAT</th><th /></tr></thead>
            <tbody>{data.deliveries.map((d) => (
              <tr key={d.delivery}>
                <td><Link className="mono" to={`/dispatch/${d.delivery}`}>{d.number}</Link>
                  <div className="small muted">{d.order} · {d.status}</div></td>
                <td>{d.customer}</td>
                <td className="small">{d.date}</td>
                <td className="num">{etb(d.value)}</td>
                <td className="num"><button className="btn" disabled={busy} onClick={() => create({ delivery: d.delivery })}>Draft invoice</button></td>
              </tr>))}
            </tbody>
          </table></div>)}
      </div>
      <div className="panel">
        <h3>Confirmed orders with no invoice yet</h3>
        <p className="small muted">Ask for a deposit with an advance invoice. It is deducted from the invoices for the deliveries later.</p>
        {data.orders.length === 0 ? <p className="muted">No confirmed orders are waiting for a deposit invoice.</p> : (
          <div className="tbl"><table>
            <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th className="num">Order value ex VAT</th><th className="num">Advance</th><th /></tr></thead>
            <tbody>{data.orders.map((o) => (
              <tr key={o.order_id}>
                <td><Link className="mono" to={`/quotes/${o.order_id}`}>{o.order}</Link><div className="small muted">{o.date}</div></td>
                <td>{o.customer}</td>
                <td className="small">{o.status}</td>
                <td className="num">{etb(o.value)}</td>
                <td className="num">{etb(o.advance)}<div className="small muted">{Math.round(Number(o.advance_pct) * 100)}%</div></td>
                <td className="num"><button className="btn ghost" disabled={busy} onClick={() => create({ advance_for: o.order_id })}>Draft advance invoice</button></td>
              </tr>))}
            </tbody>
          </table></div>)}
      </div>
    </div>
  );
}

function InvoicesTab() {
  const [rows, setRows] = useState<InvoiceRow[] | null>(null);
  const [filter, setFilter] = useState<"open" | "all">("open");
  useEffect(() => { api<Page<InvoiceRow>>("/api/invoices/?page_size=200").then((p) => setRows(p.results)); }, []);
  if (!rows) return <p className="muted">Loading…</p>;
  const shown = filter === "open" ? rows.filter((r) => r.payment_status !== "paid") : rows;
  const owed = rows.filter((r) => r.status === "issued").reduce((s, r) => s + Number(r.balance), 0);
  const overdue = rows.filter((r) => r.payment_status === "overdue").reduce((s, r) => s + Number(r.balance), 0);
  return (
    <div className="stack">
      <div className="kpis">
        <div className="kpi"><b>{etb(owed)}</b><span>owed by customers</span></div>
        <div className="kpi"><b className={overdue ? "bad-text" : ""}>{etb(overdue)}</b><span>of it overdue</span></div>
        <div className="kpi"><b>{rows.filter((r) => r.status === "draft").length}</b><span>drafts to issue</span></div>
      </div>
      <div className="panel">
        <div className="tabs small-tabs" role="tablist" aria-label="Which invoices">
          <button role="tab" aria-selected={filter === "open"} onClick={() => setFilter("open")}>Drafts and unpaid</button>
          <button role="tab" aria-selected={filter === "all"} onClick={() => setFilter("all")}>All</button>
        </div>
        {shown.length === 0 ? <p className="muted">No invoices here.</p> : (
          <div className="tbl"><table>
            <thead><tr><th>Invoice</th><th>Customer</th><th>Issued</th><th>Due</th><th className="num">Total</th><th className="num">Still owed</th><th>Status</th></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id}>
                <td><Link className="mono" to={`/finance/invoices/${r.id}`}>{r.number ?? "Draft"}</Link>
                  <div className="small muted">{r.kind_label}{r.order_number && ` · ${r.order_number}`}{r.delivery_number && ` · ${r.delivery_number}`}</div></td>
                <td>{r.customer_name}</td>
                <td className="small">{r.issue_date ?? "–"}</td>
                <td className="small">{r.due_date ?? "–"}</td>
                <td className="num">{etb(r.total)}</td>
                <td className="num">{r.status === "issued" ? etb(r.balance) : "–"}</td>
                <td><span className={`chip ${payChip(r.payment_status)}`}>{PAY_LABEL[r.payment_status]}</span></td>
              </tr>))}
            </tbody>
          </table></div>)}
      </div>
    </div>
  );
}

function BillsTab() {
  const [bills, setBills] = useState<SupplierBill[] | null>(null);
  const [toBill, setToBill] = useState<ToBill[]>([]);
  const [form, setForm] = useState<{ po: number; no: string; date: string; amount: string } | null>(null);
  const [paying, setPaying] = useState<number | null>(null);
  const [pay, setPay] = useState({ amount: "", method: "bank", reference: "" });
  const [flash, setFlash] = useState<{ kind: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [b, t] = await Promise.all([api<Page<SupplierBill>>("/api/supplier-bills/?page_size=200"), api<ToBill[]>("/api/finance/to-bill/")]);
    setBills(b.results); setToBill(t);
  }, []);
  useEffect(() => { load(); }, [load]);

  const book = async (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setBusy(true); setFlash(null);
    try {
      const b = await api<SupplierBill>("/api/supplier-bills/", { method: "POST", body: {
        purchase_order: form.po, supplier_invoice_no: form.no, bill_date: form.date, subtotal: form.amount || null } });
      setFlash({ kind: "ok", text: `${b.number} booked: ${etb(b.total)} with VAT${Number(b.withholding) ? `, less ${etb(b.withholding)} withholding we keep back, so we pay ${etb(b.payable)}` : ""}.` });
      setForm(null); await load();
    } catch (err) { setFlash({ kind: "error", text: errText(err) }); }
    finally { setBusy(false); }
  };
  const payBill = async (e: FormEvent, b: SupplierBill) => {
    e.preventDefault();
    setBusy(true); setFlash(null);
    try {
      const r = await api<SupplierBill>(`/api/supplier-bills/${b.id}/payments/`, { method: "POST", body: pay });
      setFlash({ kind: "ok", text: `Payment recorded on ${r.number}. ${Number(r.balance) > 0 ? `${etb(r.balance)} still owed.` : "Paid in full."}` });
      setPaying(null); await load();
    } catch (err) { setFlash({ kind: "error", text: errText(err) }); }
    finally { setBusy(false); }
  };

  if (!bills) return <p className="muted">Loading…</p>;
  return (
    <div className="stack">
      {flash && <p className={flash.kind} role="status">{flash.text}</p>}
      <div className="panel">
        <h3>Goods received, supplier invoice not booked</h3>
        {toBill.length === 0 ? <p className="muted">Every delivery from a supplier has its invoice booked.</p> : (
          <div className="tbl"><table>
            <thead><tr><th>Purchase order</th><th>Supplier</th><th className="num">Received ex VAT</th><th className="num">Not billed</th><th /></tr></thead>
            <tbody>{toBill.map((t) => (<Fragment key={t.purchase_order}>
              <tr>
                <td><Link className="mono" to={`/purchasing/${t.purchase_order}`}>{t.number}</Link></td>
                <td>{t.supplier}</td>
                <td className="num">{etb(t.received)}</td>
                <td className="num">{etb(t.unbilled)}</td>
                <td className="num">{form?.po !== t.purchase_order &&
                  <button className="btn" onClick={() => setForm({ po: t.purchase_order, no: "", date: today(), amount: "" })}>Book invoice</button>}</td>
              </tr>
              {form?.po === t.purchase_order && (
                <tr key={`f${t.purchase_order}`}><td colSpan={5}>
                  <form className="inline-form" onSubmit={book}>
                    <label className="field"><span>Supplier's invoice no.</span>
                      <input required value={form.no} onChange={(e) => setForm({ ...form, no: e.target.value })} /></label>
                    <label className="field"><span>Invoice date</span>
                      <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
                    <label className="field"><span>Amount ex VAT</span>
                      <input type="number" step="0.01" min="0.01" placeholder={t.unbilled} value={form.amount}
                        onChange={(e) => setForm({ ...form, amount: e.target.value })} /></label>
                    <button className="btn" disabled={busy}>Book</button>
                    <button type="button" className="btn ghost" onClick={() => setForm(null)}>Cancel</button>
                  </form>
                </td></tr>)}
            </Fragment>))}
            </tbody>
          </table></div>)}
      </div>
      <div className="panel">
        <h3>Supplier bills</h3>
        {bills.length === 0 ? <p className="muted">No supplier bills booked yet.</p> : (
          <div className="tbl"><table>
            <thead><tr><th>Bill</th><th>Supplier</th><th>Due</th><th className="num">Total with VAT</th><th className="num">Withheld</th><th className="num">Still to pay</th><th /></tr></thead>
            <tbody>{bills.map((b) => (<Fragment key={b.id}>
              <tr>
                <td><span className="mono">{b.number}</span><div className="small muted">their no. {b.supplier_invoice_no}
                  {b.purchase_order_number && ` · ${b.purchase_order_number}`}</div></td>
                <td>{b.supplier_name}</td>
                <td className="small">{b.due_date}</td>
                <td className="num">{etb(b.total)}</td>
                <td className="num">{Number(b.withholding) ? etb(b.withholding) : "–"}</td>
                <td className="num">{Number(b.balance) > 0 ? etb(b.balance) : <span className="chip okc">Paid</span>}</td>
                <td className="num">{Number(b.balance) > 0 && paying !== b.id &&
                  <button className="btn ghost" onClick={() => { setPaying(b.id); setPay({ amount: b.balance, method: "bank", reference: "" }); }}>Record payment</button>}</td>
              </tr>
              {paying === b.id && (
                <tr key={`p${b.id}`}><td colSpan={7}>
                  <form className="inline-form" onSubmit={(e) => payBill(e, b)}>
                    <label className="field"><span>Amount paid</span>
                      <input type="number" step="0.01" min="0.01" required value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></label>
                    <label className="field"><span>How</span>
                      <select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>
                        <option value="bank">Bank transfer</option><option value="cheque">Cheque</option>
                        <option value="cash">Cash</option><option value="mobile">Mobile money</option></select></label>
                    <label className="field"><span>Reference</span>
                      <input value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></label>
                    <button className="btn" disabled={busy}>Save payment</button>
                    <button type="button" className="btn ghost" onClick={() => setPaying(null)}>Cancel</button>
                  </form>
                </td></tr>)}
            </Fragment>))}
            </tbody>
          </table></div>)}
      </div>
    </div>
  );
}

function AgingTable({ title, data, docLink }: { title: string; data: Aging; docLink: (id: number) => string | null }) {
  const rows: AgingRow[] = data.customers ?? data.suppliers ?? [];
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="panel">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">Nothing outstanding.</p> : (
        <div className="tbl"><table>
          <thead><tr><th>Name</th>{data.buckets.map((b) => <th key={b.key} className="num">{b.label}</th>)}<th className="num">Total</th></tr></thead>
          <tbody>
            {rows.map((r) => (<Fragment key={r.name}>
              <tr>
                <td><button className="linkish" onClick={() => setOpen(open === r.name ? null : r.name)} aria-expanded={open === r.name}>{r.name}</button></td>
                {data.buckets.map((b) => <td key={b.key} className={`num ${b.key !== "current" && Number(r[b.key]) ? "bad-text" : ""}`}>
                  {Number(r[b.key]) ? etb(r[b.key] as string) : "–"}</td>)}
                <td className="num"><b>{etb(r.total)}</b></td>
              </tr>
              {open === r.name && r.documents.map((d) => {
                const to = docLink(d.id);
                return (
                  <tr key={`${r.name}-${d.id}`} className="sub">
                    <td className="small">{to ? <Link className="mono" to={to}>{d.number}</Link> : <span className="mono">{d.number}</span>}</td>
                    <td colSpan={data.buckets.length} className="small muted">due {d.due_date}{d.days_late > 0 && `, ${d.days_late} days late`}</td>
                    <td className="num small">{etb(d.balance)}</td>
                  </tr>);
              })}
            </Fragment>))}
            <tr className="total"><td>Total</td>{data.buckets.map((b) => <td key={b.key} className="num">{etb(data.totals[b.key])}</td>)}
              <td className="num"><b>{etb(data.totals.total)}</b></td></tr>
          </tbody>
        </table></div>)}
    </div>
  );
}

function ReportsTab() {
  const now = new Date();
  const [period, setPeriod] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [ar, setAr] = useState<Aging | null>(null);
  const [ap, setAp] = useState<Aging | null>(null);
  const [tax, setTax] = useState<TaxSummary | null>(null);
  useEffect(() => {
    api<Aging>("/api/finance/aging/receivables/").then(setAr);
    api<Aging>("/api/finance/aging/payables/").then(setAp);
  }, []);
  useEffect(() => {
    const [y, m] = period.split("-");
    if (y && m) api<TaxSummary>(`/api/finance/tax/?year=${y}&month=${Number(m)}`).then(setTax).catch(() => setTax(null));
  }, [period]);
  return (
    <div className="stack">
      {ar && <AgingTable title="Customers owe us" data={ar} docLink={(id) => `/finance/invoices/${id}`} />}
      {ap && <AgingTable title="We owe suppliers" data={ap} docLink={() => null} />}
      <div className="panel">
        <div className="row between tight">
          <h3>VAT and withholding for the month</h3>
          <label className="field inline"><span>Month</span>
            <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
        </div>
        {tax && (<>
          <div className="kpis">
            <div className="kpi"><b>{etb(tax.output_vat)}</b><span>VAT charged on {etb(tax.sales)} of sales</span></div>
            <div className="kpi"><b>{etb(tax.input_vat)}</b><span>VAT paid on {etb(tax.purchases)} of purchases</span></div>
            <div className="kpi"><b className={Number(tax.vat_payable) > 0 ? "bad-text" : ""}>{etb(tax.vat_payable)}</b>
              <span>{Number(tax.vat_payable) >= 0 ? "VAT to pay" : "VAT to carry forward"}</span></div>
            <div className="kpi"><b>{etb(tax.withheld_from_suppliers)}</b><span>withheld from suppliers, to pay the tax office</span></div>
          </div>
          <p className="small muted">Customers withheld {etb(tax.withheld_by_customers)} from what they paid us this month
            ({tax.withholding_receipts.length} withholding {tax.withholding_receipts.length === 1 ? "receipt" : "receipts"}); this is
            credit against our income tax. These figures are a working summary for your accountant, not a filed return.</p>
          <h4>Sales invoices</h4>
          {tax.invoices.length === 0 ? <p className="muted small">No invoices issued this month.</p> : (
            <div className="tbl"><table>
              <thead><tr><th>Invoice</th><th>Date</th><th>Customer</th><th>TIN</th><th>FS no.</th><th className="num">Ex VAT</th><th className="num">VAT</th></tr></thead>
              <tbody>{tax.invoices.map((i) => (
                <tr key={i.id}><td><Link className="mono" to={`/finance/invoices/${i.id}`}>{i.number}</Link></td><td className="small">{i.date}</td>
                  <td>{i.customer}</td><td className="mono small">{i.tin || "–"}</td><td className="small">{i.fs_no || "–"}</td>
                  <td className="num">{etb(i.subtotal)}</td><td className="num">{etb(i.vat)}</td></tr>))}
              </tbody>
            </table></div>)}
          <h4>Purchase invoices</h4>
          {tax.bills.length === 0 ? <p className="muted small">No supplier invoices booked this month.</p> : (
            <div className="tbl"><table>
              <thead><tr><th>Bill</th><th>Date</th><th>Supplier</th><th>TIN</th><th>Their no.</th><th className="num">Ex VAT</th><th className="num">VAT</th><th className="num">Withheld</th></tr></thead>
              <tbody>{tax.bills.map((b) => (
                <tr key={b.id}><td className="mono">{b.number}</td><td className="small">{b.date}</td><td>{b.supplier}</td>
                  <td className="mono small">{b.tin || "–"}</td><td className="small">{b.supplier_invoice_no}</td>
                  <td className="num">{etb(b.subtotal)}</td><td className="num">{etb(b.vat)}</td><td className="num">{Number(b.withholding) ? etb(b.withholding) : "–"}</td></tr>))}
              </tbody>
            </table></div>)}
        </>)}
      </div>
    </div>
  );
}
