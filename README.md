# Betewubet ERP

ERP for Betewubet Home and Office Furniture Manufacturing PLC: parametric product configuration and BOMs, multi-UOM inventory with offcuts and lots, production and shop-floor tracking, job costing, and Ethiopian VAT-compliant finance.

This repository currently holds **Phase 1 (foundation)** of the [architecture and roadmap](https://claude.ai/artifact/GvjCjLUhYQCujGbkgjcVRy): the backend for the catalogue, parametric BOMs, inventory, quotes, sales orders, work orders and job costing, and the staff screens: sign-in, configure and quote, quotes and orders, work orders with estimated vs actual cost, inventory (stock, offcuts, receiving goods) and the shop-floor station screen.

## How it fits together

| App | What it owns |
| --- | --- |
| `core` | Units of measure, work centers with ETB hourly rates, company cost settings (overhead, nesting yield, VAT 15%) |
| `catalog` | Items (raw materials and bought-in parts only), product templates with parameters, formula-driven BOM lines and routing, the formula engine and BOM explosion |
| `inventory` | Locations, lots, the append-only stock ledger, offcuts with exact sizes |
| `sales` | Customers (with TIN and VAT number), quotes and sales orders, configured order lines, pricing from target margin |
| `production` | Work orders with frozen BOM and estimate, planned materials and operations, shop-floor time logs, estimated vs actual job cost |
| `purchasing` | Suppliers with pack prices, shortages (open work orders + reorder level − stock − on order), purchase orders and receiving against them |
| `maintenance` | Machines with running hours from station time, service plans due by hours or days, breakdowns that block their station until repaired |

Three rules hold the design together:

1. **Products are templates, not part numbers.** A base cabinet is one template with width, height, depth, board, front finish, drawer count and handle as parameters. BOM lines and routing steps use formulas such as `W - 2*board_t`, so any size can be quoted without creating a new item.
2. **Every stock movement is a ledger row.** Stock moves are never edited or deleted; on-hand quantity and value are sums over the ledger. Boards are stocked in m², edgeband in metres, finishes in litres, hardware in pieces, with pack sizes (sheet, roll, drum) per item.
3. **The work order is the costing unit.** Confirming a sales order explodes each line, freezes the BOM and cost estimate on a work order, and from then on material issues and scanned time post against it.

## Formulas

Formulas are a small safe language: numbers, parameter names, `+ - * / // % **`, comparisons, `and`/`or`/`not`, `x if cond else y`, and `min max abs round ceil floor`. Item parameters also expose their thickness as `<name>_t`. Routing formulas may also use `n_panels`, `panel_m2`, `edge_m` and `front_m2` for the template's own panels.

```
H - 2*board_t                       # bottom panel length
2 if W > 600 else 1                 # one or two doors
drawers > 0 and front == 'lac'      # line condition
0.4*edge_m + 0.5*n_panels           # edgebander minutes
```

## Running it locally

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo           # sample units, materials, cabinet templates, opening stock
python manage.py createsuperuser
python manage.py runserver
```

Then open http://localhost:8000/admin/ for the back office, or http://localhost:8000/api/ for the API.

In a second terminal, start the staff web app (React + TypeScript, in `frontend/`):

```bash
cd frontend
npm install
npm run dev
```

and open http://localhost:5173. It forwards `/api` and `/admin` to the Django server on port 8000, so sign in with the user you created above. If the web app runs at another address, add it to `CSRF_TRUSTED_ORIGINS`.

Without `DATABASE_URL` the project uses SQLite. To run with PostgreSQL instead: `docker compose up`, or copy `.env.example` to `.env` and point `DATABASE_URL` at your server.

The sample prices loaded by `seed_demo` are illustrative ETB figures, not real supplier prices.

## Main API endpoints

| Endpoint | Use |
| --- | --- |
| `POST /api/templates/BASE-CAB/explode/` | Configure a product: `{"params": {"W": 800, "drawers": 3}, "qty": 4}` returns parts, hardware, routing, cost estimate and offcuts that fit |
| `/api/sales-orders/`, `/api/sales-order-lines/` | Quotes and orders; lines are priced on save from the target margin |
| `POST /api/sales-orders/{id}/confirm/` | Quote to order; creates one work order per line |
| `GET /api/work-orders/{id}/cost/` | Estimated vs actual cost: material, labour, machine, overhead |
| `GET /api/work-orders/{id}/cut-list/` | Panels to cut grouped by board, with part IDs and a sheet estimate |
| `GET /api/work-orders/{id}/cut-list/csv/` | The same cut list as CSV for nesting software |
| `GET /api/operations/?work_center=EDGE`, `POST .../start/`, `POST .../stop/` | What a station tablet uses |
| `POST /api/work-centers/{code}/scan/` | A label scanned at a station: `WO-000001` starts the job's step there; `WO-000001-P03-2` also records piece 2 of part 3 |
| `/api/stock-moves/`, `/api/lots/`, `/api/offcuts/` | Inventory ledger, lots and offcuts |
| `GET /api/auth/me/`, `POST /api/auth/login/`, `POST /api/auth/logout/` | Sign-in for the web app (session cookie + CSRF) |
| `GET /api/stock/` | On hand per item in base and pack units, with lots, value and reorder status |
| `POST /api/stock/receive/`, `POST /api/stock/issue/` | Goods received (in packs or base units, lot created if new); material issued to a work order |
| `POST /api/offcuts/register/` | Put a leftover board piece in stock (300 x 300 mm minimum) |
| `/api/work-centers/`, `/api/non-conformances/` | Stations; rejects reported at stations, each with its rework order |
| `GET /api/purchasing/shortages/` | Items short for open work orders and reorder levels, with the suggested supplier and packs |
| `POST /api/purchasing/draft-orders/` | One draft purchase order per supplier for the current shortages (optional `{"items": [...]}`) |
| `/api/purchase-orders/`, `POST .../send/`, `.../cancel/`, `.../receive/` | Purchase orders; receiving books stock at the order price with the PO number as reference |
| `/api/suppliers/`, `/api/supplier-items/` | Suppliers and what each sells, in which pack, at what price |
| `/api/machines/`, `POST /api/machines/{code}/breakdown/` | Machines with hours, state, open breakdowns and service status; report a breakdown |
| `GET /api/maintenance/due/`, `POST /api/maintenance-plans/{id}/done/` | Service schedule, most urgent first; record a service done |
| `/api/maintenance-logs/`, `POST .../close/` | Service and breakdown history; record the repair that closes a breakdown |

## Tests

```bash
cd backend && python -m pytest -q
cd frontend && npm run build      # type-checks and builds the web app
```

The test suite runs on every pull request against PostgreSQL 16 (see `.github/workflows/tests.yml`).
