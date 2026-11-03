import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, FinanceSettings, InvoiceDetail } from "../api";
import { qty as fmtQty, today } from "../format";
import { errText, etb, PAY_LABEL, payChip } from "./Finance";

export default function InvoiceView() {
  const { id } = useParams();
  const nav = useNavigate();
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [co, setCo] = useState<FinanceSettings | null>(null);
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [busy, setBusy] = useState(false);
  const [fs, setFs] = useState("");
  const [line, setLine] = useState({ description: "", quantity: "1", unit_price: "" });
  const [paying, setPaying] = useState(false);
  const [pay, setPay] = useState({ amount: "", withholding: "0", withholding_receipt_no: "", date: today(), method: "bank", reference: "" });

  useEffect(() => {
    api<InvoiceDetail>(`/api/invoices/${id}/`).then(setInv).catch(() => setError("Invoice not found."));
    api<FinanceSettings>("/api/finance/settings/").then(setCo).catch(() => undefined);
  }, [id]);

  const run = async (fn: () => Promise<InvoiceDetail | void>, ok?: string) => {
    setBusy(true); setError(""); setFlash("");
    try { const r = await fn(); if (r) setInv(r); if (ok) setFlash(ok); return true; }
    catch (e) { setError(errText(e)); return false; }
    finally { setBusy(false); }
  };

  if (error && !inv) return <p className="error">{error}</p>;
  if (!inv) return <p className="muted">Loading…</p>;
  const draft = inv.status === "draft";
  const startPaying = () => {
    const wh = inv.payments.length ? "0" : inv.expected_withholding;
    setPay({ ...pay, withholding: wh, amount: (Number(inv.balance) - Number(wh)).toFixed(2) });
    setPaying(true);
  };

  const addLine = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await api<InvoiceDetail>(`/api/invoices/${inv.id}/lines/`, { method: "POST", body: line });
      setLine({ description: "", quantity: "1", unit_price: "" });
      return r;
    });
  };
  const issue = () => run(() => api<InvoiceDetail>(`/api/invoices/${inv.id}/issue/`, { method: "POST", body: { fiscal_receipt_no: fs } }));
  const remove = () => run(async () => { await api(`/api/invoices/${inv.id}/`, { method: "DELETE" }); nav("/finance?tab=invoices"); });
  const recordPay = (e: FormEvent) => {
    e.preventDefault();
    run(() => api<InvoiceDetail>(`/api/invoices/${inv.id}/payments/`, { method: "POST", body: pay }), "Payment recorded.")
      .then((ok) => ok && setPaying(false));
  };

  return (
    <section className="stack invoice-doc">
      <div className="row between">
        <div>
          <p className="muted no-print"><Link to="/finance?tab=invoices">Finance</Link></p>
          {co && <div className="print-only letterhead">
            <p className="brand">{co.company_name}</p>
            <p className="small">{co.company_address}{co.company_phone && ` · ${co.company_phone}`}</p>
            <p className="small">{co.company_tin && `TIN ${co.company_tin}`}{co.company_vat_no && ` · VAT reg. ${co.company_vat_no}`}</p>
          </div>}
          <h2>{inv.kind === "advance" ? "Advance invoice" : "Tax invoice"} <span className="mono">{inv.number ?? "(draft)"}</span></h2>
          <p className="muted"><span className={`chip ${payChip(inv.payment_status)}`}>{PAY_LABEL[inv.payment_status]}</span>
            {inv.issue_date && <> · issued {inv.issue_date} · due {inv.due_date}</>}
            {inv.fiscal_receipt_no && <> · FS no. {inv.fiscal_receipt_no}</>}</p>
        </div>
        <div className="row no-print">
          {!draft && Number(inv.balance) > 0 && !paying && <button className="btn" onClick={startPaying}>Record payment</button>}
          {draft && <button className="btn ghost" disabled={busy} onClick={remove}>Delete draft</button>}
          <button className="btn ghost" onClick={() => window.print()}>Print</button>
        </div>
      </div>
      {error && <p className="error no-print" role="status">{error}</p>}
      {flash && <p className="ok no-print" role="status">{flash}</p>}

      <div className="split even">
        <div className="panel">
          <h3>Bill to</h3>
          <p><b>{inv.customer_name}</b></p>
          <p className="small">{inv.customer_address || "–"}</p>
          <p className="small muted">{inv.customer_tin ? `TIN ${inv.customer_tin}` : "No TIN on file"}
            {inv.customer_vat_no && ` · VAT reg. ${inv.customer_vat_no}`}</p>
        </div>
        <div className="panel">
          <h3>Reference</h3>
          <p className="small">Order: {inv.order ? <Link className="mono" to={`/quotes/${inv.order}`}>{inv.order_number}</Link> : "–"}<br />
            Delivery note: {inv.delivery ? <Link className="mono" to={`/dispatch/${inv.delivery}`}>{inv.delivery_number}</Link> : "–"}</p>
        </div>
      </div>

      <div className="panel">
        <div className="tbl"><table>
          <thead><tr><th>Description</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Amount (ETB)</th></tr></thead>
          <tbody>
            {inv.lines.map((l) => (
              <tr key={l.id}><td>{l.description}</td><td className="num">{fmtQty(l.quantity)}</td>
                <td className="num">{etb(l.unit_price)}</td><td className="num">{etb(l.amount)}</td></tr>))}
            <tr className="total"><td colSpan={3}>Total ex VAT</td><td className="num">{etb(inv.subtotal)}</td></tr>
            <tr><td colSpan={3}>VAT {Math.round(Number(inv.vat_rate) * 100)}%</td><td className="num">{etb(inv.vat)}</td></tr>
            <tr className="total"><td colSpan={3}><b>Total to pay</b></td><td className="num"><b>{etb(inv.total)}</b></td></tr>
          </tbody>
        </table></div>
        {draft && (
          <form className="inline-form no-print" onSubmit={addLine}>
            <label className="field"><span>Add a line, e.g. delivery or installation</span>
              <input required value={line.description} onChange={(e) => setLine({ ...line, description: e.target.value })} /></label>
            <label className="field"><span>Qty</span>
              <input type="number" step="any" required value={line.quantity} onChange={(e) => setLine({ ...line, quantity: e.target.value })} /></label>
            <label className="field"><span>Unit price ex VAT</span>
              <input type="number" step="0.01" required value={line.unit_price} onChange={(e) => setLine({ ...line, unit_price: e.target.value })} /></label>
            <button className="btn ghost" disabled={busy}>Add line</button>
          </form>)}
        {co?.bank_details && <p className="small print-only">Pay to: {co.bank_details}</p>}
        {inv.notes && <p className="small">{inv.notes}</p>}
      </div>

      {draft && (
        <div className="panel no-print">
          <h3>Issue this invoice</h3>
          <p className="small muted">Issuing gives it the next invoice number and locks the lines. If you print the receipt on a
            sales register machine, enter its FS number.</p>
          <div className="inline-form">
            <label className="field"><span>FS no. (optional)</span><input value={fs} onChange={(e) => setFs(e.target.value)} /></label>
            <button className="btn" disabled={busy} onClick={issue}>Issue invoice</button>
          </div>
        </div>)}

      {paying && (
        <form className="panel inline-form no-print" onSubmit={recordPay}>
          <h3 className="full">Payment received</h3>
          <label className="field"><span>Money received</span>
            <input type="number" step="0.01" min="0" required value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></label>
          <label className="field"><span>Withheld by customer</span>
            <input type="number" step="0.01" min="0" value={pay.withholding} onChange={(e) => setPay({ ...pay, withholding: e.target.value })} /></label>
          {Number(pay.withholding) > 0 && <label className="field"><span>Withholding receipt no.</span>
            <input required value={pay.withholding_receipt_no} onChange={(e) => setPay({ ...pay, withholding_receipt_no: e.target.value })} /></label>}
          <label className="field"><span>Date</span>
            <input type="date" required value={pay.date} onChange={(e) => setPay({ ...pay, date: e.target.value })} /></label>
          <label className="field"><span>How</span>
            <select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>
              <option value="bank">Bank transfer</option><option value="cheque">Cheque</option>
              <option value="cash">Cash</option><option value="mobile">Mobile money</option></select></label>
          <label className="field"><span>Bank ref. or cheque no.</span>
            <input value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></label>
          <button className="btn" disabled={busy}>Save payment</button>
          <button type="button" className="btn ghost" onClick={() => setPaying(false)}>Cancel</button>
          {Number(inv.expected_withholding) > 0 && <p className="small muted full">{inv.customer_name} is a withholding agent and this
            invoice is over the threshold, so expect them to keep back {etb(inv.expected_withholding)} and give you a withholding receipt.</p>}
        </form>)}

      {inv.payments.length > 0 && (
        <div className="panel">
          <h3>Payments</h3>
          <div className="tbl"><table>
            <thead><tr><th>Receipt</th><th>Date</th><th>How</th><th className="num">Received</th><th className="num">Withheld</th></tr></thead>
            <tbody>{inv.payments.map((p) => (
              <tr key={p.id}><td className="mono">{p.number}</td><td className="small">{p.date}</td>
                <td className="small">{p.method_label}{p.reference && ` · ${p.reference}`}</td>
                <td className="num">{etb(p.amount)}</td>
                <td className="num">{Number(p.withholding) ? <>{etb(p.withholding)}<div className="small muted">{p.withholding_receipt_no}</div></> : "–"}</td></tr>))}
              <tr className="total"><td colSpan={4}>Still owed</td><td className="num"><b>{etb(inv.balance)}</b></td></tr>
            </tbody>
          </table></div>
        </div>)}
    </section>
  );
}
