#!/usr/bin/env python3
"""Freeze the materialized N>1 runtime bundles and emit launch receipts.

This command is intentionally fail-closed: it never marks a bundle launchable
unless every assigned task has both agent and grader payloads and an explicit
full-loop canary receipt.  The package is a manifest plus content-addressed
payload paths; the E2B executor uploads only the selected task payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
PREPARED = SUITE / "prepared" / "scaling-e2b-20260922"
CONFIG = SUITE / "configs" / "scaling-e2b-20260922.json"
MIXED = SUITE / "configs" / "mixed-scaling-20260922.json"
ASSIGNMENTS = SUITE / "configs" / "mixed-scaling-20260922.tasks.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze(n: int, canary: dict | None) -> Path:
    folder = PREPARED / f"n{n}"
    inventory_path = folder / "bundle-inventory.json"
    inventory = load(inventory_path)
    failures = []
    payloads = []
    for item in inventory.get("tasks", []):
        for field in ("agent_payload", "grader_payload", "agent_payload_sha256", "grader_payload_sha256"):
            if not item.get(field):
                failures.append(f"{item.get('task_key')}: missing {field}")
        for field in ("agent_payload", "grader_payload"):
            path = Path(item.get(field, ""))
            if not path.is_file():
                failures.append(f"{item.get('task_key')}: missing file {path}")
            elif item.get(field + "_sha256") != sha256(path):
                failures.append(f"{item.get('task_key')}: {field} hash mismatch")
        payloads.append({
            "task_key": item.get("task_key"),
            "benchmark": item.get("benchmark"),
            "task_id": item.get("task_id"),
            "source_revision": item.get("source_revision") or item.get("benchmark_revision"),
            "source_content_sha256": item.get("source_tree_sha256"),
            "agent_payload": item.get("agent_payload"),
            "agent_payload_sha256": item.get("agent_payload_sha256"),
            "grader_payload": item.get("grader_payload"),
            "grader_payload_sha256": item.get("grader_payload_sha256"),
            "grader_sha256": item.get("grader_payload_sha256"),
        })
    canary_ok = bool(canary and canary.get("status") == "passed" and canary.get("full_loop") is True)
    if not canary_ok:
        failures.append("missing full-loop E2B/Boyue canary receipt")
    receipt = {
        "schema_version": "hse-scaling-runtime-receipt-v1",
        "experiment_id": f"hse-n{n}-e2b-20260922",
        "status": "ready" if not failures else "prepared",
        "launchable": not failures,
        "created_at": datetime.now(UTC).isoformat(),
        "controller_sha": git_sha(),
        "config_sha256": sha256(CONFIG),
        "assignment_sha256": sha256(ASSIGNMENTS),
        "mixed_config_sha256": sha256(MIXED),
        "bundle_inventory_sha256": sha256(inventory_path),
        "task_count": len(payloads),
        "payloads": payloads,
        "canary": canary,
        "failures": failures,
        "executor": str(SUITE / "run_scaling_bundle_e2b.py"),
        "upload_policy": "one selected task payload per E2B sandbox; no whole-suite upload",
    }
    out = folder / "receipt.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", default="all", choices=["all", "4", "8", "16", "32"])
    parser.add_argument("--canary-receipt", type=Path)
    args = parser.parse_args()
    canary = load(args.canary_receipt) if args.canary_receipt else None
    ns = (4, 8, 16, 32) if args.n == "all" else (int(args.n),)
    outputs = [str(freeze(n, canary)) for n in ns]
    print(json.dumps({"receipts": outputs, "canary_required": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
