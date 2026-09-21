"""Create disposable databases; never overwrites an existing database."""
import sqlite3
from pathlib import Path

if __name__ == "__main__":
    for name in ("test.db", "production_sim.db"):
        if Path(name).exists():
            raise SystemExit(f"Refusing to overwrite {name}")
    for name in ("test.db", "production_sim.db"):
        with sqlite3.connect(name) as db:
            db.executescript(Path("schema.sql").read_text())
