#!/usr/bin/env python3
"""Export a redacted experiment monitor snapshot for the static frontend.

Only status, role counts and coarse agent activity are published. Raw logs,
prompts, credentials, container names and repository tokens stay local.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def export(source: Path, output: Path, title: str | None) -> None:
    latest = read_json(source / "telemetry/monitor-latest.json")
    run_id = source.name
    out = output / run_id
    api = out / "api"
    api.mkdir(parents=True, exist_ok=True)

    agents = []
    for row in latest.get("agents", []):
        agents.append(
            {
                "agent_id": row.get("agent_id", "unknown"),
                "role": row.get("role", "user"),
                "label": row.get("agent_id", "unknown"),
                "running": bool(row.get("running", False)),
                "status": row.get("status", ""),
                "round": row.get("round"),
                "meta": None,
                "turns": [],
                "detail": None,
                "log": [],
                "started_at": row.get("updated_at", ""),
                "updated_at": row.get("updated_at", ""),
            }
        )

    state = {
        "running": latest.get("state") == "RUNNING",
        "round": latest.get("round", 0),
        "total_rounds": latest.get("total_rounds", 0),
        "round_shas": [],
        "started_at": None,
        "updated_at": latest.get("time"),
    }
    issue_counts = latest.get("issues") or {}
    api_files = {
        "agents.json": {"agents": agents},
        "state.json": state,
        "history.json": {"items": []},
        "issues.json": {"connected": False, "board_url": None, "issues": []},
        "commits.json": {"connected": False, "commits_url": None, "commits": []},
        "config.json": {
            "roster": {"user": len(agents), "triager": 0, "designer": 0, "developer": 0}
        },
        "overview.json": {
            "open_issue_count": issue_counts.get("open", 0),
            "session_count": latest.get("sessions_saved", 0),
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
        "title": title or run_id,
        "status": latest.get("state", "UNKNOWN"),
        "updated_at": latest.get("time"),
        "round": latest.get("round"),
        "total_rounds": latest.get("total_rounds"),
        "worker_alive": latest.get("worker_alive"),
        "sessions_saved": latest.get("sessions_saved", 0),
        "active_roles": latest.get("active_roles", {}),
        "alerts": latest.get("alerts", []),
    }
    (out / "latest.json").write_text(json.dumps(latest_public, ensure_ascii=False, indent=2) + "\n")
    # A compact timeline is safe to publish and sufficient for static replay.
    timeline = []
    history_path = source / "telemetry/monitor.jsonl"
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timeline.append(
                {
                    key: row.get(key)
                    for key in (
                        "time",
                        "state",
                        "round",
                        "total_rounds",
                        "worker_alive",
                        "sessions_saved",
                        "active_roles",
                        "alerts",
                    )
                }
            )
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title")
    args = parser.parse_args()
    export(args.source, args.output, args.title)
    now = datetime.now(UTC).isoformat()
    index_path = args.output / "index.json"
    existing = read_json(index_path) if index_path.exists() else {"experiments": []}
    entry = {
        "id": args.source.name,
        "title": args.title or args.source.name,
        "status": read_json(args.source / "telemetry/monitor-latest.json").get("state", "UNKNOWN"),
        "updated_at": read_json(args.source / "telemetry/monitor-latest.json").get("time", now),
        "source": "static",
    }
    existing["experiments"] = [e for e in existing["experiments"] if e.get("id") != entry["id"]]
    existing["experiments"].append(entry)
    existing["experiments"].sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    args.output.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
