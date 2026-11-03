PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    min_stock INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    sold_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transaction_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
    line_total INTEGER NOT NULL CHECK(line_total >= 0),
    UNIQUE(transaction_id, product_id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE RESTRICT,
    movement_type TEXT NOT NULL CHECK(movement_type IN ('initial', 'sale', 'restock', 'adjustment')),
    delta INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ((movement_type='sale' AND delta<0) OR (movement_type IN ('initial','restock') AND delta>=0) OR movement_type='adjustment')
);

CREATE INDEX IF NOT EXISTS idx_transactions_sold_at ON transactions(sold_at);
CREATE INDEX IF NOT EXISTS idx_items_product ON transaction_items(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_product ON stock_movements(product_id);

CREATE VIEW IF NOT EXISTS product_inventory AS
SELECT p.id, p.sku, p.name, p.category, p.unit_price, p.min_stock,
       COALESCE(SUM(sm.delta), 0) AS current_stock
FROM products p
LEFT JOIN stock_movements sm ON sm.product_id = p.id
GROUP BY p.id;

-- V1.2 idempotency for manually entered sales. CREATE IF NOT EXISTS also upgrades v1.1 databases.
CREATE TABLE IF NOT EXISTS manual_sale_requests (
    request_key TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);


-- v1.3c: application-level append-only audit of authenticated business writes.
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE RESTRICT,
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    before_json TEXT,
    after_json TEXT,
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_action_id ON audit_events(action,id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'Audit events tidak boleh diubah'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'Audit events tidak boleh dihapus'); END;

-- v1.4b: per-product replenishment parameters. Historical rows untouched.
CREATE TABLE IF NOT EXISTS reorder_settings (
    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE RESTRICT,
    lead_time_days INTEGER NOT NULL CHECK(lead_time_days BETWEEN 1 AND 365),
    safety_stock_units INTEGER NOT NULL CHECK(safety_stock_units BETWEEN 0 AND 1000000),
    review_days INTEGER NOT NULL CHECK(review_days BETWEEN 1 AND 90),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
