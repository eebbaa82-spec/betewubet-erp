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

export interface StockRow {
  code: string;
  name: string;
  kind: string;
  base_uom: string;
  track_lots: boolean;
  on_hand: string;
  pack: string | null;
  pack_size: string | null;
  on_hand_packs: string | null;
  in_offcuts: string | null;
  unit_cost: string;
  value: string;
  reorder_level: string | null;
  below_reorder: boolean;
  lots: { code: string; colour_ref: string; qty: string }[];
}

export interface Offcut {
  id: number;
  code: string;
  item_code: string;
  item_name: string;
  length_mm: number;
  width_mm: number;
  area_m2: string;
  location_code: string;
  lot_code: string;
  status: string;
  source_work_order_number: string;
  created_at: string;
}

export interface Location {
  id: number;
  code: string;
  name: string;
  is_offcut_rack: boolean;
}

export interface WorkCenter {
  code: string;
  name: string;
}

export interface Operation {
  id: number;
  work_order: string;
  work_order_id: number;
  sequence: number;
  work_center: string;
  description: string;
  planned_minutes: string;
  status: "queued" | "running" | "paused" | "done";
  product: string;
  quantity: string;
  order_number: string;
  customer: string;
  is_rework: boolean;
  spent_minutes: string;
  running_since: string | null;
  pieces_total: number;
  pieces_scanned: number;
}

export interface ScanResult {
  operation: number;
  work_order: string;
  step: string;
  started: boolean;
  switched_from: string | null;
  part: { part_id: string; piece: number; qty: number; name: string; length_mm: string; width_mm: string; material: string } | null;
  pieces_total: number;
  pieces_scanned: number;
}

export interface WorkOrder {
  id: number;
  number: string;
  product: string;
  configuration: Record<string, string | number>;
  quantity: string;
  status: string;
  status_label: string;
  due_date: string | null;
  order_number: string;
  order_id: number | null;
  customer: string;
  rework_of: string | null;
  estimate: Partial<Estimate>;
  materials: { item: string; item_name: string; uom: string; planned_qty: string; issued_qty: string }[];
  operations: Operation[];
  non_conformances: { number: string; work_center: string; qty: string; reason: string; rework_order: string | null; created_at: string }[];
  created_at: string;
}

export type CostLine = { estimate: string; actual: string; variance: string };
export type CostVariance = Record<"material" | "labour" | "machine" | "overhead" | "total", CostLine>;

export interface CutPart {
  part_id: string;
  name: string;
  path: string;
  length_mm: string;
  width_mm: string;
  qty: number;
  grain_locked: boolean;
  edge_item: string;
  edge_name: string;
  edge_mm_per_piece: string;
}

export interface CutList {
  work_order: string;
  product: string;
  quantity: string;
  order_number: string;
  customer: string;
  due_date: string | null;
  nesting_yield: string;
  total_pieces: number;
  materials: {
    item: string;
    item_name: string;
    thickness_mm: string | null;
    sheet: string;
    pieces: number;
    area_m2: string;
    sheets_estimate: number | null;
    parts: CutPart[];
  }[];
}

export interface Shortage {
  item: string;
  item_name: string;
  kind: string;
  uom: string;
  required: string;
  reorder_level: string;
  in_stock: string;
  on_order: string;
  short: string;
  supplier: string | null;
  pack_name: string | null;
  pack_qty: string | null;
  suggested_packs: number | null;
  price_per_pack: string | null;
  amount: string | null;
}

export interface PurchaseOrderLine {
  id: number;
  item: string;
  item_name: string;
  uom: string;
  track_lots: boolean;
  pack_name: string;
  pack_qty: string;
  packs: string;
  price_per_pack: string;
  received_packs: string;
  open_packs: string;
  amount: string;
}

export interface PurchaseOrder {
  id: number;
  number: string;
  supplier: number;
  supplier_name: string;
  supplier_tin: string;
  status: "draft" | "sent" | "partial" | "received" | "cancelled";
  status_label: string;
  order_date: string;
  expected_date: string | null;
  notes: string;
  lines: PurchaseOrderLine[];
  totals: { subtotal: string; vat_rate: string; vat: string; total: string };
  created_at: string;
}

export interface MaintenanceLog {
  id: number;
  machine: string;
  machine_name: string;
  kind: "preventive" | "breakdown";
  kind_label: string;
  plan: number | null;
  description: string;
  machine_down: boolean;
  reported_at: string;
  reported_by: string;
  closed_at: string | null;
  action_taken: string;
  done_by: string;
  parts_cost: string;
  machine_hours: string | null;
  is_open: boolean;
  downtime_minutes: string;
}

export interface PlanStatus {
  id: number;
  machine: string;
  machine_name: string;
  task: string;
  instructions: string;
  every_hours: string | null;
  every_days: number | null;
  last_done_at: string;
  last_done_hours: string;
  hours_now: string;
  hours_left: string | null;
  due_date: string | null;
  used: string;
  state: "overdue" | "soon" | "ok";
}

export interface Machine {
  id: number;
  code: string;
  name: string;
  work_center: string | null;
  make_model: string;
  serial_no: string;
  hours: string;
  downtime_30d: string;
  state: "down" | "overdue" | "soon" | "ok";
  open_logs: MaintenanceLog[];
  plans: PlanStatus[];
}
