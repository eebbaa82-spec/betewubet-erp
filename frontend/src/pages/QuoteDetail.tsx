import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, Order, OrderLine } from "../api";
import { dec1, money, qty as fmtQty } from "../format";

function summary(line: OrderLine) {
  const c = line.configuration;
  const dims = ["W", "H", "D"].filter((k) => k in c).map((k) => c[k]).join(" x ");
  const rest = Object.entries(c).filter(([k]) => !["W", "H", "D"].includes(k)).map(([k, v]) => `${k} ${v}`);
  return [dims && `${dims} mm`, ...rest].filter(Boolean).join(", ");
}

export default function QuoteDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api<Order>(`/api/sales-orders/${id}/`).then(setOrder), [id]);
  useEffect(() => { load().catch(() => setError("Quote not found.")); }, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); await load(); } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save. Try again.");
    } finally { setBusy(false); }
  };

  const setPrice = (line: OrderLine, value: string) => run(() =>
    api(`/api/sales-order-lines/${line.id}/`, {
      method: "PATCH", body: value === "" ? { price_locked: false } : { unit_price: value, price_locked: true },
    }));
  const setQty = (line: OrderLine, value: string) => run(() =>
    api(`/api/sales-order-lines/${line.id}/`, { method: "PATCH", body: { quantity: value } }));
  const remove = (line: OrderLine) => run(() => api(`/api/sales-order-lines/${line.id}/`, { method: "DELETE" }));
  const confirm = () => run(async () => {
    const r = await api<{ work_orders: string[] }>(`/api/sales-orders/${id}/confirm/`, { method: "POST" });
    setCreated(r.work_orders);
  });

  if (error && !order) return <p className="error">{error}</p>;
  if (!order) return <p className="muted">Loading…</p>;
  const isQuote = order.status === "quote";

  return (
    <section className="stack">
      <div className="row between">
        <div>
          <p className="muted"><Link to="/quotes">Quotes and orders</Link></p>
          <h2><span className="mono">{order.number}</span> · {order.customer_name}</h2>
          <span className={`chip st-${order.status}`}>{order.status_label}</span>
        </div>
        {isQuote && (
          <div className="row">
            <Link className="btn ghost" to="/configure">Add a product</Link>
            <button className="btn" disabled={busy || order.lines.length === 0} onClick={confirm}>
              Confirm order and create work orders
            </button>
          </div>
        )}
      </div>
      {created.length > 0 && (
        <p className="ok">Order confirmed. Work orders created: {created.join(", ")}.</p>
      )}
      {error && <p className="error">{error}</p>}

      <div className="panel">
        <div className="tbl">
          <table>
            <thead>
              <tr><th>Product</th><th className="num">Qty</th><th className="num">Unit cost</th>
                <th className="num">Unit price ex VAT</th><th className="num">Line total</th><th></th></tr>
            </thead>
            <tbody>
              {order.lines.map((l) => (
                <tr key={l.id}>
                  <td><b>{l.template_name}</b><div className="muted small">{summary(l)}</div></td>
                  <td className="num">
                    {isQuote ? <input className="cell" type="number" min="1" defaultValue={fmtQty(l.quantity)}
                      onBlur={(e) => e.target.value !== fmtQty(l.quantity) && setQty(l, e.target.value)} /> : fmtQty(l.quantity)}
                  </td>
                  <td className="num">{money(l.estimated_unit_cost)}</td>
                  <td className="num">
                    {isQuote ? (
                      <input className="cell" type="number" min="0" defaultValue={Number(l.unit_price).toFixed(0)}
                        title={l.price_locked ? "Price set by hand. Clear it to use the margin price." : "Price from target margin"}
                        onBlur={(e) => Number(e.target.value) !== Number(l.unit_price) && setPrice(l, e.target.value)} />
                    ) : money(l.unit_price)}
                    {l.price_locked && <div className="small muted">set by hand</div>}
                  </td>
                  <td className="num">{money(l.line_total)}</td>
                  <td>{isQuote && <button className="link danger" onClick={() => remove(l)} disabled={busy}>Remove</button>}</td>
                </tr>
              ))}
              {order.lines.length === 0 && (
                <tr><td colSpan={6} className="muted">No products yet. Use “Add a product”.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <dl className="lines totals">
          <div><dt>Subtotal ex VAT</dt><dd className="num">{money(order.totals.subtotal)}</dd></div>
          <div><dt>VAT {dec1(Number(order.totals.vat_rate) * 100)}%</dt><dd className="num">{money(order.totals.vat)}</dd></div>
          <div className="strong"><dt>Total incl. VAT</dt><dd className="num">{money(order.totals.total)}</dd></div>
          <div><dt>Estimated cost</dt><dd className="num">{money(order.totals.estimated_cost)}</dd></div>
          <div><dt>Estimated margin</dt><dd className="num">{dec1(order.totals.estimated_margin_pct)}%</dd></div>
        </dl>
      </div>
    </section>
  );
}
