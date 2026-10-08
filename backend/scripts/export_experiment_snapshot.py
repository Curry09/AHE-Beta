#!/usr/bin/env python3
"""Export coarse monitor data using an allowlist, never raw telemetry text.

Public IDs and titles are operator-provided publication metadata. By default the
source directory name is hashed and agent identifiers are replaced with ordinals.
Use a fresh output directory: this tool does not clean previously published files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROLES = ("user", "triager", "synthesizer", "divergent", "owner", "developer", "harness")
STATES = {
    "CREATED",
    "PROVISIONED",
    "READY",
    "RUNNING",
    "STOPPING",
    "STOPPED",
    "PAUSED",
    "FAILED",
    "COMPLETED",
    "FINISHED",
    "ARCHIVED",
    "DESTROYED",
    "UNKNOWN",
}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("monitor/index must be a JSON object")
    return value


def count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def timestamp(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def coarse_status(row: dict) -> dict:
    """Treat every source field, including nested counts, as untrusted text."""
    state = row.get("state")
    roles = row.get("active_roles")
    alerts = row.get("alerts")
    alert_count = len(alerts) if isinstance(alerts, list) else 0
    return {
        "time": timestamp(row.get("time")),
        "state": state if isinstance(state, str) and state in STATES else "UNKNOWN",
        "round": count(row.get("round")),
        "total_rounds": count(row.get("total_rounds")),
        "worker_alive": row.get("worker_alive") is True,
        "sessions_saved": count(row.get("sessions_saved")),
        "active_roles": {role: count(roles.get(role)) for role in ROLES}
        if isinstance(roles, dict)
        else {},
        "alerts": [f"{alert_count} alert(s); details withheld"] if alert_count else [],
    }


def export(source: Path, output: Path, title: str | None, *, public_id: str | None = None) -> dict:
    latest = read_json(source / "telemetry/monitor-latest.json")
    run_id = public_id or "run-" + hashlib.sha256(source.name.encode()).hexdigest()[:16]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run_id):
        raise ValueError("public_id must be a 1–80 character slug")
    out = output / run_id
    api = out / "api"
    api.mkdir(parents=True, exist_ok=True)
    summary = coarse_status(latest)
    agents = []
    rows = latest.get("agents")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        role = row.get("role")
        role = role if isinstance(role, str) and role in ROLES else "user"
        agent_id = f"agent-{len(agents) + 1}"
        running = row.get("running") is True
        agents.append(
            {
                "agent_id": agent_id,
                "role": role,
                "label": agent_id,
                "running": running,
                "status": "running" if running else "idle",
                "round": count(row.get("round")),
                "meta": None,
                "turns": [],
                "detail": None,
                "log": [],
                "started_at": "",
                "updated_at": timestamp(row.get("updated_at")),
            }
        )
    issues = latest.get("issues")
    api_files = {
        "agents.json": {"agents": agents},
        "state.json": {
            "running": summary["state"] == "RUNNING",
            "round": summary["round"],
            "total_rounds": summary["total_rounds"],
            "round_shas": [],
            "started_at": None,
            "updated_at": summary["time"],
        },
        "history.json": {"items": []},
        "issues.json": {"connected": False, "board_url": None, "issues": []},
        "commits.json": {"connected": False, "commits_url": None, "commits": []},
        "config.json": {
            "roster": {role: sum(agent["role"] == role for agent in agents) for role in ROLES}
        },
        "overview.json": {
            "open_issue_count": count(issues.get("open")) if isinstance(issues, dict) else 0,
            "session_count": summary["sessions_saved"],
            "feeling_trend": [],
            "issue_curve": [],
            "funnel": {"report": 0, "proposal": 0, "ready": 0},
        },
        "delivery.json": {"connected": False, "pulls": [], "needs_human": 0},
    }
    for filename, payload in api_files.items():
        (api / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    latest_public = {
        "id": run_id,
        "title": title if title is not None else run_id,
        "status": summary.pop("state"),
        "updated_at": summary.pop("time"),
        **summary,
    }
    (out / "latest.json").write_text(json.dumps(latest_public, ensure_ascii=False, indent=2) + "\n")
    timeline = []
    history_path = source / "telemetry/monitor.jsonl"
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                timeline.append(coarse_status(row))
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n")
    return {key: latest_public[key] for key in ("id", "title", "status", "updated_at")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", help="Public title; reviewed by the operator")
    parser.add_argument(
        "--public-id", help="Public URL slug; defaults to a hash of the source name"
    )
    args = parser.parse_args()
    entry = export(args.source, args.output, args.title, public_id=args.public_id)
    entry["source"] = "static"
    index_path = args.output / "index.json"
    existing = read_json(index_path) if index_path.exists() else {"experiments": []}
    existing["experiments"] = [e for e in existing["experiments"] if e.get("id") != entry["id"]]
    existing["experiments"].append(entry)
    existing["experiments"].sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    index_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
