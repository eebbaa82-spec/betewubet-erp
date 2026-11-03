import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, ApiError, Location, Page, PurchaseOrder, PurchaseOrderLine, Shortage } from "../api";
import { dec1, money, plural, qty as fmtQty } from "../format";

const FILTERS = [["draft,sent,partial", "Open"], ["received", "Received"], ["", "All"]] as const;
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong.");

export default function Purchasing() {
  const [tab, setTab] = useState<"short" | "orders">("short");
  return (
    <section className="stack">
      <div>
        <h2>Purchasing</h2>
        <p className="lead">What open work orders and reorder levels need beyond stock and open orders, and the
          purchase orders that cover it.</p>
      </div>
      <div className="tabs small-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "short"} onClick={() => setTab("short")}>Shortages</button>
        <button role="tab" aria-selected={tab === "orders"} onClick={() => setTab("orders")}>Purchase orders</button>
      </div>
      {tab === "short" ? <Shortages onDrafted={() => setTab("orders")} /> : <Orders />}
    </section>
  );
}

function Shortages({ onDrafted }: { onDrafted: () => void }) {
  const [rows, setRows] = useState<Shortage[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<Shortage[]>("/api/purchasing/shortages/").then(setRows); }, []);

  const draft = async () => {
    setBusy(true); setError("");
    try {
      await api("/api/purchasing/draft-orders/", { method: "POST", body: {} });
      onDrafted();
    } catch (e) { setError(errText(e)); setBusy(false); }
  };

  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) {
    return <div className="panel"><p className="muted">Nothing is short. Stock and open purchase orders cover every
      open work order and reorder level.</p></div>;
  }
  const buyable = rows.filter((r) => r.supplier);
  const suppliers = new Set(buyable.map((r) => r.supplier));
  const total = buyable.reduce((s, r) => s + Number(r.amount), 0);
  return (
    <div className="panel">
      <div className="row between">
        <p className="muted">{rows.length} {plural(rows.length, "item")} short.
          {buyable.length > 0 && <> Suggested orders come to {money(total)} before VAT from {suppliers.size} {plural(suppliers.size, "supplier")}.</>}</p>
        {buyable.length > 0 && <button className="btn" disabled={busy} onClick={draft}>
          {busy ? "Drafting…" : `Draft ${suppliers.size} purchase ${suppliers.size === 1 ? "order" : "orders"}`}</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="tbl">
        <table>
          <thead><tr><th>Item</th><th className="num">Needed for jobs</th><th className="num">Reorder level</th>
            <th className="num">In stock</th><th className="num">On order</th><th className="num">Short</th>
            <th>Suggested</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.item}>
                <td>{r.item_name}<div className="mono small muted">{r.item}</div></td>
                <td className="num">{fmtQty(r.required)}</td>
                <td className="num">{fmtQty(r.reorder_level)}</td>
                <td className="num">{fmtQty(r.in_stock)}</td>
                <td className="num">{fmtQty(r.on_order)}</td>
                <td className="num"><b>{fmtQty(r.short)}</b> <span className="muted">{r.uom}</span></td>
                <td>{r.supplier ? <>{r.suggested_packs} {plural(r.suggested_packs ?? 0, r.pack_name ?? "")}
                  <div className="small muted">{r.supplier}</div></> : <span className="chip bad">no supplier</span>}</td>
                <td className="num">{r.amount ? money(r.amount) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">Short = needed for open work orders + reorder level − in stock − on order. Boards on the
        offcut rack are not counted as stock. Suppliers and their pack prices are kept in the back office.</p>
    </div>
  );
}

