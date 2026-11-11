-- AI Buyer Agent - mock purchasing database.
-- One SQLite file per scenario run (see db.py). Every table maps to a piece of
-- information the assignment says a buyer has access to.

-- Simulation clock + run metadata. "Today" is frozen so runs are reproducible.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Fulfillment nodes (dark stores / warehouses).
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    city    TEXT NOT NULL
);

-- Product master. Replenishment policy lives on the product:
--   review_period_days : how often we re-plan this SKU (order cycle)
--   safety_stock_days  : buffer kept against forecast error / supplier delay
--   shelf_life_days    : NULL for non-perishables; caps how much we can buy
CREATE TABLE products (
    sku                TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    category           TEXT NOT NULL,          -- budgets are per category
    storage_zone       TEXT NOT NULL,          -- 'ambient' | 'chilled'
    case_pack          INTEGER NOT NULL,       -- orders must be multiples of this
    shelf_life_days    INTEGER,
    review_period_days INTEGER NOT NULL,
    safety_stock_days  INTEGER NOT NULL
);

-- Supplier master + historical performance (used to judge reliability).
CREATE TABLE suppliers (
    supplier_id  TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    on_time_rate REAL NOT NULL,                -- share of POs delivered on time (0-1)
    fill_rate    REAL NOT NULL,                -- share of ordered units delivered (0-1)
    is_approved  INTEGER NOT NULL DEFAULT 1    -- unapproved vendors cannot receive POs
);

-- Commercial terms per supplier x SKU. This is what the agent can SEE.
CREATE TABLE supplier_products (
    supplier_id           TEXT NOT NULL REFERENCES suppliers(supplier_id),
    sku                   TEXT NOT NULL REFERENCES products(sku),
    unit_cost             REAL NOT NULL,
    moq                   INTEGER NOT NULL,     -- minimum order quantity (units)
    lead_time_days        INTEGER NOT NULL,
    listed_capacity_units INTEGER NOT NULL,     -- what the catalog SAYS they can supply
    is_primary            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (supplier_id, sku)
);

-- What the supplier can ACTUALLY ship right now. Hidden from the agent's read
-- tools; only the mock supplier API uses it when a PO is submitted. This models
-- the real world: catalog data is stale, the supplier's confirmation is the truth.
CREATE TABLE supplier_live_availability (
    supplier_id     TEXT NOT NULL,
    sku             TEXT NOT NULL,
    available_units INTEGER NOT NULL,
    PRIMARY KEY (supplier_id, sku)
);

-- Stock on hand per node. last_counted_at lets the agent judge data freshness.
CREATE TABLE inventory (
    node_id         TEXT NOT NULL REFERENCES nodes(node_id),
    sku             TEXT NOT NULL REFERENCES products(sku),
    on_hand         INTEGER NOT NULL,
    last_counted_at TEXT NOT NULL,
    PRIMARY KEY (node_id, sku)
);

-- Actual daily sales (past).
CREATE TABLE sales_history (
    node_id    TEXT NOT NULL,
    sku        TEXT NOT NULL,
    date       TEXT NOT NULL,
    units_sold INTEGER NOT NULL,
    PRIMARY KEY (node_id, sku, date)
);

-- Daily demand forecast (future), produced by an upstream forecasting system.
CREATE TABLE forecasts (
    node_id        TEXT NOT NULL,
    sku            TEXT NOT NULL,
    date           TEXT NOT NULL,
    forecast_units REAL NOT NULL,
    PRIMARY KEY (node_id, sku, date)
);

-- Known promotions - explains demand spikes that should NOT be extrapolated.
CREATE TABLE promotions (
    promo_id   TEXT PRIMARY KEY,
    node_id    TEXT NOT NULL,
    sku        TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    description TEXT NOT NULL
);

-- Storage capacity per node x zone. Other SKUs' occupancy is summarised as one
-- number so we don't have to model the full assortment.
CREATE TABLE storage_capacity (
    node_id                TEXT NOT NULL,
    zone                   TEXT NOT NULL,
    capacity_units         INTEGER NOT NULL,
    occupied_by_other_skus INTEGER NOT NULL,
    PRIMARY KEY (node_id, zone)
);

-- Open-to-buy budget per category per month.
-- remaining = budget_amount - spent_to_date - value of open POs in category
CREATE TABLE budgets (
    category      TEXT NOT NULL,
    period        TEXT NOT NULL,                -- 'YYYY-MM'
    budget_amount REAL NOT NULL,
    spent_to_date REAL NOT NULL,
    PRIMARY KEY (category, period)
);

-- Purchase orders. Simplification: one SKU per PO (real POs have lines).
-- Status lifecycle:
--   PENDING_APPROVAL -> SUBMITTED -> CONFIRMED | PARTIALLY_CONFIRMED | REJECTED
--   any open status  -> CANCELLED ;  CONFIRMED -> RECEIVED
CREATE TABLE purchase_orders (
    po_id            TEXT PRIMARY KEY,
    supplier_id      TEXT NOT NULL REFERENCES suppliers(supplier_id),
    node_id          TEXT NOT NULL REFERENCES nodes(node_id),
    sku              TEXT NOT NULL REFERENCES products(sku),
    qty_ordered      INTEGER NOT NULL,
    qty_confirmed    INTEGER,                   -- NULL until supplier responds
    unit_cost        REAL NOT NULL,
    status           TEXT NOT NULL,
    expected_arrival TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    created_by       TEXT NOT NULL,             -- 'system' | 'agent' | 'human'
    parent_po_id     TEXT,                      -- links a replacement/top-up PO to its origin
    notes            TEXT
);

-- Output of the upstream replenishment engine. NOT assumed to be correct.
CREATE TABLE recommendations (
    rec_id          TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    sku             TEXT NOT NULL,
    supplier_id     TEXT NOT NULL,
    recommended_qty INTEGER NOT NULL,
    reason          TEXT NOT NULL,             -- how the engine says it got the number
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN'
);

-- Inbound messages from suppliers (e.g. "can only ship 250 of 500").
CREATE TABLE supplier_events (
    event_id     TEXT PRIMARY KEY,
    po_id        TEXT NOT NULL,
    supplier_id  TEXT NOT NULL,
    event_type   TEXT NOT NULL,                 -- 'PARTIAL_CONFIRMATION' | ...
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- Human-in-the-loop queue: things the agent could not / should not decide alone.
CREATE TABLE escalations (
    escalation_id TEXT PRIMARY KEY,
    run_id        TEXT,
    kind          TEXT NOT NULL,                -- 'APPROVAL' | 'INVESTIGATION' | 'BUDGET_INCREASE' | ...
    po_id         TEXT,
    summary       TEXT NOT NULL,
    details_json  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN' | 'APPROVED' | 'REJECTED'
    created_at    TEXT NOT NULL
);

-- Append-only trail of every state change (who changed what, and why).
CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT,
    actor      TEXT NOT NULL,                   -- 'agent' | 'supplier_api' | 'human' | 'system'
    action     TEXT NOT NULL,
    entity_id  TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
