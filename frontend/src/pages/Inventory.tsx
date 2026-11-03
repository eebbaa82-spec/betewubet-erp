import { FormEvent, useEffect, useMemo, useState } from "react";

import { api, ApiError, Location, Offcut, Page, StockRow } from "../api";
import { dec2, money, plural, qty as fmtQty } from "../format";

const KINDS = [["", "All"], ["board", "Boards"], ["edgeband", "Edgeband"], ["hardware", "Hardware"],
  ["finish", "Finishes"], ["consumable", "Consumables"]] as const;

type Tab = "stock" | "offcuts" | "receive";

export default function Inventory() {
  const [tab, setTab] = useState<Tab>("stock");
  return (
    <section>
      <h2>Inventory</h2>
      <p className="lead">
        Stock in the unit each material is used in: boards in m² and sheets, edgeband in metres and rolls, finishes in
        litres, hardware in pieces. Every receipt has a lot, so a project can stay on one batch or dye lot.
      </p>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "stock"} onClick={() => setTab("stock")}>Stock on hand</button>
        <button role="tab" aria-selected={tab === "offcuts"} onClick={() => setTab("offcuts")}>Offcuts</button>
        <button role="tab" aria-selected={tab === "receive"} onClick={() => setTab("receive")}>Receive goods</button>
      </div>
      {tab === "stock" && <Stock />}
      {tab === "offcuts" && <Offcuts />}
      {tab === "receive" && <Receive onDone={() => setTab("stock")} />}
    </section>
  );
}

