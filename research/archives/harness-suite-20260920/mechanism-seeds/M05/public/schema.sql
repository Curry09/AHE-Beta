CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0)
);
CREATE INDEX orders_by_tenant ON orders(tenant_id);

INSERT INTO orders(id, tenant_id, total_cents) VALUES
    (1, 'acme', 1200),
    (2, 'globex', 500);
