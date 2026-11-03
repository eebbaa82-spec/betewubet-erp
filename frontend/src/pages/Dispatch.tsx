import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, ApiError, Delivery, Installation, Page, ReadyOrder } from "../api";
import { configSummary, qty as fmtQty, today } from "../format";

type Tab = "ready" | "deliveries" | "installs";
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Could not reach the server.");
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Dispatch() {
  const [tab, setTab] = useState<Tab>("ready");
  return (
    <section className="stack">
      <div>
        <h2>Dispatch and installation</h2>
        <p className="lead">Finished work ready to leave the factory, delivery notes with proof of delivery, and
          installation visits signed off by the customer.</p>
      </div>
      <div className="tabs small-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "ready"} onClick={() => setTab("ready")}>Ready to ship</button>
        <button role="tab" aria-selected={tab === "deliveries"} onClick={() => setTab("deliveries")}>Deliveries</button>
        <button role="tab" aria-selected={tab === "installs"} onClick={() => setTab("installs")}>Installations</button>
      </div>
      {tab === "ready" ? <Ready /> : tab === "deliveries" ? <Deliveries /> : <Installs />}
    </section>
  );
}

function Ready() {
  const [rows, setRows] = useState<ReadyOrder[] | null>(null);
  useEffect(() => { api<ReadyOrder[]>("/api/dispatch/ready/").then(setRows); }, []);
  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <div className="panel"><p className="muted">Nothing is waiting to ship. Orders appear
    here once their work orders are finished.</p></div>;
  return <div className="stack">{rows.map((o) => <ReadyCard key={o.order} o={o} />)}</div>;
}

