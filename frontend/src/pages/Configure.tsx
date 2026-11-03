import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, ApiError, choiceLabel, choiceValue, Customer, Explosion, Item, Order, OrderLine, Page, Parameter, Template,
} from "../api";
import { dec1, money, qty as fmtQty, today } from "../format";

const VAT = 0.15;
type Values = Record<string, string>;

export default function Configure() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [code, setCode] = useState("");
  const [template, setTemplate] = useState<Template | null>(null);
  const [items, setItems] = useState<Record<string, Item>>({});
  const [values, setValues] = useState<Values>({});
  const [quantity, setQuantity] = useState("1");
  const [margin, setMargin] = useState("30");
  const [result, setResult] = useState<Explosion | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Page<Template>>("/api/templates/?sellable=1").then((p) => {
      setTemplates(p.results);
      if (p.results.length) setCode(p.results[0].code);
    });
    api<Page<Item>>("/api/items/?page_size=500").then((p) =>
      setItems(Object.fromEntries(p.results.map((i) => [i.code, i]))),
    );
  }, []);

  useEffect(() => {
    if (!code) return;
    api<Template>(`/api/templates/${code}/`).then((t) => {
      setTemplate(t);
      setValues(Object.fromEntries(t.parameters.map((p) => [p.name, p.default])));
    });
  }, [code]);

  // Re-explode shortly after the last change.
  const seq = useRef(0);
  useEffect(() => {
    if (!template) return;
    const mine = ++seq.current;
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const params = Object.fromEntries(
          template.parameters.map((p) => [p.name, p.kind === "number" ? Number(values[p.name]) : values[p.name]]),
        );
        const r = await api<Explosion>(`/api/templates/${template.code}/explode/`, {
          method: "POST", body: { params, qty: Number(quantity) || 1 },
        });
        if (mine === seq.current) { setResult(r); setErrors([]); }
      } catch (e) {
        if (mine === seq.current) setErrors(e instanceof ApiError ? e.messages : ["Could not reach the server."]);
      } finally {
        if (mine === seq.current) setBusy(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [template, values, quantity]);

  const q = Number(quantity) || 1;
  const m = Math.min(Math.max(Number(margin) || 0, 0), 95) / 100;
  const total = result ? Number(result.estimate.total) : 0;
  const price = total / (1 - m);

  return (
    <section>
      <h2>Configure and quote</h2>
      <p className="lead">
        Choose the sizes and options. Parts, hardware, machine time and price are worked out from the product's
        formulas. Parts that fit an offcut in stock are listed so the cutting team uses it before a new sheet.
      </p>
      <div className="split">
        <div className="panel stack">
          <label className="field">
            <span>Product</span>
            <select id="template" value={code} onChange={(e) => setCode(e.target.value)}>
              {templates.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select>
          </label>
          {template && (
            <ParamFields params={template.parameters} values={values} items={items}
              onChange={(name, v) => setValues((old) => ({ ...old, [name]: v }))} />
          )}
          <div className="fields two">
            <label className="field">
              <span>Quantity</span>
              <input id="qty" type="number" min="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </label>
            <label className="field">
              <span>Target margin %</span>
              <input id="margin" type="number" min="0" max="95" value={margin} onChange={(e) => setMargin(e.target.value)} />
            </label>
          </div>
          {errors.length > 0 && <ul className="error">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
          {template && result && errors.length === 0 && (
            <AddToQuote template={template} values={values} quantity={quantity} margin={m} />
          )}
        </div>

        <div className={`stack ${busy ? "stale" : ""}`}>
          {result && (
            <>
              <div className="kpis">
                <Kpi value={money(price / q)} label="Price per unit, ex VAT" />
                <Kpi value={money(total / q)} label="Cost per unit" />
                <Kpi value={dec1(sumMinutes(result) / 60)} label={`Shop hours for ${q}`} />
                <Kpi value={String(result.offcut_matches.length)} label="Parts that fit offcuts" />
              </div>
              <Bom result={result} items={items} />
              <div className="split even">
                <Routing result={result} />
                <div className="panel">
                  <h3>Price build-up, {q} unit{q > 1 ? "s" : ""}</h3>
                  <dl className="lines">
                    <Line label="Material" v={result.estimate.material} />
                    <Line label="Operator labour" v={result.estimate.labour} />
                    <Line label="Machine time" v={result.estimate.machine} />
                    <Line label="Factory overhead" v={result.estimate.overhead} />
                    <Line label="Total cost" v={total} strong />
                    <Line label={`Margin ${dec1(m * 100)}%`} v={price - total} />
                    <Line label="Price ex VAT" v={price} strong />
                    <Line label="VAT 15%" v={price * VAT} />
                    <Line label="Price incl. VAT" v={price * (1 + VAT)} strong />
                  </dl>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function ParamFields({ params, values, items, onChange }: {
  params: Parameter[]; values: Values; items: Record<string, Item>; onChange: (name: string, v: string) => void;
}) {
  const numbers = params.filter((p) => p.kind === "number");
  const others = params.filter((p) => p.kind !== "number");
  return (
    <>
      <div className="fields">
        {numbers.map((p) => (
          <label className="field" key={p.name}>
            <span>{p.label}</span>
            <input id={`p-${p.name}`} type="number" value={values[p.name] ?? ""}
              min={p.min_value ?? undefined} max={p.max_value ?? undefined}
              onChange={(e) => onChange(p.name, e.target.value)} />
          </label>
        ))}
      </div>
      {others.map((p) => {
        const options = p.kind === "choice"
          ? p.choices.map((c) => [choiceValue(c), choiceLabel(c)])
          : (p.choices.length ? p.choices.map(choiceValue) : Object.values(items).filter((i) => i.kind === p.item_kind).map((i) => i.code))
              .map((c) => [c, items[c]?.name ?? c]);
        return (
          <label className="field" key={p.name}>
            <span>{p.label}</span>
            <select id={`p-${p.name}`} value={values[p.name] ?? ""} onChange={(e) => onChange(p.name, e.target.value)}>
              {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        );
      })}
    </>
  );
}

function Bom({ result, items }: { result: Explosion; items: Record<string, Item> }) {
  const groups = useMemo(() => {
    const g = new Map<string, { panels: Explosion["panels"]; items: Explosion["items"] }>();
    const get = (k: string) => {
      if (!g.has(k)) g.set(k, { panels: [], items: [] });
      return g.get(k)!;
    };
    result.panels.forEach((p) => get(p.path || "Unit").panels.push(p));
    result.items.forEach((i) => get(i.path || "Unit").items.push(i));
    return [...g.entries()];
  }, [result]);
  const offcutsFor = (p: Explosion["panels"][number]) =>
    result.offcut_matches.filter((o) => o.panel === p.name && o.path === p.path).map((o) => o.offcut);
  const name = (code: string) => items[code]?.name ?? code;

  return (
    <div className="panel">
      <h3>Bill of materials</h3>
      {groups.map(([path, g]) => (
        <details open key={path}>
          <summary>{path}</summary>
          <div className="tbl">
            <table>
              {g.panels.length > 0 && (
                <thead>
                  <tr><th>Part</th><th>Material</th><th className="num">Length</th><th className="num">Width</th>
                    <th className="num">Qty</th><th className="num">Edge m</th><th>Source</th></tr>
                </thead>
              )}
              <tbody>
                {g.panels.map((p) => {
                  const oc = offcutsFor(p);
                  return (
                    <tr key={p.name}>
                      <td>{p.name}{p.grain_locked && <span className="chip">grain</span>}</td>
                      <td>{name(p.item_code)}</td>
                      <td className="num">{dec1(p.length_mm)}</td>
                      <td className="num">{dec1(p.width_mm)}</td>
                      <td className="num">{fmtQty(p.qty)}</td>
                      <td className="num">{Number(p.edge_m) ? dec1(p.edge_m) : "–"}</td>
                      <td>{oc.length ? <span className="chip oc">{oc.length} from {oc.join(", ")}</span> : <span className="chip">sheet</span>}</td>
                    </tr>
                  );
                })}
                {g.items.map((i) => (
                  <tr key={i.name + i.item_code} className="sub">
                    <td colSpan={4}>{name(i.item_code)}</td>
                    <td className="num">{fmtQty(i.qty)} {items[i.item_code]?.base_uom ?? ""}</td>
                    <td colSpan={2}></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
      <p className="note">
        Totals: {Object.entries(result.material_totals).map(([c, v]) => `${name(c)} ${fmtQty(v)} ${items[c]?.base_uom ?? ""}`).join(" · ")}
      </p>
    </div>
  );
}

function Routing({ result }: { result: Explosion }) {
  return (
    <div className="panel">
      <h3>Routing</h3>
      <div className="tbl">
        <table>
          <thead><tr><th>Step</th><th className="num">Minutes</th></tr></thead>
          <tbody>
            {result.operations.map((o, i) => (
              <tr key={i}><td>{o.path}: {o.description}</td><td className="num">{dec1(o.minutes)}</td></tr>
            ))}
            <tr className="total"><td>Total</td><td className="num">{dec1(sumMinutes(result))}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AddToQuote({ template, values, quantity, margin }: {
  template: Template; values: Values; quantity: string; margin: number;
}) {
  const navigate = useNavigate();
  const [quotes, setQuotes] = useState<Order[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [target, setTarget] = useState("new");
  const [customer, setCustomer] = useState("");
  const [newCustomer, setNewCustomer] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<Page<Order>>("/api/sales-orders/?status=quote").then((p) => setQuotes(p.results));
    api<Page<Customer>>("/api/customers/?page_size=500").then((p) => setCustomers(p.results));
  }, []);

  const add = async () => {
    setSaving(true);
    setError("");
    try {
      let orderId = Number(target);
      if (target === "new") {
        let customerId = Number(customer);
        if (customer === "" || customer === "new") {
          if (!newCustomer.trim()) throw new ApiError(400, ["Choose a customer or type a new customer's name."]);
          customerId = (await api<Customer>("/api/customers/", { method: "POST", body: { name: newCustomer.trim() } })).id;
        }
        orderId = (await api<Order>("/api/sales-orders/", {
          method: "POST", body: { customer: customerId, order_date: today(), target_margin: margin.toFixed(4) },
        })).id;
      }
      const params = Object.fromEntries(
        template.parameters.map((p) => [p.name, p.kind === "number" ? Number(values[p.name]) : values[p.name]]),
      );
      await api<OrderLine>("/api/sales-order-lines/", {
        method: "POST", body: { order: orderId, template_code: template.code, configuration: params, quantity },
      });
      navigate(`/quotes/${orderId}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="addq stack">
      <h3>Add to a quote</h3>
      <label className="field">
        <span>Quote</span>
        <select id="quote" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="new">New quote</option>
          {quotes.map((o) => <option key={o.id} value={o.id}>{o.number} · {o.customer_name}</option>)}
        </select>
      </label>
      {target === "new" && (
        <>
          <label className="field">
            <span>Customer</span>
            <select id="customer" value={customer} onChange={(e) => setCustomer(e.target.value)}>
              <option value="">New customer…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          {customer === "" && (
            <label className="field">
              <span>New customer name</span>
              <input id="new-customer" value={newCustomer} onChange={(e) => setNewCustomer(e.target.value)} />
            </label>
          )}
        </>
      )}
      {error && <p className="error">{error}</p>}
      <button className="btn" onClick={add} disabled={saving}>{saving ? "Adding…" : "Add to quote"}</button>
    </div>
  );
}

const sumMinutes = (r: Explosion) => r.operations.reduce((s, o) => s + Number(o.minutes), 0);

function Kpi({ value, label }: { value: string; label: string }) {
  return <div className="kpi"><b>{value}</b><span>{label}</span></div>;
}

function Line({ label, v, strong }: { label: string; v: string | number; strong?: boolean }) {
  return (
    <div className={strong ? "strong" : ""}>
      <dt>{label}</dt>
      <dd className="num">{money(v)}</dd>
    </div>
  );
}
