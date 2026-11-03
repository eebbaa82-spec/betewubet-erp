import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError, CostVariance, Location, Page, WorkOrder } from "../api";
import { dec1, money, qty as fmtQty } from "../format";

const FILTERS = [["planned,released,in_progress", "Open"], ["done", "Done"], ["", "All"]] as const;

export function WorkOrders() {
  const [status, setStatus] = useState<string>(FILTERS[0][0]);
  const [rows, setRows] = useState<WorkOrder[] | null>(null);
  useEffect(() => {
    setRows(null);
    api<Page<WorkOrder>>(`/api/work-orders/?page_size=200${status ? `&status=${status}` : ""}`).then((p) => setRows(p.results));
  }, [status]);

  return (
    <section>
      <h2>Work orders</h2>
      <div className="tabs">
        {FILTERS.map(([v, l]) => <button key={v} aria-selected={status === v} onClick={() => setStatus(v)}>{l}</button>)}
      </div>
      <div className="panel">
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? (
          <p className="muted">No work orders here. Confirming a quote creates them.</p>
        ) : (
          <div className="tbl">
            <table>
              <thead><tr><th>Number</th><th>Product</th><th>Order</th><th>Status</th><th className="num">Qty</th>
                <th>Progress</th><th>Due</th></tr></thead>
              <tbody>
                {rows.map((w) => {
                  const done = w.operations.filter((o) => o.status === "done").length;
                  return (
                    <tr key={w.id}>
                      <td><Link className="mono" to={`/work-orders/${w.id}`}>{w.number}</Link>
                        {w.rework_of && <span className="chip bad">Rework</span>}</td>
                      <td>{w.product}</td>
                      <td>{w.order_number ? <span className="mono">{w.order_number}</span> : "–"}<div className="small muted">{w.customer}</div></td>
                      <td><span className="chip">{w.status_label}</span></td>
                      <td className="num">{fmtQty(w.quantity)}</td>
                      <td><Progress done={done} total={w.operations.length} /></td>
                      <td className="mono small">{w.due_date ?? "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Progress({ done, total }: { done: number; total: number }) {
  return (
    <div className="progress" title={`${done} of ${total} steps done`}>
      <span className="track"><i style={{ width: `${total ? (done / total) * 100 : 0}%` }} /></span>
      <span className="small muted">{done}/{total}</span>
    </div>
  );
}

const COST_ROWS: [keyof CostVariance, string][] = [
  ["material", "Material"], ["labour", "Labour"], ["machine", "Machine time"], ["overhead", "Overhead"],
];

export function WorkOrderDetail() {
  const { id } = useParams();
  const [wo, setWo] = useState<WorkOrder | null>(null);
  const [cost, setCost] = useState<CostVariance | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const [w, c] = await Promise.all([
      api<WorkOrder>(`/api/work-orders/${id}/`), api<CostVariance>(`/api/work-orders/${id}/cost/`),
    ]);
    setWo(w); setCost(c);
  }, [id]);
  useEffect(() => { load().catch(() => setError("Work order not found.")); }, [load]);

  if (error) return <p className="error">{error}</p>;
  if (!wo || !cost) return <p className="muted">Loading…</p>;
  const max = Math.max(1, ...COST_ROWS.flatMap(([k]) => [Number(cost[k].estimate), Number(cost[k].actual)]));
  const totalVar = Number(cost.total.variance);

  return (
    <section className="stack">
      <div>
        <p className="muted"><Link to="/work-orders">Work orders</Link></p>
        <h2><span className="mono">{wo.number}</span> · {wo.product} x {fmtQty(wo.quantity)}</h2>
        <p className="muted">
          <span className="chip">{wo.status_label}</span>
          {wo.order_number && <> · <Link to={`/quotes/${wo.order_id}`}>{wo.order_number}</Link> · {wo.customer}</>}
          {wo.rework_of && <> · rework of {wo.rework_of}</>}
          {wo.due_date && <> · due {wo.due_date}</>}
        </p>
      </div>

      <div className="split even">
        <div className="panel">
          <h3>Cost: estimate vs actual so far</h3>
          <div className="legend"><span><i className="est" />Estimate</span><span><i className="act" />Actual</span>
            <span><i className="over" />Over estimate</span></div>
          {COST_ROWS.map(([k, label]) => {
            const e = Number(cost[k].estimate), a = Number(cost[k].actual);
            return (
              <div className="bar-row" key={k}>
                <span>{label}</span>
                <div className="bars">
                  <div className="est" style={{ width: `${(e / max) * 100}%` }} />
                  <div className={`act ${a > e ? "over" : ""}`} style={{ width: `${(a / max) * 100}%` }} />
                </div>
                <span className="num">{money(a)}<div className="small muted">of {money(e)}</div></span>
              </div>
            );
          })}
          <dl className="lines">
            <div className="strong"><dt>Total actual</dt><dd className="num">{money(cost.total.actual)}</dd></div>
            <div><dt>Estimated</dt><dd className="num">{money(cost.total.estimate)}</dd></div>
            <div><dt>{totalVar > 0 ? "Over estimate" : "Under estimate"}</dt><dd className="num">{money(Math.abs(totalVar))}</dd></div>
          </dl>
        </div>

        <div className="panel">
          <h3>Steps</h3>
          <div className="tbl">
            <table>
              <thead><tr><th>Step</th><th>Status</th><th className="num">Minutes</th></tr></thead>
              <tbody>
                {wo.operations.map((o) => (
                  <tr key={o.id}>
                    <td><span className="mono small">{o.work_center}</span> {o.description}</td>
                    <td><span className={`chip st-${o.status}`}>{o.status}</span></td>
                    <td className="num">{dec1(o.spent_minutes)}<span className="muted"> / {dec1(o.planned_minutes)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {wo.non_conformances.length > 0 && (
            <>
              <h3 className="gap">Rejects</h3>
              {wo.non_conformances.map((n) => (
                <p className="small" key={n.number}>
                  <span className="mono">{n.number}</span> · {fmtQty(n.qty)} at {n.work_center}: {n.reason}
                  {n.rework_order && <> · rework {n.rework_order}</>}
                </p>
              ))}
            </>
          )}
        </div>
      </div>

      <div className="panel">
        <h3>Materials</h3>
        <div className="tbl">
          <table>
            <thead><tr><th>Item</th><th className="num">Planned</th><th className="num">Issued</th><th></th></tr></thead>
            <tbody>
              {wo.materials.map((m) => {
                const over = Number(m.issued_qty) > Number(m.planned_qty) * 1.0001;
                return (
                  <tr key={m.item}>
                    <td>{m.item_name}<div className="mono small muted">{m.item}</div></td>
                    <td className="num">{fmtQty(m.planned_qty)} {m.uom}</td>
                    <td className="num">{fmtQty(m.issued_qty)} {m.uom}</td>
                    <td>{over && <span className="chip bad">over plan</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {wo.status !== "done" && <IssueForm wo={wo} onDone={load} />}
      </div>
    </section>
  );
}

function IssueForm({ wo, onDone }: { wo: WorkOrder; onDone: () => Promise<void> }) {
  const [locations, setLocations] = useState<Location[]>([]);
  const [f, setF] = useState({ item: wo.materials[0]?.item ?? "", qty: "", location: "", lot_code: "" });
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  useEffect(() => {
    api<Page<Location>>("/api/locations/").then((p) => {
      setLocations(p.results);
      setF((x) => ({ ...x, location: (p.results.find((l) => !l.is_offcut_rack) ?? p.results[0])?.code ?? "" }));
    });
  }, []);
  const mat = wo.materials.find((m) => m.item === f.item);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      await api("/api/stock/issue/", { method: "POST", body: { ...f, work_order: wo.number } });
      setMsg({ kind: "ok", text: `Issued ${f.qty} ${mat?.uom} of ${mat?.item_name}.` });
      setF({ ...f, qty: "", lot_code: "" });
      await onDone();
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof ApiError ? err.message : "Could not save." });
    }
  };
  return (
    <form className="inline-form" onSubmit={submit}>
      <label className="field"><span>Issue item</span>
        <select id="is-item" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })}>
          {wo.materials.map((m) => <option key={m.item} value={m.item}>{m.item_name}</option>)}
        </select></label>
      <label className="field"><span>Quantity ({mat?.uom})</span>
        <input id="is-qty" type="number" step="any" required value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></label>
      <label className="field"><span>From</span>
        <select id="is-loc" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })}>
          {locations.map((l) => <option key={l.code} value={l.code}>{l.code}</option>)}
        </select></label>
      <label className="field"><span>Lot (optional)</span>
        <input id="is-lot" placeholder="oldest first" value={f.lot_code} onChange={(e) => setF({ ...f, lot_code: e.target.value })} /></label>
      <button className="btn">Issue to job</button>
      {msg && <p className={`${msg.kind} full`}>{msg.text}</p>}
    </form>
  );
}