function Stock() {
  const [kind, setKind] = useState("");
  const [rows, setRows] = useState<StockRow[] | null>(null);
  useEffect(() => {
    setRows(null);
    api<StockRow[]>(`/api/stock/${kind ? `?kind=${kind}` : ""}`).then(setRows);
  }, [kind]);
  const total = useMemo(() => (rows ?? []).reduce((s, r) => s + Number(r.value), 0), [rows]);

  return (
    <div className="panel">
      <div className="row between">
        <div className="tabs small-tabs">
          {KINDS.map(([v, l]) => (
            <button key={v} aria-selected={kind === v} onClick={() => setKind(v)}>{l}</button>
          ))}
        </div>
        {rows && <span className="muted">Stock value {money(total)}</span>}
      </div>
      {rows === null ? <p className="muted">Loading…</p> : (
        <div className="tbl">
          <table>
            <thead>
              <tr><th>Item</th><th className="num">On hand</th><th className="num">In packs</th>
                <th className="num">Unit cost</th><th className="num">Value</th><th>Lots</th><th>Status</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code}>
                  <td><b>{r.name}</b><div className="mono small muted">{r.code}</div></td>
                  <td className="num">{fmtQty(r.on_hand)} {r.base_uom}
                    {r.in_offcuts && Number(r.in_offcuts) > 0 && (
                      <div className="small muted">incl. {dec2(r.in_offcuts)} {r.base_uom} in offcuts</div>
                    )}
                  </td>
                  <td className="num">{r.pack ? `${fmtQty(r.on_hand_packs!)} ${plural(r.on_hand_packs!, r.pack)}` : "–"}</td>
                  <td className="num">{dec2(r.unit_cost)}/{r.base_uom}</td>
                  <td className="num">{money(r.value)}</td>
                  <td className="small">
                    {r.lots.length === 0 ? <span className="muted">not lot-tracked</span> : r.lots.map((l) => (
                      <div key={l.code}><span className="mono">{l.code}</span>{l.colour_ref && ` · ${l.colour_ref}`} · {fmtQty(l.qty)}</div>
                    ))}
                  </td>
                  <td>{r.below_reorder ? <span className="chip bad">Below reorder ({fmtQty(r.reorder_level!)})</span>
                    : <span className="chip okc">OK</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Offcuts() {
  const [status, setStatus] = useState("available");
  const [rows, setRows] = useState<Offcut[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const load = () => api<Page<Offcut>>(`/api/offcuts/?page_size=500${status ? `&status=${status}` : ""}`)
    .then((p) => setRows(p.results));
  useEffect(() => { setRows(null); load(); }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="stack">
      <div className="panel">
        <div className="row between">
          <div className="tabs small-tabs">
            {[["available", "Available"], ["reserved", "Reserved"], ["used", "Used"], ["", "All"]].map(([v, l]) => (
              <button key={v} aria-selected={status === v} onClick={() => setStatus(v)}>{l}</button>
            ))}
          </div>
          <button className="btn ghost" onClick={() => setShowAdd((v) => !v)}>{showAdd ? "Close" : "Put an offcut in stock"}</button>
        </div>
        {showAdd && <AddOffcut onDone={() => { setShowAdd(false); load(); }} />}
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <p className="muted">No offcuts here.</p> : (
          <div className="tbl">
            <table>
              <thead>
                <tr><th>Label</th><th>Material</th><th className="num">Size mm</th><th className="num">m²</th>
                  <th>Lot</th><th>Rack</th><th>Cut from</th><th>Status</th></tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id}>
                    <td className="mono">{o.code}</td>
                    <td>{o.item_name}</td>
                    <td className="num">{o.length_mm} x {o.width_mm}</td>
                    <td className="num">{dec2(o.area_m2)}</td>
                    <td className="mono small">{o.lot_code || "–"}</td>
                    <td className="mono">{o.location_code}</td>
                    <td className="mono small">{o.source_work_order_number || "–"}</td>
                    <td><span className={`chip ${o.status === "available" ? "oc" : ""}`}>{o.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="note">Pieces smaller than 300 x 300 mm are scrap and are not kept.</p>
      </div>
    </div>
  );
}

function AddOffcut({ onDone }: { onDone: () => void }) {
  const [boards, setBoards] = useState<StockRow[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [f, setF] = useState({ item: "", length_mm: "", width_mm: "", location: "", work_order: "" });
  const [error, setError] = useState("");
  useEffect(() => {
    api<StockRow[]>("/api/stock/?kind=board").then((b) => { setBoards(b); setF((x) => ({ ...x, item: b[0]?.code ?? "" })); });
    api<Page<Location>>("/api/locations/").then((p) => {
      setLocations(p.results);
      setF((x) => ({ ...x, location: (p.results.find((l) => l.is_offcut_rack) ?? p.results[0])?.code ?? "" }));
    });
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api("/api/offcuts/register/", { method: "POST", body: { ...f, work_order: f.work_order.trim().toUpperCase() || null } });
      onDone();
    } catch (err) { setError(err instanceof ApiError ? err.message : "Could not save."); }
  };
  return (
    <form className="inline-form" onSubmit={submit}>
      <label className="field"><span>Board</span>
        <select id="oc-item" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })}>
          {boards.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
        </select></label>
      <label className="field"><span>Length mm</span>
        <input id="oc-l" type="number" required value={f.length_mm} onChange={(e) => setF({ ...f, length_mm: e.target.value })} /></label>
      <label className="field"><span>Width mm</span>
        <input id="oc-w" type="number" required value={f.width_mm} onChange={(e) => setF({ ...f, width_mm: e.target.value })} /></label>
      <label className="field"><span>Rack</span>
        <select id="oc-loc" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })}>
          {locations.map((l) => <option key={l.code} value={l.code}>{l.code} · {l.name}</option>)}
        </select></label>
      <label className="field"><span>From work order (optional)</span>
        <input id="oc-wo" placeholder="WO-000001" value={f.work_order} onChange={(e) => setF({ ...f, work_order: e.target.value })} /></label>
      <button className="btn">Add offcut</button>
      {error && <p className="error full">{error}</p>}
    </form>
  );
}

function Receive({ onDone }: { onDone: () => void }) {
  const [rows, setRows] = useState<StockRow[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [f, setF] = useState({ item: "", qty: "", unit: "", unit_cost: "", location: "", lot_code: "",
    supplier_batch: "", colour_ref: "", reference: "" });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    api<StockRow[]>("/api/stock/").then(setRows);
    api<Page<Location>>("/api/locations/").then((p) => {
      setLocations(p.results);
      setF((x) => ({ ...x, location: (p.results.find((l) => !l.is_offcut_rack) ?? p.results[0])?.code ?? "" }));
    });
  }, []);
  const item = rows.find((r) => r.code === f.item);
  const units = item ? [item.pack, item.base_uom].filter(Boolean) as string[] : [];
  const tracked = item?.track_lots ?? false;

  const pick = (code: string) => {
    const r = rows.find((x) => x.code === code);
    setF({ ...f, item: code, unit: r?.pack ?? r?.base_uom ?? "" });
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setSaved("");
    try {
      await api("/api/stock/receive/", { method: "POST", body: f });
      setSaved(`Received ${f.qty} ${plural(f.qty, f.unit)} of ${item?.name}.`);
      setF({ ...f, qty: "", unit_cost: "", lot_code: "", supplier_batch: "", colour_ref: "", reference: "" });
    } catch (err) { setError(err instanceof ApiError ? err.message : "Could not save."); }
  };

  return (
    <form className="panel stack narrow" onSubmit={submit}>
      <label className="field"><span>Item</span>
        <select id="rc-item" required value={f.item} onChange={(e) => pick(e.target.value)}>
          <option value="">Choose an item…</option>
          {rows.map((r) => <option key={r.code} value={r.code}>{r.name} ({r.code})</option>)}
        </select></label>
      <div className="fields">
        <label className="field"><span>Quantity</span>
          <input id="rc-qty" type="number" step="any" required value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} /></label>
        <label className="field"><span>Unit</span>
          <select id="rc-unit" value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })}>
            {units.map((u) => <option key={u} value={u}>{u}</option>)}
          </select></label>
        <label className="field"><span>Cost per {f.unit || "unit"}, ETB</span>
          <input id="rc-cost" type="number" step="any" required value={f.unit_cost} onChange={(e) => setF({ ...f, unit_cost: e.target.value })} /></label>
      </div>
      {item?.pack && f.unit === item.pack && f.qty && (
        <p className="note">= {fmtQty(Number(f.qty) * Number(item.pack_size))} {item.base_uom} in stock</p>
      )}
      <div className="fields two">
        <label className="field"><span>Location</span>
          <select id="rc-loc" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })}>
            {locations.map((l) => <option key={l.code} value={l.code}>{l.code} · {l.name}</option>)}
          </select></label>
        <label className="field"><span>GRN or invoice no.</span>
          <input id="rc-ref" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></label>
      </div>
      {tracked && (
        <div className="fields">
          <label className="field"><span>Lot / batch</span>
            <input id="rc-lot" required value={f.lot_code} onChange={(e) => setF({ ...f, lot_code: e.target.value })} /></label>
          <label className="field"><span>Supplier batch</span>
            <input id="rc-batch" value={f.supplier_batch} onChange={(e) => setF({ ...f, supplier_batch: e.target.value })} /></label>
          <label className="field"><span>Colour / dye lot</span>
            <input id="rc-colour" value={f.colour_ref} onChange={(e) => setF({ ...f, colour_ref: e.target.value })} /></label>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {saved && <p className="ok">{saved} <button type="button" className="link" onClick={onDone}>See stock</button></p>}
      <button className="btn">Receive</button>
    </form>
  );
}
