#!/usr/bin/env python3
"""Replay PM/Synthesizer against fixed evidence, without writing a remote tracker.

Uses the production prompt builders and tool definitions. The only run overrides
are bounded timeout/iterations. Inputs are copied to the output for reproducibility;
native observation files stay read-only at the supplied root.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from auto_designer.demand.agent_runtime import run_agent_def
from auto_designer.demand.divergent import Divergent
from auto_designer.demand.synthesizer import Synthesizer
from auto_designer.models import OpenIssue
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore


class ReplayTracker(FakeTracker):
    def __init__(self, proposals: list[OpenIssue]) -> None:
        super().__init__()
        for item in proposals:
            self._issues[item.number] = {**item.to_dict(), "comments": [], "reason": ""}
        self._counter = max((item.number for item in proposals), default=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=["pm", "synthesizer", "both"], default="both")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--max-iterations", type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    profile: dict[str, str] = {}
    for line in args.profile.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            profile[key.strip()] = value.strip().strip("\"'")
    for key in ("DEMAND_LLM_MODEL", "DEMAND_LLM_BASE_URL", "DEMAND_LLM_API_KEY"):
        os.environ[key] = profile[key]
    os.environ["ROLE_RUNS_DIR"] = str(args.output / "role-runs")
    os.environ["AUTO_DESIGNER_USAGE_PATH"] = str(args.output / "usage.jsonl")
    os.environ["AUTO_DESIGNER_OBSERVATION_ROOT"] = str(args.observations.resolve())
    shutil.copytree(args.sessions, args.output / "sessions")
    shutil.copyfile(args.proposals, args.output / "input-proposals.json")
    store = SessionStore(args.output / "sessions")
    proposals = [OpenIssue.from_dict(row) for row in json.loads(args.proposals.read_text())]
    agents = Path(__file__).resolve().parents[1] / "agent_defs"
    summary = {
        "model": profile["DEMAND_LLM_MODEL"],
        "evidence_mode": "fixed-input replay; not a new user experiment",
        "observations": str(args.observations.resolve()),
        "timeout_per_invocation": args.timeout,
        "max_iterations": args.max_iterations,
        "roles": {},
    }
    roles = ["pm", "synthesizer"] if args.role == "both" else [args.role]
    for role in roles:
        trace_path = args.output / f"{role}-trace.jsonl"

        def event(kind: str, text: str, *, trace_path: Path = trace_path) -> None:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"at": datetime.now(UTC).isoformat(), "kind": kind, "text": text},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        def bounded_run(*pos, **kwargs):
            kwargs.update(timeout=args.timeout, max_iterations=args.max_iterations)
            return run_agent_def(*pos, **kwargs)

        tracker = ReplayTracker(proposals)
        driver = (
            Divergent(tracker, store, str(args.repo), str(agents / "divergent_pm"), on_event=event)
            if role == "pm"
            else Synthesizer(
                tracker, store, str(args.repo), str(agents / "synthesizer"), on_event=event
            )
        )
        module = "divergent" if role == "pm" else "synthesizer"
        started = time.monotonic()
        try:
            with (
                bind_usage_context(run_id=args.output.name, round_no=1),
                patch(f"auto_designer.demand.{module}.run_agent_def", bounded_run),
            ):
                outcome = driver.propose_once()
            row = {
                "status": "returned",
                "outcome": asdict(outcome),
                "open_issues": [item.to_dict() for item in tracker.list_open_issues()],
            }
        except Exception as exc:
            # Preserve collected trace on backend/protocol failure; never call it success.
            row = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary["roles"][role] = row
        (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {"role": role, "status": row["status"], "elapsed_seconds": row["elapsed_seconds"]}
            ),
            flush=True,
        )
    return int(any(row["status"] == "error" for row in summary["roles"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