function ReadyCard({ o }: { o: ReadyOrder }) {
  const nav = useNavigate();
  const [qtys, setQtys] = useState<Record<number, string>>(
    Object.fromEntries(o.lines.map((l) => [l.line, Number(l.ready) > 0 ? fmtQty(l.ready) : "0"])));
  const [f, setF] = useState({ scheduled_date: today(), vehicle: "", driver: "", install_required: true, notes: "" });
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const d = await api<Delivery>("/api/deliveries/", { method: "POST", body: {
        order: o.order, ...f, lines: o.lines.map((l) => ({ line: l.line, quantity: qtys[l.line] || "0" })) } });
      nav(`/dispatch/${d.id}`);
    } catch (err) { setError(errText(err)); }
  };
  return (
    <form className="panel" onSubmit={submit}>
      <div className="row between tight">
        <div><Link className="mono" to={`/quotes/${o.order}`}>{o.number}</Link> · <b>{o.customer}</b>
          <div className="small muted">{o.address || "No site address"}{o.phone && ` · ${o.phone}`}{o.due_date && ` · due ${o.due_date}`}</div></div>
      </div>
      <div className="tbl">
        <table>
          <thead><tr><th>Item</th><th className="num">Ordered</th><th className="num">Finished</th>
            <th className="num">Shipped</th><th className="num">Send now</th></tr></thead>
          <tbody>
            {o.lines.map((l) => (
              <tr key={l.line}>
                <td>{l.product}<div className="small muted">{l.description || configSummary(l.configuration)}</div></td>
                <td className="num">{fmtQty(l.ordered)}</td>
                <td className="num">{fmtQty(l.made)}</td>
                <td className="num">{fmtQty(l.shipped)}</td>
                <td className="num">
                  <input className="cell" type="number" min="0" max={l.ready} step="any" aria-label={`Quantity of line ${l.sequence} to send`}
                    disabled={Number(l.ready) <= 0} value={qtys[l.line]} onChange={(e) => setQtys({ ...qtys, [l.line]: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="inline-form">
        <label className="field"><span>Delivery date</span>
          <input type="date" required value={f.scheduled_date} onChange={(e) => setF({ ...f, scheduled_date: e.target.value })} /></label>
        <label className="field"><span>Vehicle</span>
          <input placeholder="Plate number" value={f.vehicle} onChange={(e) => setF({ ...f, vehicle: e.target.value })} /></label>
        <label className="field"><span>Driver</span>
          <input value={f.driver} onChange={(e) => setF({ ...f, driver: e.target.value })} /></label>
        <label className="check"><input type="checkbox" checked={f.install_required}
          onChange={(e) => setF({ ...f, install_required: e.target.checked })} /> Install at site</label>
        <button className="btn">Create delivery note</button>
        {error && <p className="error full">{error}</p>}
      </div>
    </form>
  );
}

const FILTERS = [["planned,out", "Open"], ["delivered", "Delivered"], ["", "All"]] as const;

function Deliveries() {
  const [status, setStatus] = useState<string>(FILTERS[0][0]);
  const [rows, setRows] = useState<Delivery[] | null>(null);
  useEffect(() => {
    setRows(null);
    api<Page<Delivery>>(`/api/deliveries/?page_size=200${status ? `&status=${status}` : ""}`).then((p) => setRows(p.results));
  }, [status]);
  return (
    <div className="panel">
      <div className="tabs">
        {FILTERS.map(([v, l]) => <button key={v} aria-selected={status === v} onClick={() => setStatus(v)}>{l}</button>)}
      </div>
      {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <p className="muted">No deliveries here.</p> : (
        <div className="tbl">
          <table>
            <thead><tr><th>Note</th><th>Date</th><th>Customer</th><th>Status</th><th>Vehicle</th><th className="num">Items</th></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  <td><Link className="mono" to={`/dispatch/${d.id}`}>{d.number}</Link></td>
                  <td className="mono small">{d.scheduled_date}</td>
                  <td>{d.customer}<div className="small muted mono">{d.order_number}</div></td>
                  <td><span className={`chip dn-${d.status}`}>{d.status_label}</span></td>
                  <td className="small">{[d.vehicle, d.driver].filter(Boolean).join(" · ") || "–"}</td>
                  <td className="num">{fmtQty(d.lines.reduce((s, l) => s + Number(l.quantity), 0))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Installs() {
  const [rows, setRows] = useState<Installation[] | null>(null);
  const [flash, setFlash] = useState<{ kind: string; text: string } | null>(null);
  const load = useCallback(() => api<Page<Installation>>("/api/installations/?page_size=200").then((p) => setRows(p.results)), []);
  useEffect(() => { load(); }, [load]);
  if (rows === null) return <p className="muted">Loading…</p>;
  const open = rows.filter((r) => r.status === "scheduled");
  const closed = rows.filter((r) => r.status !== "scheduled").reverse();
  return (
    <div className="stack">
      {flash && <p className={flash.kind} role="status">{flash.text}</p>}
      {open.length === 0 && <div className="panel"><p className="muted">No installation visits scheduled. They are created
        when a delivery that needs installing is marked delivered.</p></div>}
      {open.map((j) => <InstallCard key={j.id} j={j} onDone={async (t) => { setFlash({ kind: "ok", text: t }); await load(); }}
        onError={(t) => setFlash({ kind: "error", text: t })} />)}
      {closed.length > 0 && (
        <div className="panel">
          <h3>Completed</h3>
          <div className="tbl"><table>
            <thead><tr><th>Visit</th><th>Customer</th><th>Status</th><th>Signed off</th><th>Snags</th></tr></thead>
            <tbody>{closed.map((j) => (
              <tr key={j.id}>
                <td className="mono small">{j.number}</td>
                <td>{j.customer}<div className="small muted mono">{j.order_number} · {j.delivery}</div></td>
                <td><span className={`chip in-${j.status}`}>{j.status_label}</span></td>
                <td className="small">{j.signed_off_by}{j.completed_at && <div className="muted">{when(j.completed_at)}</div>}</td>
                <td className="small">{j.snags || "–"}</td>
              </tr>))}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}

function InstallCard({ j, onDone, onError }: { j: Installation; onDone: (t: string) => Promise<void>; onError: (t: string) => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ signed_off_by: "", snags: "", notes: "" });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<Installation & { follow_up: Installation | null }>(`/api/installations/${j.id}/complete/`, { method: "POST", body: f });
      await onDone(r.follow_up ? `${j.number} signed off with snags. Return visit ${r.follow_up.number} booked for ${r.follow_up.scheduled_date}.`
        : `${j.number} signed off by ${f.signed_off_by}.`);
    } catch (err) { onError(errText(err)); }
  };
  return (
    <div className="panel">
      <div className="row between tight">
        <div><span className="mono small">{j.number}</span>{j.return_visit_of && <span className="chip bad">Return visit</span>}
          <div className="op-title">{j.customer}</div>
          <div className="small muted">{j.address}{j.contact_phone && ` · ${j.contact_phone}`}</div>
          <div className="small muted">{j.scheduled_date}{j.crew && ` · ${j.crew}`} · <span className="mono">{j.order_number} · {j.delivery}</span></div>
          {j.notes && <p className="small">{j.notes}</p>}
        </div>
        {!open && <button className="btn" onClick={() => setOpen(true)}>Sign off</button>}
      </div>
      {open && (
        <form className="inline-form" onSubmit={submit}>
          <label className="field"><span>Signed off by (customer)</span>
            <input required autoFocus value={f.signed_off_by} onChange={(e) => setF({ ...f, signed_off_by: e.target.value })} /></label>
          <label className="field full"><span>Snags still to fix (leave empty if none)</span>
            <textarea rows={2} value={f.snags} onChange={(e) => setF({ ...f, snags: e.target.value })} /></label>
          <button className="btn">{f.snags.trim() ? "Sign off and book return visit" : "Sign off"}</button>
          <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Back</button>
        </form>
      )}
    </div>
  );
}

export function DeliveryNote() {
  const { id } = useParams();
  const [d, setD] = useState<Delivery | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pod, setPod] = useState({ received_by: "", install_date: "", crew: "" });
  useEffect(() => { api<Delivery>(`/api/deliveries/${id}/`).then(setD).catch(() => setError("Delivery not found.")); }, [id]);
  const act = async (what: "dispatch" | "deliver" | "cancel", body?: unknown) => {
    setBusy(true); setError("");
    try { setD(await api<Delivery>(`/api/deliveries/${id}/${what}/`, { method: "POST", body })); }
    catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  if (error && !d) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <section className="stack delivery-note">
      <div className="row between">
        <div>
          <p className="muted no-print"><Link to="/dispatch">Dispatch</Link></p>
          <p className="print-only brand">Betewubet Home and Office Furniture Manufacturing PLC</p>
          <h2>Delivery note <span className="mono">{d.number}</span></h2>
          <p className="muted"><span className={`chip dn-${d.status}`}>{d.status_label}</span> · {d.scheduled_date}
            {d.dispatched_at && <> · left {when(d.dispatched_at)}</>}{d.delivered_at && <> · delivered {when(d.delivered_at)}</>}</p>
        </div>
        <div className="row no-print">
          {d.status === "planned" && <button className="btn" disabled={busy} onClick={() => act("dispatch")}>Truck has left</button>}
          {d.status === "planned" && <button className="btn ghost" disabled={busy} onClick={() => act("cancel")}>Cancel</button>}
          <button className="btn ghost" onClick={() => window.print()}>Print</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      <div className="split even">
        <div className="panel">
          <h3>Deliver to</h3>
          <p><b>{d.customer}</b>{d.customer_tin && <span className="muted"> · TIN {d.customer_tin}</span>}</p>
          <p className="small">{d.address || "–"}</p>
          <p className="small muted">{d.contact_phone} · order <span className="mono">{d.order_number}</span></p>
        </div>
        <div className="panel">
          <h3>Transport</h3>
          <p className="small">Vehicle: {d.vehicle || "–"}<br />Driver: {d.driver || "–"}<br />
            Installation: {d.install_required ? "yes, by our team" : "no"}</p>
        </div>
      </div>

      <div className="panel">
        <div className="tbl">
          <table>
            <thead><tr><th>#</th><th>Item</th><th className="num">Qty</th><th className="print-only">Checked</th></tr></thead>
            <tbody>{d.lines.map((l) => (
              <tr key={l.line}>
                <td className="mono small">{l.sequence}</td>
                <td>{l.product}<div className="small muted">{l.description || configSummary(l.configuration)}</div></td>
                <td className="num">{fmtQty(l.quantity)}</td>
                <td className="print-only">☐</td>
              </tr>))}
            </tbody>
          </table>
        </div>
        {d.received_by && <p className="ok">Received by {d.received_by}{d.delivered_at && ` on ${when(d.delivered_at)}`}.</p>}
        <div className="signatures print-only">
          <div>Received in good condition by (name)</div><div>Signature</div><div>Date</div>
        </div>
      </div>

      {d.status === "out" && (
        <form className="panel no-print" onSubmit={(e) => { e.preventDefault(); act("deliver", { ...pod, install_date: pod.install_date || null }); }}>
          <h3>Proof of delivery</h3>
          <div className="inline-form">
            <label className="field"><span>Received by</span>
              <input required value={pod.received_by} onChange={(e) => setPod({ ...pod, received_by: e.target.value })} /></label>
            {d.install_required && <>
              <label className="field"><span>Installation date</span>
                <input type="date" value={pod.install_date} onChange={(e) => setPod({ ...pod, install_date: e.target.value })} /></label>
              <label className="field"><span>Installation crew</span>
                <input value={pod.crew} onChange={(e) => setPod({ ...pod, crew: e.target.value })} /></label>
            </>}
            <button className="btn" disabled={busy}>Mark delivered</button>
          </div>
        </form>
      )}
      {d.installations.length > 0 && (
        <div className="panel no-print">
          <h3>Installation</h3>
          {d.installations.map((j) => (
            <p className="small" key={j.id}><span className="mono">{j.number}</span> · {j.scheduled_date}{j.crew && ` · ${j.crew}`} ·{" "}
              <span className={`chip in-${j.status}`}>{j.status_label}</span>{j.snags && ` · ${j.snags}`}</p>))}
          <p className="note">Sign-off happens on the Installations tab of the Dispatch page.</p>
        </div>
      )}
    </section>
  );
}
