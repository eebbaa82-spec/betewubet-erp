// Thin client for the Django REST API. Uses the session cookie and sends the CSRF token on writes.

export class ApiError extends Error {
  constructor(public status: number, public messages: string[]) {
    super(messages.join(" "));
  }
}

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function flatten(data: unknown): string[] {
  if (data == null) return [];
  if (typeof data === "string") return [data];
  if (Array.isArray(data)) return data.flatMap(flatten);
  if (typeof data === "object") {
    return Object.entries(data as Record<string, unknown>).flatMap(([k, v]) =>
      flatten(v).map((msg) => (k === "detail" || k === "non_field_errors" ? msg : `${k}: ${msg}`)),
    );
  }
  return [String(data)];
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = csrfToken();
  }
  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msgs = flatten(data);
    throw new ApiError(res.status, msgs.length ? msgs : [`Request failed (${res.status}).`]);
  }
  return data as T;
}

export interface Page<T> {
  count: number;
  results: T[];
}

export interface User {
  id: number;
  username: string;
  name: string;
  is_staff: boolean;
}

export type Choice = string | [string, string];

export interface Parameter {
  name: string;
  label: string;
  kind: "number" | "choice" | "item";
  default: string;
  min_value: string | null;
  max_value: string | null;
  choices: Choice[];
  item_kind: string;
}

export interface Template {
  id: number;
  code: string;
  name: string;
  description: string;
  parameters: Parameter[];
}

export interface Item {
  id: number;
  code: string;
  name: string;
  kind: string;
  base_uom: string;
  standard_cost: string;
}

export interface Panel {
  path: string;
  name: string;
  item_code: string;
  length_mm: string;
  width_mm: string;
  qty: string;
  edge_m: string;
  edge_item_code: string;
  grain_locked: boolean;
}

export interface Estimate {
  material: string;
  labour: string;
  machine: string;
  overhead: string;
  total: string;
  minutes: Record<string, string>;
}

export interface Explosion {
  template_code: string;
  params: Record<string, string | number>;
  panels: Panel[];
  items: { path: string; name: string; item_code: string; qty: string }[];
  operations: { path: string; work_center_code: string; description: string; minutes: string }[];
  material_totals: Record<string, string>;
  minutes_by_work_center: Record<string, string>;
  estimate: Estimate;
  offcut_matches: { panel: string; path: string; offcut: string; offcut_size_mm: [number, number] }[];
}

export interface Customer {
  id: number;
  name: string;
  tin: string;
  vat_reg_no: string;
  phone: string;
}

export interface OrderLine {
  id: number;
  order: number;
  template_code: string;
  template_name: string;
  configuration: Record<string, string | number>;
  description: string;
  quantity: string;
  estimated_unit_cost: string;
  unit_price: string;
  price_locked: boolean;
  line_total: string;
}

export interface Order {
  id: number;
  number: string;
  customer: number;
  customer_name: string;
  order_type: string;
  status: string;
  status_label: string;
  order_date: string;
  due_date: string | null;
  target_margin: string | null;
  notes: string;
  lines: OrderLine[];
  totals: {
    subtotal: string;
    vat_rate: string;
    vat: string;
    total: string;
    estimated_cost: string;
    estimated_margin_pct: string;
  };
}

export function choiceValue(c: Choice) {
  return Array.isArray(c) ? c[0] : c;
}
export function choiceLabel(c: Choice) {
  return Array.isArray(c) ? c[1] : c;
}
