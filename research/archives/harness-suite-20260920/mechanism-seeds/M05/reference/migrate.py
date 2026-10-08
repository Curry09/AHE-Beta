import sqlite3


def apply_migration(connection: sqlite3.Connection) -> None:
    if "status" not in {r[1] for r in connection.execute("PRAGMA table_info(orders)")}:
        with connection:
            connection.execute("ALTER TABLE orders ADD COLUMN status TEXT")


def rollback_migration(connection: sqlite3.Connection) -> None:
    if "status" in {r[1] for r in connection.execute("PRAGMA table_info(orders)")}:
        with connection:
            connection.execute("ALTER TABLE orders DROP COLUMN status")
