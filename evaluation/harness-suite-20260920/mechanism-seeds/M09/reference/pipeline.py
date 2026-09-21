import csv
import json
from pathlib import Path

from report import build_report


def load_rows(source: Path, required_fields: list[str]) -> list[dict[str, str]]:
    with source.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing = set(required_fields) - set(rows[0] if rows else ())
    if missing:
        raise ValueError(f"missing report fields: {sorted(missing)}")
    return rows


def run_pipeline(config_path: Path, root: Path) -> Path:
    config = json.loads(config_path.read_text())
    rows = load_rows(root / config["source"], config["required_fields"])
    if config["renderer"] == "pdf":
        raise RuntimeError("PDF renderer unavailable; choose documented html fallback")
    output_dir = root / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ("daily_sales." + config["renderer"])
    build_report(rows, output, renderer=config["renderer"])
    return output