function Orders() {
  const [status, setStatus] = useState<string>(FILTERS[0][0]);
  const [rows, setRows] = useState<PurchaseOrder[] | null>(null);
  useEffect(() => {
    setRows(null);
    api<Page<PurchaseOrder>>(`/api/purchase-orders/?page_size=200${status ? `&status=${status}` : ""}`).then((p) => setRows(p.results));
  }, [status]);
  return (
    <div className="panel">
      <div className="tabs">
        {FILTERS.map(([v, l]) => <button key={v} aria-selected={status === v} onClick={() => setStatus(v)}>{l}</button>)}
      </div>
      {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? (
        <p className="muted">No purchase orders here. Draft them from the shortages list.</p>
      ) : (
        <div className="tbl">
          <table>
            <thead><tr><th>Number</th><th>Supplier</th><th>Status</th><th className="num">Lines</th>
              <th className="num">Total incl. VAT</th><th>Ordered</th><th>Expected</th></tr></thead>
            <tbody>
              {rows.map((po) => (
                <tr key={po.id}>
                  <td><Link className="mono" to={`/purchasing/${po.id}`}>{po.number}</Link></td>
                  <td>{po.supplier_name}</td>
                  <td><span className={`chip po-${po.status}`}>{po.status_label}</span></td>
                  <td className="num">{po.lines.length}</td>
                  <td className="num">{money(po.totals.total)}</td>
                  <td className="mono small">{po.order_date}</td>
                  <td className="mono small">{po.expected_date ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function PurchaseOrderDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [po, setPo] = useState<PurchaseOrder | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<PurchaseOrder>(`/api/purchase-orders/${id}/`).then(setPo), [id]);
  useEffect(() => { load().catch(() => setError("Purchase order not found.")); }, [load]);

  const act = async (what: "send" | "cancel") => {
    setBusy(true); setError("");
    try {
      setPo(await api<PurchaseOrder>(`/api/purchase-orders/${id}/${what}/`, { method: "POST" }));
      return true;
    } catch (e) {
      setError(errText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const savePacks = async (line: PurchaseOrderLine, packs: string) => {
    if (!po || packs === line.packs || Number(packs) <= 0) return;
    setError("");
    try {
      const lines = po.lines.map((l) => ({ item: l.item, pack_name: l.pack_name, pack_qty: l.pack_qty,
        price_per_pack: l.price_per_pack, packs: l.id === line.id ? packs : l.packs }));
      setPo(await api<PurchaseOrder>(`/api/purchase-orders/${id}/`, { method: "PATCH", body: { lines } }));
    } catch (e) { setError(errText(e)); }
  };

  if (error && !po) return <p className="error">{error}</p>;
  if (!po) return <p className="muted">Loading…</p>;
  const isDraft = po.status === "draft";
  const receivable = po.status === "sent" || po.status === "partial";

  return (
    <section className="stack">
      <div className="row between">
        <div>
          <p className="muted no-print"><Link to="/purchasing">Purchasing</Link></p>
          <h2><span className="mono">{po.number}</span> · {po.supplier_name}</h2>
          <p className="muted"><span className={`chip po-${po.status}`}>{po.status_label}</span> · ordered {po.order_date}
            {po.expected_date && <> · expected {po.expected_date}</>}{po.supplier_tin && <> · TIN {po.supplier_tin}</>}</p>
        </div>
        <div className="row no-print">
          {isDraft && <button className="btn" disabled={busy} onClick={() => act("send")}>Mark as sent</button>}
          {(isDraft || po.status === "sent") && <button className="btn ghost" disabled={busy}
            onClick={() => act("cancel").then((ok) => ok && nav("/purchasing"))}>Cancel order</button>}
          <button className="btn ghost" onClick={() => window.print()}>Print</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {isDraft && <p className="note no-print">This is a draft. Change quantities here, then mark it as sent once the
        supplier has it. Goods can be received only on sent orders.</p>}

      <div className="panel">
        <div className="tbl">
          <table>
            <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Price per pack</th>
              <th className="num">Amount</th><th className="num">Received</th></tr></thead>
            <tbody>
              {po.lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.item_name}<div className="mono small muted">{l.item}{l.pack_name !== l.uom && <> · 1 {l.pack_name} = {fmtQty(l.pack_qty)} {l.uom}</>}</div></td>
                  <td className="num">
                    {isDraft ? <input className="cell" type="number" min="1" step="any" defaultValue={fmtQty(l.packs)}
                      aria-label={`Quantity of ${l.item}`} onBlur={(e) => savePacks(l, e.target.value)} />
                      : fmtQty(l.packs)} <span className="muted">{plural(l.packs, l.pack_name)}</span>
                  </td>
                  <td className="num">{money(l.price_per_pack)}</td>
                  <td className="num">{money(l.amount)}</td>
                  <td className="num">{fmtQty(l.received_packs)}<span className="muted"> / {fmtQty(l.packs)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="lines totals">
          <div><dt>Subtotal ex VAT</dt><dd className="num">{money(po.totals.subtotal)}</dd></div>
          <div><dt>VAT {dec1(Number(po.totals.vat_rate) * 100)}%</dt><dd className="num">{money(po.totals.vat)}</dd></div>
          <div className="strong"><dt>Total incl. VAT</dt><dd className="num">{money(po.totals.total)}</dd></div>
        </dl>
      </div>

      {receivable && <ReceiveForm po={po} onDone={setPo} />}
    </section>
  );
}

function ReceiveForm({ po, onDone }: { po: PurchaseOrder; onDone: (po: PurchaseOrder) => void }) {
  const open = po.lines.filter((l) => Number(l.open_packs) > 0);
  const [locations, setLocations] = useState<Location[]>([]);
  const [f, setF] = useState({ line: open[0]?.id ?? 0, packs: open[0] ? fmtQty(open[0].open_packs) : "", location: "",
    lot_code: "", colour_ref: "", supplier_batch: "" });
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  useEffect(() => {
    api<Page<Location>>("/api/locations/").then((p) => {
      setLocations(p.results.filter((l) => !l.is_offcut_rack));
      setF((x) => ({ ...x, location: p.results.find((l) => !l.is_offcut_rack)?.code ?? "" }));
    });
  }, []);
  const line = po.lines.find((l) => l.id === f.line);
  const pick = (id: number) => {
    const l = po.lines.find((x) => x.id === id);
    setF({ ...f, line: id, packs: l ? fmtQty(l.open_packs) : "", lot_code: "", colour_ref: "", supplier_batch: "" });
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      const next = await api<PurchaseOrder>(`/api/purchase-orders/${po.id}/receive/`, { method: "POST", body: f });
      setMsg({ kind: "ok", text: `Received ${f.packs} ${plural(f.packs, line?.pack_name ?? "")} of ${line?.item_name} into ${f.location}.` });
      const nextOpen = next.lines.find((l) => Number(l.open_packs) > 0);
      setF({ ...f, line: nextOpen?.id ?? 0, packs: nextOpen ? fmtQty(nextOpen.open_packs) : "", lot_code: "", colour_ref: "", supplier_batch: "" });
      onDone(next);
    } catch (err) {
      setMsg({ kind: "error", text: errText(err) });
    }
  };
  if (open.length === 0) return null;
  return (
    <div className="panel no-print">
      <h3>Receive goods</h3>
      <form className="inline-form" onSubmit={submit}>
        <label className="field"><span>Item</span>
          <select value={f.line} onChange={(e) => pick(Number(e.target.value))}>
            {open.map((l) => <option key={l.id} value={l.id}>{l.item_name} ({fmtQty(l.open_packs)} open)</option>)}
          </select></label>
        <label className="field"><span>Quantity ({line ? plural(2, line.pack_name) : ""})</span>
          <input type="number" min="0.01" step="any" required value={f.packs} onChange={(e) => setF({ ...f, packs: e.target.value })} /></label>
        <label className="field"><span>Into</span>
          <select value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })}>
            {locations.map((l) => <option key={l.code} value={l.code}>{l.code}</option>)}
          </select></label>
        {line?.track_lots && <>
          <label className="field"><span>Lot or batch</span>
            <input required value={f.lot_code} onChange={(e) => setF({ ...f, lot_code: e.target.value })} /></label>
          <label className="field"><span>Colour or dye lot (optional)</span>
            <input value={f.colour_ref} onChange={(e) => setF({ ...f, colour_ref: e.target.value })} /></label>
        </>}
        <button className="btn">Receive into stock</button>
        {msg && <p className={`${msg.kind} full`}>{msg.text}</p>}
      </form>
      <p className="note">Stock is booked at the order price, with {po.number} as the reference.</p>
    </div>
  );
}
