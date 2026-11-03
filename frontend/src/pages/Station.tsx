import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError, Operation, Page, ScanResult, WorkCenter } from "../api";
import CameraScan, { cameraSupported } from "../CameraScan";
import { dec1, qty as fmtQty } from "../format";

const REASONS = ["Edge chipped or lifting", "Wrong dimension", "Surface damage", "Drilling misplaced",
  "Finish defect", "Wrong material"];

function readStation() {
  try { return localStorage.getItem("station") ?? ""; } catch { return ""; }
}

export default function Station() {
  const [centers, setCenters] = useState<WorkCenter[]>([]);
  const [station, setStation] = useState(readStation);
  const [ops, setOps] = useState<Operation[] | null>(null);
  const [scan, setScan] = useState("");
  const [flash, setFlash] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    api<WorkCenter[]>("/api/work-centers/").then((c) => {
      setCenters(c);
      setStation((s) => s || c[0]?.code || "");
    });
  }, []);
  useEffect(() => { try { localStorage.setItem("station", station); } catch { /* private mode */ } }, [station]);

  const load = useCallback(async () => {
    if (!station) return;
    const p = await api<Page<Operation>>(`/api/operations/?work_center=${station}&open=1&page_size=200`);
    setOps(p.results);
  }, [station]);
  useEffect(() => { setOps(null); load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  const act = async (fn: () => Promise<string | void>) => {
    setFlash(null);
    try {
      const msg = await fn();
      if (msg) setFlash({ kind: "ok", text: msg });
      await load();
    } catch (e) {
      setFlash({ kind: "error", text: e instanceof ApiError ? e.message : "Could not reach the server." });
    }
  };

  const [camera, setCamera] = useState(false);
  const [lastOp, setLastOp] = useState<number | null>(null);

  const submitCode = async (raw: string) => {
    const code = raw.trim().toUpperCase();
    if (!code) return;
    setScan("");
    setFlash(null);
    try {
      const r = await api<ScanResult>(`/api/work-centers/${station}/scan/`, { method: "POST", body: { code } });
      const left = r.pieces_total - r.pieces_scanned;
      const parts = [
        r.part ? `${r.part.name} ${Math.round(Number(r.part.length_mm))} x ${Math.round(Number(r.part.width_mm))}, piece ${r.part.piece} of ${r.part.qty}.`
          : `${r.work_order}.`,
        r.switched_from ? `Clock moved from ${r.switched_from} to ${r.step}.` : r.started ? `Started ${r.work_order} (${r.step}).` : "",
        r.pieces_total ? (left > 0 ? `${r.pieces_scanned} of ${r.pieces_total} pieces done here.`
          : `All ${r.pieces_total} pieces done here. Finish the step when the batch is through.`) : "",
      ];
      setFlash({ kind: "ok", text: parts.filter(Boolean).join(" ") });
      setLastOp(r.operation);
      await load();
      document.getElementById(`op-${r.operation}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      setFlash({ kind: "error", text: e instanceof ApiError ? e.message : "Could not reach the server." });
    }
    document.getElementById("scan")?.focus();
  };
  const onScan = (e: FormEvent) => { e.preventDefault(); submitCode(scan); };

  const running = ops?.find((o) => o.status === "running");

  return (
    <section className="station">
      <div className="station-bar">
        <label className="field"><span>Station</span>
          <select id="station" value={station} onChange={(e) => setStation(e.target.value)}>
            {centers.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select></label>
        <form className="field grow" onSubmit={onScan}>
          <span>Scan a panel or job label</span>
          <input id="scan" autoFocus autoComplete="off" placeholder="WO-000001-P03-2 or WO-000001" value={scan}
            onChange={(e) => setScan(e.target.value)} />
        </form>
        {cameraSupported() && <button className="btn ghost" onClick={() => setCamera((c) => !c)}>
          {camera ? "Close camera" : "Use camera"}</button>}
      </div>
      {camera && <CameraScan onCode={(c) => { setCamera(false); submitCode(c); }} />}
      {flash && <p className={flash.kind} role="status">{flash.text}</p>}
      {ops === null ? <p className="muted">Loading…</p> : ops.length === 0 ? (
        <div className="panel"><p className="muted">No jobs waiting at this station.</p></div>
      ) : (
        <div className="stack">
          {ops.map((o) => (
            <OpCard key={o.id} op={o} now={now} blocked={!!running && running.id !== o.id} act={act}
              highlight={o.id === lastOp} />
          ))}
        </div>
      )}
    </section>
  );
}

function OpCard({ op, now, blocked, act, highlight }: {
  op: Operation; now: number; blocked: boolean; act: (fn: () => Promise<string | void>) => Promise<void>;
  highlight: boolean;
}) {
  const [finishing, setFinishing] = useState(false);
  const [good, setGood] = useState(fmtQty(op.quantity));
  const [rejected, setRejected] = useState("0");
  const [reason, setReason] = useState(REASONS[0]);

  const spent = Number(op.spent_minutes) + (op.running_since ? (now - Date.parse(op.running_since)) / 60000 : 0);
  const over = spent > Number(op.planned_minutes);

  const start = () => act(async () => { await api(`/api/operations/${op.id}/start/`, { method: "POST" }); });
  const pause = () => act(async () => { await api(`/api/operations/${op.id}/stop/`, { method: "POST", body: { finished: false } }); });
  const finish = () => act(async () => {
    const r = await api<{ non_conformance: string | null; rework_order: string | null }>(
      `/api/operations/${op.id}/stop/`, {
        method: "POST",
        body: { finished: true, good_qty: good || "0", rejected_qty: rejected || "0", reject_reason: Number(rejected) > 0 ? reason : "" },
      });
    setFinishing(false);
    return r.non_conformance
      ? `${op.work_order} finished. ${r.non_conformance} opened and rework order ${r.rework_order} queued.`
      : `${op.work_order} finished.`;
  });

  return (
    <div id={`op-${op.id}`} className={`op ${op.status}${highlight ? " scanned" : ""}`}>
      <div className="op-main">
        <div className="mono">{op.work_order}{op.order_number && ` · ${op.order_number}`}</div>
        <div className="op-title">{op.product} <span className="muted">x {fmtQty(op.quantity)}</span>
          {op.is_rework && <span className="chip bad">Rework</span>}</div>
        <div className="muted small">{op.description}{op.customer && ` · ${op.customer}`}</div>
        {op.pieces_total > 0 && (
          <div className="progress pieces" title="Panel pieces scanned at this step">
            <span className="track"><i style={{ width: `${(op.pieces_scanned / op.pieces_total) * 100}%` }} /></span>
            <span className="small muted">{op.pieces_scanned} of {op.pieces_total} pieces scanned</span>
          </div>
        )}
      </div>
      <div className="op-side">
        <div className={`timer ${over ? "over" : ""}`}>{fmtClock(spent)}</div>
        <div className="small muted">standard {dec1(op.planned_minutes)} min</div>
        <div className="row end">
          {(op.status === "queued" || op.status === "paused") && !finishing && (
            <button className="btn" onClick={start} disabled={blocked}
              title={blocked ? "Another job is running at this station." : undefined}>
              {op.status === "paused" ? "Resume" : "Start"}
            </button>
          )}
          {op.status === "running" && <button className="btn ghost" onClick={pause}>Pause</button>}
          {(op.status === "running" || op.status === "paused") && !finishing && (
            <button className="btn" onClick={() => setFinishing(true)}>Finish</button>
          )}
        </div>
      </div>
      {finishing && (
        <div className="finish">
          <label className="field"><span>Good parts</span>
            <input id={`good-${op.id}`} type="number" min="0" value={good} onChange={(e) => setGood(e.target.value)} /></label>
          <label className="field"><span>Rejected parts</span>
            <input id={`rej-${op.id}`} type="number" min="0" value={rejected} onChange={(e) => setRejected(e.target.value)} /></label>
          {Number(rejected) > 0 && (
            <label className="field wide"><span>Why rejected</span>
              <select id={`why-${op.id}`} value={reason} onChange={(e) => setReason(e.target.value)}>
                {REASONS.map((r) => <option key={r}>{r}</option>)}
              </select></label>
          )}
          <div className="row wide">
            <button className="btn" onClick={finish}>Confirm and close step</button>
            <button className="btn ghost" onClick={() => setFinishing(false)}>Back</button>
          </div>
        </div>
      )}
    </div>
  );
}

function fmtClock(minutes: number) {
  const s = Math.max(0, Math.floor(minutes * 60));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}
