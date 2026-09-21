"""Safe, reversible schema migration exercise."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def apply_migration(connection: sqlite3.Connection) -> None:
    """Add the nullable status column without changing existing rows."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
    if "status" not in columns:
        with connection:
            connection.execute("ALTER TABLE orders ADD COLUMN status TEXT")


def rollback_migration(connection: sqlite3.Connection) -> None:
    """Candidate rollback: audit data, constraints and index preservation."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
    if "status" not in columns:
        return
    with connection:
        connection.execute("ALTER TABLE orders RENAME TO orders_with_status")
        connection.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "total_cents INTEGER NOT NULL CHECK (total_cents >= 0))"
        )
        connection.execute(
            "INSERT INTO orders(id, tenant_id, total_cents) "
            "SELECT id, tenant_id, total_cents FROM orders_with_status"
        )
        connection.execute("DROP TABLE orders_with_status")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("action", choices=("apply", "rollback"))
    args = parser.parse_args()
    with sqlite3.connect(args.db) as connection:
        (apply_migration if args.action == "apply" else rollback_migration)(connection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
