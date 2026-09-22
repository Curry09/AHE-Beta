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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prompt_metadata(item: dict, assignment: dict) -> tuple[str | None, str | None]:
    explicit_source = assignment.get("prompt_source")
    explicit_hash = assignment.get("prompt_sha256")
    if explicit_source:
        path = Path(str(explicit_source))
        if path.is_file():
            return str(path), str(explicit_hash or sha256(path))
        return str(explicit_source), str(explicit_hash or "") or None
    if item.get("benchmark") == "mechanism":
        manifest = load(SUITE / "task-manifest.json")
        for task in manifest.get("mechanism_tasks", []):
            if task.get("task_id") == item.get("task_id"):
                opening = str(task.get("opening_message") or "")
                return f"task-manifest.json#{task.get('id')}", sha256_text(opening) if opening else None
    source = Path(str(item.get("source") or ""))
    for candidate in ("instruction.md", "TASK.md", "start.md"):
        path = source / candidate
        if path.is_file():
            return str(path), sha256(path)
    return None, None


def git_sha() -> str:
    result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze(n: int, canary: dict | None) -> Path:
    folder = PREPARED / f"n{n}"
    inventory_path = folder / "bundle-inventory.json"
    inventory = load(inventory_path)
    scaling_config = load(CONFIG)
    assignment_rows = {
        str(item["task_key"]): item
        for item in load(ASSIGNMENTS).get("tasks", [])
    }
    e2b = scaling_config.get("e2b") or {}
    profile_name = (e2b.get("effective_profile_by_n") or {}).get(str(n))
    resource_profile = (e2b.get("resource_profiles") or {}).get(profile_name)
    failures = []
    if not profile_name or not isinstance(resource_profile, dict):
        failures.append(f"N{n}: missing effective E2B resource profile")
    resource_plan_path = folder / "resource-plan.json"
    if not resource_plan_path.is_file():
        failures.append(f"N{n}: missing resource plan {resource_plan_path}")
    elif load(resource_plan_path).get("config_sha256") != sha256(CONFIG):
        failures.append(f"N{n}: resource plan config hash mismatch")
    failures = []
    payloads = []
    for item in inventory.get("tasks", []):
        assignment = assignment_rows.get(str(item.get("task_key")), {})
        prompt_source, prompt_sha = prompt_metadata(item, assignment)
        for field in ("agent_payload", "grader_payload", "agent_payload_sha256", "grader_payload_sha256"):
            if not item.get(field):
                failures.append(f"{item.get('task_key')}: missing {field}")
        for field in ("agent_payload", "grader_payload"):
            path = Path(item.get(field, ""))
            if not path.is_file():
                failures.append(f"{item.get('task_key')}: missing file {path}")
            elif item.get(field + "_sha256") != sha256(path):
                failures.append(f"{item.get('task_key')}: {field} hash mismatch")
        official_timeout = int(assignment.get("official_agent_timeout_seconds", 1800))
        payloads.append({
            "task_key": item.get("task_key"),
            "benchmark": item.get("benchmark"),
            "task_id": item.get("task_id"),
            "stratum": assignment.get("stratum"),
            "interaction": assignment.get("interaction"),
            "persona_id": assignment.get("persona_id"),
            "prompt_source": prompt_source,
            "prompt_sha256": prompt_sha,
            "official_agent_timeout_seconds": official_timeout,
            "outer_timeout_seconds": official_timeout + 600,
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
        "e2b": {
            "template_alias": e2b.get("template_alias"),
            "template_build_id": e2b.get("template_build_id"),
            "profile": profile_name,
            "resources": resource_profile,
        },
        "timeouts": scaling_config.get("timeouts") or {},
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
