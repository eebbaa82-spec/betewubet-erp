import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, Order, Page } from "../api";
import { dec1, money } from "../format";

const FILTERS = [
  ["", "All"], ["quote", "Quotes"], ["confirmed", "Confirmed"], ["production", "In production"],
] as const;

export default function Quotes() {
  const [status, setStatus] = useState("");
  const [orders, setOrders] = useState<Order[] | null>(null);

  useEffect(() => {
    setOrders(null);
    api<Page<Order>>(`/api/sales-orders/${status ? `?status=${status}` : ""}`).then((p) => setOrders(p.results));
  }, [status]);

  return (
    <section>
      <div className="row between">
        <h2>Quotes and orders</h2>
        <Link className="btn" to="/configure">New quote</Link>
      </div>
      <div className="tabs" role="tablist">
        {FILTERS.map(([v, l]) => (
          <button key={v} role="tab" aria-selected={status === v} onClick={() => setStatus(v)}>{l}</button>
        ))}
      </div>
      <div className="panel">
        {orders === null ? <p className="muted">Loading…</p> : orders.length === 0 ? (
          <p className="muted">Nothing here yet. Configure a product and add it to a new quote.</p>
        ) : (
          <div className="tbl">
            <table>
              <thead>
                <tr><th>Number</th><th>Customer</th><th>Status</th><th>Date</th>
                  <th className="num">Lines</th><th className="num">Total incl. VAT</th><th className="num">Margin</th></tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td><Link to={`/quotes/${o.id}`} className="mono">{o.number}</Link></td>
                    <td>{o.customer_name}</td>
                    <td><span className={`chip st-${o.status}`}>{o.status_label}</span></td>
                    <td className="mono">{o.order_date}</td>
                    <td className="num">{o.lines.length}</td>
                    <td className="num">{money(o.totals.total)}</td>
                    <td className="num">{dec1(o.totals.estimated_margin_pct)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
