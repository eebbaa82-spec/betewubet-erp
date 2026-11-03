import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, Machine, MaintenanceLog, Page, PlanStatus } from "../api";
import { dec1, money, plural } from "../format";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Could not reach the server.");
const STATE_LABEL = { down: "Down", overdue: "Service overdue", soon: "Service due soon", ok: "OK" } as const;
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export default function Maintenance() {
  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [due, setDue] = useState<PlanStatus[]>([]);
  const [history, setHistory] = useState<MaintenanceLog[]>([]);
  const [flash, setFlash] = useState<{ kind: string; text: string } | null>(null);
  const load = useCallback(async () => {
    const [m, d, h] = await Promise.all([
      api<Machine[]>("/api/machines/"), api<PlanStatus[]>("/api/maintenance/due/"),
      api<Page<MaintenanceLog>>("/api/maintenance-logs/?page_size=15"),
    ]);
    setMachines(m); setDue(d); setHistory(h.results);
  }, []);
  useEffect(() => { load(); }, [load]);
  const done = async (text: string) => { setFlash({ kind: "ok", text }); await load(); };

  if (!machines) return <p className="muted">Loading…</p>;
  const down = machines.filter((m) => m.state === "down").length;
  const overdue = due.filter((p) => p.state === "overdue").length;
  const soon = due.filter((p) => p.state === "soon").length;
  const downtime = machines.reduce((s, m) => s + Number(m.downtime_30d), 0);

  return (
    <section className="stack">
      <div>
        <h2>Maintenance</h2>
        <p className="lead">Machine hours come from the time scanned at each station. Services fall due by running
          hours or days, whichever comes first. A breakdown that stops a machine blocks its station until it is closed.</p>
      </div>
      <div className="kpis">
        <div className="kpi"><b className={down ? "bad-text" : ""}>{down}</b><span>{plural(down, "machine")} down</span></div>
        <div className="kpi"><b className={overdue ? "bad-text" : ""}>{overdue}</b><span>{plural(overdue, "service")} overdue</span></div>
        <div className="kpi"><b>{soon}</b><span>due soon</span></div>
        <div className="kpi"><b>{dec1(downtime)} h</b><span>downtime, last 30 days</span></div>
      </div>
      {flash && <p className={flash.kind} role="status">{flash.text}</p>}

      <div className="machines">
        {machines.map((m) => <MachineCard key={m.code} m={m} onDone={done} onError={(t) => setFlash({ kind: "error", text: t })} />)}
      </div>

      <div className="panel">
        <h3>Service schedule</h3>
        <div className="tbl">
          <table>
            <thead><tr><th>Machine</th><th>Task</th><th>Every</th><th>Last done</th><th>Left</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {due.map((p) => <PlanRow key={p.id} p={p} onDone={done} onError={(t) => setFlash({ kind: "error", text: t })} />)}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h3>Recent work</h3>
        {history.length === 0 ? <p className="muted">Nothing recorded yet.</p> : (
          <div className="tbl">
            <table>
              <thead><tr><th>When</th><th>Machine</th><th>What</th><th>Done</th><th className="num">Downtime</th><th className="num">Parts</th></tr></thead>
              <tbody>
                {history.map((l) => (
                  <tr key={l.id}>
                    <td className="small mono">{when(l.reported_at)}</td>
                    <td className="mono small">{l.machine}</td>
                    <td><span className={`chip ${l.kind === "breakdown" ? "bad" : ""}`}>{l.kind_label}</span> {l.description}
                      {l.action_taken && <div className="small muted">{l.action_taken}</div>}</td>
                    <td className="small">{l.is_open ? <span className="chip bad">open</span> : <>{l.done_by || "–"}</>}</td>
                    <td className="num">{l.machine_down ? `${dec1(Number(l.downtime_minutes) / 60)} h` : "–"}</td>
                    <td className="num">{Number(l.parts_cost) ? money(l.parts_cost) : "–"}</td>
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

function MachineCard({ m, onDone, onError }: { m: Machine; onDone: (t: string) => Promise<void>; onError: (t: string) => void }) {
  const [reporting, setReporting] = useState(false);
  const [desc, setDesc] = useState("");
  const [stops, setStops] = useState(true);
  const report = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/api/machines/${m.code}/breakdown/`, { method: "POST", body: { description: desc, machine_down: stops } });
      setReporting(false); setDesc("");
      await onDone(stops && m.work_center ? `Breakdown recorded. ${m.work_center} is blocked until it is closed.` : "Breakdown recorded.");
    } catch (err) { onError(errText(err)); }
  };
  const next = m.plans.slice().sort((a, b) => Number(b.used) - Number(a.used))[0];
  return (
    <div className={`panel machine st-${m.state}`}>
      <div className="row between tight">
        <div><span className="mono small">{m.code}</span>{m.work_center && <span className="small muted"> · station {m.work_center}</span>}
          <div className="op-title">{m.name}</div></div>
        <span className={`chip m-${m.state}`}>{STATE_LABEL[m.state]}</span>
      </div>
      <p className="small muted">{dec1(m.hours)} running hours · {dec1(m.downtime_30d)} h down in 30 days
        {next && <> · next: {next.task.toLowerCase()}</>}</p>
      {m.open_logs.map((l) => <OpenLog key={l.id} l={l} onDone={onDone} onError={onError} />)}
      {reporting ? (
        <form className="inline-form" onSubmit={report}>
          <label className="field full"><span>What is wrong</span>
            <input required autoFocus value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
          <label className="check full"><input type="checkbox" checked={stops} onChange={(e) => setStops(e.target.checked)} />
            Machine cannot run{m.work_center ? ` (blocks station ${m.work_center})` : ""}</label>
          <button className="btn">Report breakdown</button>
          <button type="button" className="btn ghost" onClick={() => setReporting(false)}>Back</button>
        </form>
      ) : <button className="link danger" onClick={() => setReporting(true)}>Report a breakdown</button>}
    </div>
  );
}

function OpenLog({ l, onDone, onError }: { l: MaintenanceLog; onDone: (t: string) => Promise<void>; onError: (t: string) => void }) {
  const [closing, setClosing] = useState(false);
  const [f, setF] = useState({ action_taken: "", done_by: "", parts_cost: "" });
  const close = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/api/maintenance-logs/${l.id}/close/`, { method: "POST", body: { ...f, parts_cost: f.parts_cost || "0" } });
      await onDone(`${l.machine} repair recorded${l.machine_down ? "; the machine is back in use" : ""}.`);
    } catch (err) { onError(errText(err)); }
  };
  return (
    <div className="open-log">
      <p className="small"><b>{l.machine_down ? "Down since" : "Reported"} {when(l.reported_at)}:</b> {l.description}
        {l.reported_by && <span className="muted"> ({l.reported_by})</span>}</p>
      {closing ? (
        <form className="inline-form" onSubmit={close}>
          <label className="field full"><span>What was done</span>
            <input required autoFocus value={f.action_taken} onChange={(e) => setF({ ...f, action_taken: e.target.value })} /></label>
          <label className="field"><span>By</span>
            <input value={f.done_by} onChange={(e) => setF({ ...f, done_by: e.target.value })} /></label>
          <label className="field"><span>Parts cost (ETB)</span>
            <input type="number" min="0" step="any" value={f.parts_cost} onChange={(e) => setF({ ...f, parts_cost: e.target.value })} /></label>
          <button className="btn">Close and return to use</button>
        </form>
      ) : <button className="btn ghost" onClick={() => setClosing(true)}>Record repair</button>}
    </div>
  );
}

function PlanRow({ p, onDone, onError }: { p: PlanStatus; onDone: (t: string) => Promise<void>; onError: (t: string) => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ done_by: "", notes: "", parts_cost: "" });
  const every = [p.every_hours && `${dec1(p.every_hours)} h`, p.every_days && `${p.every_days} ${plural(p.every_days, "day")}`]
    .filter(Boolean).join(" or ");
  const past = p.due_date !== null && new Date(p.due_date) < new Date(new Date().toDateString());
  const left = [
    p.hours_left !== null && (Number(p.hours_left) < 0 ? `${dec1(-Number(p.hours_left))} h over` : `${dec1(p.hours_left)} h`),
    p.due_date && (past ? `due since ${day(p.due_date)}` : `by ${day(p.due_date)}`),
  ].filter(Boolean).join(", ");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/api/maintenance-plans/${p.id}/done/`, { method: "POST", body: { ...f, parts_cost: f.parts_cost || "0" } });
      setOpen(false);
      await onDone(`${p.machine}: “${p.task}” recorded. The next one is counted from now.`);
    } catch (err) { onError(errText(err)); }
  };
  return (
    <>
      <tr>
        <td className="mono small">{p.machine}</td>
        <td>{p.task}</td>
        <td className="small">{every}</td>
        <td className="small">{day(p.last_done_at)} <span className="muted">at {dec1(p.last_done_hours)} h</span></td>
        <td className="small">{left}</td>
        <td><span className={`chip m-${p.state}`}>{STATE_LABEL[p.state]}</span></td>
        <td>{!open && <button className="link" onClick={() => setOpen(true)}>Mark done</button>}</td>
      </tr>
      {open && (
        <tr><td colSpan={7}>
          <form className="inline-form" onSubmit={submit}>
            <label className="field"><span>Done by</span><input autoFocus value={f.done_by} onChange={(e) => setF({ ...f, done_by: e.target.value })} /></label>
            <label className="field"><span>Notes</span><input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
            <label className="field"><span>Parts cost (ETB)</span><input type="number" min="0" step="any" value={f.parts_cost} onChange={(e) => setF({ ...f, parts_cost: e.target.value })} /></label>
            <button className="btn">Record service</button>
            <button type="button" className="btn ghost" onClick={() => setOpen(false)}>Back</button>
          </form>
        </td></tr>
      )}
    </>
  );
}
