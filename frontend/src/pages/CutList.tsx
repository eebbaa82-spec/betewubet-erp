import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, CutList as CutListData, CutPart, url } from "../api";
import { dec2, plural } from "../format";

type View = "list" | "labels";

const mm = (v: string) => String(Math.round(Number(v)));

export default function CutList() {
  const { id } = useParams();
  const [cl, setCl] = useState<CutListData | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("list");
  useEffect(() => {
    api<CutListData>(`/api/work-orders/${id}/cut-list/`).then(setCl).catch(() => setError("Work order not found."));
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!cl) return <p className="muted">Loading…</p>;

  return (
    <section className="stack">
      <div className="no-print">
        <p className="muted"><Link to={`/work-orders/${id}`}>{cl.work_order}</Link></p>
        <h2>Cut list · {cl.product}</h2>
        <p className="muted">
          {`${cl.total_pieces} ${plural(cl.total_pieces, "piece")}`} from {`${cl.materials.length} ${plural(cl.materials.length, "board")}`}
          {cl.customer && <> · {cl.order_number} · {cl.customer}</>}
          {cl.due_date && <> · due {cl.due_date}</>}
        </p>
      </div>

      {cl.materials.length === 0 ? (
        <div className="panel"><p className="muted">This work order has no panels to cut.</p></div>
      ) : (
        <>
          <div className="toolbar no-print">
            <div className="tabs" role="tablist">
              <button role="tab" aria-selected={view === "list"} onClick={() => setView("list")}>Cut list</button>
              <button role="tab" aria-selected={view === "labels"} onClick={() => setView("labels")}>Panel labels</button>
            </div>
            <a className="btn ghost" href={url(`/api/work-orders/${id}/cut-list/csv/`)} download>Download CSV</a>
            <button className="btn" onClick={() => window.print()}>Print {view === "list" ? "cut list" : "labels"}</button>
          </div>
          {view === "list" ? <Sheets cl={cl} /> : <Labels cl={cl} />}
        </>
      )}
    </section>
  );
}

function Sheets({ cl }: { cl: CutListData }) {
  return (
    <>
      <p className="print-only"><strong>{cl.work_order}</strong> · {cl.product} x {cl.quantity}
        {cl.customer && <> · {cl.order_number} · {cl.customer}</>}</p>
      {cl.materials.map((g) => (
        <div className="panel cut-group" key={g.item}>
          <div className="cut-head">
            <h3>{g.item_name} <span className="mono">{g.item}</span></h3>
            <span className="small muted">
              {`${g.pieces} ${plural(g.pieces, "piece")}`} · {dec2(g.area_m2)} m² · about {g.sheets_estimate ?? "?"} sheets
              {g.sheet && <> of {g.sheet} mm</>} at {Math.round(Number(cl.nesting_yield) * 100)}% yield
            </span>
          </div>
          <div className="tbl">
            <table>
              <thead><tr><th>Part</th><th>Name</th><th className="num">Length</th><th className="num">Width</th>
                <th className="num">Qty</th><th>Grain</th><th>Edgeband</th></tr></thead>
              <tbody>
                {g.parts.map((p) => (
                  <tr key={p.part_id}>
                    <td className="mono small">{p.part_id}</td>
                    <td>{p.name}<div className="small muted">{p.path}</div></td>
                    <td className="num">{mm(p.length_mm)}</td>
                    <td className="num">{mm(p.width_mm)}</td>
                    <td className="num">{p.qty}</td>
                    <td>{p.grain_locked ? <span className="chip">locked</span> : <span className="muted">free</span>}</td>
                    <td className="small">{p.edge_item ? <>{p.edge_name}<div className="muted">{p.edge_mm_per_piece} mm per piece</div></> : <span className="muted">none</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}

function Labels({ cl }: { cl: CutListData }) {
  const labels = cl.materials.flatMap((g) =>
    g.parts.flatMap((p) => Array.from({ length: p.qty }, (_, i) => ({ g, p, n: i + 1 }))));
  return (
    <>
      <p className="note no-print">
        {labels.length} {plural(labels.length, "label")}, one per piece, sized 70 x 37 mm for A4 sheets of 24. The QR code holds the part ID and piece number, for scanning at stations.
      </p>
      <div className="labels">
        {labels.map(({ g, p, n }) => (
          <Label key={`${p.part_id}-${n}`} part={p} n={n} board={g.item}
            thickness={g.thickness_mm} cl={cl} />
        ))}
      </div>
    </>
  );
}

function Label({ part, n, board, thickness, cl }: { part: CutPart; n: number; board: string; thickness: string | null; cl: CutListData }) {
  const [qr, setQr] = useState("");
  useEffect(() => {
    QRCode.toString(`${part.part_id}-${n}`, { type: "svg", margin: 0, errorCorrectionLevel: "M" }).then(setQr);
  }, [part.part_id, n]);
  return (
    <div className="label">
      <div className="qr" aria-label={`QR code ${part.part_id}-${n}`} dangerouslySetInnerHTML={{ __html: qr }} />
      <div className="label-text">
        <strong>{part.name}</strong>
        <span className="mono">{mm(part.length_mm)} x {mm(part.width_mm)}{thickness ? ` x ${Math.round(Number(thickness))}` : ""}</span>
        <span>{board}{part.grain_locked ? " · grain ↕" : ""}</span>
        {part.edge_item && <span>Edge {part.edge_item}</span>}
        <span className="mono">{part.part_id} · {n}/{part.qty}</span>
        <span className="trunc">{cl.customer || cl.product}</span>
      </div>
    </div>
  );
}
