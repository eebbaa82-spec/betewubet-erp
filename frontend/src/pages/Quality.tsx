import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, AwaitingFinal, Checklist, Inspection, Page } from "../api";
import InspectionForm from "../InspectionForm";
import { configSummary, qty as fmtQty } from "../format";

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Quality() {
  const [tab, setTab] = useState<"final" | "history">("final");
  return (
    <section className="stack">
      <div>
        <h2>Quality</h2>
        <p className="lead">Final inspection before a job can be put on a delivery note, and every station and final
          inspection with its result. A failed check with pieces to rework opens a non-conformance and a rework order.</p>
      </div>
      <div className="tabs small-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "final"} onClick={() => setTab("final")}>Final inspection</button>
        <button role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}>Inspection history</button>
      </div>
      {tab === "final" ? <Final /> : <History />}
    </section>
  );
}

function Final() {
  const [rows, setRows] = useState<AwaitingFinal[] | null>(null);
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [flash, setFlash] = useState<{ kind: string; text: string } | null>(null);
  const load = useCallback(async () => {
    const [r, c] = await Promise.all([api<AwaitingFinal[]>("/api/quality/awaiting-final/"), api<Checklist[]>("/api/checklists/?stage=final")]);
    setRows(r); setChecklist(c[0] ?? null);
  }, []);
  useEffect(() => { load(); }, [load]);
  if (rows === null) return <p className="muted">Loading…</p>;
  if (!checklist) return <div className="panel"><p className="muted">No final inspection checklist is set up, so finished
    jobs can ship without one. Add one in the back office under Quality.</p></div>;
  return (
    <div className="stack">
      {flash && <p className={flash.kind} role="status">{flash.text}</p>}
      {rows.length === 0 ? <div className="panel"><p className="muted">No finished jobs are waiting for final inspection.</p></div> :
        rows.map((w) => (
          <div className="panel" key={w.id}>
            <div className="row between tight">
              <div><Link className="mono" to={`/work-orders/${w.id}`}>{w.number}</Link>
                {w.last_result === "fail" && <span className="chip bad">Failed last time</span>}
                <div className="op-title">{w.product} <span className="muted">x {fmtQty(w.quantity)}</span></div>
                <div className="small muted">{configSummary(w.configuration)}{w.customer && ` · ${w.order_number} · ${w.customer}`}</div></div>
              {open !== w.id && <button className="btn" onClick={() => setOpen(w.id)}>Inspect</button>}
            </div>
            {open === w.id && <InspectionForm checklist={checklist} workOrderId={w.id} maxQty={Number(w.quantity)}
              onCancel={() => setOpen(null)}
              onDone={async (i) => {
                setOpen(null);
                setFlash(i.result === "pass" ? { kind: "ok", text: `${w.number} passed final inspection (${i.number}) and can now be shipped.` }
                  : { kind: "error", text: `${w.number} failed (${i.number}).${i.non_conformance ? ` ${i.non_conformance} opened, rework order ${i.rework_order}.` : ""}` });
                await load();
              }} />}
          </div>
        ))}
    </div>
  );
}

function History() {
  const [rows, setRows] = useState<Inspection[] | null>(null);
  useEffect(() => { api<Page<Inspection>>("/api/inspections/?page_size=100").then((p) => setRows(p.results)); }, []);
  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) return <div className="panel"><p className="muted">No inspections recorded yet.</p></div>;
  const passRate = Math.round((rows.filter((r) => r.result === "pass").length / rows.length) * 100);
  return (
    <div className="panel">
      <p className="muted">Last {rows.length} inspections · {passRate}% passed first time or on recheck.</p>
      <div className="tbl">
        <table>
          <thead><tr><th>When</th><th>Inspection</th><th>Job</th><th>Result</th><th>Failed checks</th><th>Follow-up</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="small mono">{when(r.created_at)}</td>
                <td><span className="mono small">{r.number}</span> {r.checklist_name}
                  <div className="small muted">{r.work_center || "final"}{r.inspector && ` · ${r.inspector}`}</div></td>
                <td><Link className="mono small" to={`/work-orders/${r.work_order_id}`}>{r.work_order}</Link>
                  <div className="small muted">{r.product}{r.customer && ` · ${r.customer}`}</div></td>
                <td><span className={`chip ${r.result === "fail" ? "bad" : "pass"}`}>{r.result_label}</span></td>
                <td className="small">{r.results.filter((x) => !x.passed).map((x) =>
                  <div key={x.item}>{x.text}{x.value !== null && ` (${x.value})`}{x.note && ` – ${x.note}`}</div>)}
                  {r.result === "pass" && <span className="muted">–</span>}</td>
                <td className="small">{r.non_conformance ? <>{r.non_conformance} · rework {r.rework_order} ({fmtQty(r.failed_qty)})</> : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
