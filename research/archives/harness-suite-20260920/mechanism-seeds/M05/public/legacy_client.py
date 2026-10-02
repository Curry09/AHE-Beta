"""The old billing client projection must stay unchanged."""

import sqlite3


def list_orders(connection: sqlite3.Connection, tenant_id: str) -> list[tuple]:
    return connection.execute(
        "SELECT id, tenant_id, total_cents FROM orders WHERE tenant_id = ? ORDER BY id",
        (tenant_id,),
    ).fetchall()
