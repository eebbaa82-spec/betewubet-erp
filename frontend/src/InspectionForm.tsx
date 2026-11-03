import { FormEvent, useState } from "react";

import { api, ApiError, Checklist, Inspection } from "./api";
import { dec1 } from "./format";

type Answer = { passed: boolean | null; value: string; note: string };

/** Fill in a checklist for one work order. Measurements are judged against target ± tolerance. */
export default function InspectionForm({ checklist, workOrderId, operationId, maxQty, onDone, onCancel }: {
  checklist: Checklist; workOrderId: number; operationId?: number; maxQty: number;
  onDone: (i: Inspection) => void; onCancel: () => void;
}) {
  const [a, setA] = useState<Record<number, Answer>>(
    Object.fromEntries(checklist.items.map((i) => [i.id, { passed: i.kind === "measure" ? null : true, value: "", note: "" }])));
  const [failedQty, setFailedQty] = useState("1");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const judged = checklist.items.map((i) => {
    const x = a[i.id];
    if (i.kind === "measure") {
      if (x.value === "" || i.target === null) return x.value === "" ? null : true;
      return Math.abs(Number(x.value) - Number(i.target)) <= Number(i.tolerance ?? 0);
    }
    return x.passed;
  });
  const failing = judged.some((p) => p === false);
  const set = (id: number, patch: Partial<Answer>) => setA({ ...a, [id]: { ...a[id], ...patch } });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api<Inspection>("/api/inspections/", { method: "POST", body: {
        work_order: workOrderId, checklist: checklist.id, operation: operationId ?? null, notes,
        failed_qty: failing ? failedQty || "0" : "0",
        answers: checklist.items.map((i) => ({ item: i.id, passed: i.kind === "measure" ? null : a[i.id].passed,
          value: i.kind === "measure" ? a[i.id].value : null, note: a[i.id].note })) } });
      onDone(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
      setBusy(false);
    }
  };

  return (
    <form className="inspection" onSubmit={submit}>
      <h3>{checklist.name}</h3>
      <ol className="checks">
        {checklist.items.map((i, n) => (
          <li key={i.id} className={judged[n] === false ? "failing" : ""}>
            <span className="check-text">{i.text}
              {i.kind === "measure" && i.target !== null && <span className="small muted"> target {dec1(i.target)} ± {dec1(i.tolerance ?? 0)}</span>}</span>
            {i.kind === "measure" ? (
              <input className="cell" type="number" step="any" required aria-label={i.text} value={a[i.id].value}
                onChange={(e) => set(i.id, { value: e.target.value })} />
            ) : (
              <span className="passfail" role="group" aria-label={i.text}>
                <button type="button" aria-pressed={a[i.id].passed === true} onClick={() => set(i.id, { passed: true })}>Pass</button>
                <button type="button" aria-pressed={a[i.id].passed === false} className="fail" onClick={() => set(i.id, { passed: false })}>Fail</button>
              </span>
            )}
            {judged[n] === false && <input className="check-note" placeholder="What is wrong (optional)" value={a[i.id].note}
              onChange={(e) => set(i.id, { note: e.target.value })} />}
          </li>
        ))}
      </ol>
      <div className="inline-form">
        {failing && <label className="field"><span>Pieces to rework</span>
          <input type="number" min="0" max={maxQty} step="any" value={failedQty} onChange={(e) => setFailedQty(e.target.value)} /></label>}
        <label className="field"><span>Notes</span><input value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        <button className={`btn ${failing ? "danger" : ""}`} disabled={busy}>
          {failing ? (Number(failedQty) > 0 ? "Record fail and send to rework" : "Record fail") : "Record pass"}</button>
        <button type="button" className="btn ghost" onClick={onCancel}>Back</button>
        {error && <p className="error full">{error}</p>}
      </div>
    </form>
  );
}
