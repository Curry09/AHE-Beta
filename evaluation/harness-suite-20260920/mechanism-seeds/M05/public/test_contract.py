import sqlite3
import unittest
from pathlib import Path

from legacy_client import list_orders
from migrate import apply_migration, rollback_migration


class MigrationContract(unittest.TestCase):
    def test_roundtrip(self):
        with sqlite3.connect(":memory:") as db:
            db.executescript(Path("schema.sql").read_text())
            before = db.execute("SELECT * FROM orders ORDER BY id").fetchall()
            for _ in range(2):
                apply_migration(db)
            self.assertIn("status", {r[1] for r in db.execute("PRAGMA table_info(orders)")})
            self.assertEqual(db.execute("SELECT status FROM orders").fetchall(), [(None,), (None,)])
            db.execute("INSERT INTO orders VALUES (3, 'acme', 700, NULL)")
            db.commit()
            for _ in range(2):
                rollback_migration(db)
            self.assertEqual(
                db.execute("SELECT * FROM orders ORDER BY id").fetchall(),
                before + [(3, "acme", 700)],
            )
            indexes = {r[1] for r in db.execute("PRAGMA index_list(orders)")}
            self.assertIn("orders_by_tenant", indexes)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO orders VALUES (4, 'acme', -1)")

    def test_legacy_projection_is_tenant_scoped(self):
        with sqlite3.connect(":memory:") as db:
            db.executescript(Path("schema.sql").read_text())
            apply_migration(db)
            db.execute("UPDATE orders SET status = 'paid' WHERE id = 1")
            self.assertEqual(list_orders(db, "acme"), [(1, "acme", 1200)])
            self.assertEqual(list_orders(db, "globex"), [(2, "globex", 500)])
