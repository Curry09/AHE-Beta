#!/usr/bin/env python3
"""Resume an offline role replay from frozen Triage artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import uuid
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-summary", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Explicit demand model override; otherwise use profile/run")
    add_inputs(parser)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sessions = args.output / "sessions"
    shutil.copytree(args.sessions, sessions)
    harness = args.output / "harness_repo"
    shutil.copytree(
        ROOT / "harness_template", harness, ignore=shutil.ignore_patterns(".git", "__pycache__")
    )
    source = json.loads(args.source_summary.read_text(encoding="utf-8"))
    load_secrets(args.secrets_file)
    role_environment("DEMAND", model=args.model)
    args.model = os.environ["DEMAND_LLM_MODEL"]
    os.environ.update(
        AHE_BETA_USAGE_PATH=str(args.output / "usage.jsonl"),
    )

    from ahe_beta.demand.architect import Architect
    from ahe_beta.demand.divergent import Divergent
    from ahe_beta.demand.issue_schema import FROM_TRIAGE, PROPOSAL, plane
    from ahe_beta.demand.owner import Owner
    from ahe_beta.models import IssueDraft
    from ahe_beta.tracker.fake import FakeTracker
    from ahe_beta.usage import bind_usage_context, default_usage_store
    from ahe_beta.user.session_store import SessionStore

    tracker = FakeTracker()
    triage_numbers = set(int(n) for n in source["triage"]["accepted"])
    for item in source["issues"]:
        if int(item["number"]) in triage_numbers:
            tracker.create_issue(
                IssueDraft(
                    title=item["title"],
                    body=item["body"],
                    labels=[PROPOSAL, FROM_TRIAGE, "round-1"],
                )
            )
    store = SessionStore(sessions)
    event_path = args.output / "agent-events.jsonl"
    lock = threading.Lock()

    def event(role: str):
        def write(kind: str, text: str) -> None:
            with lock, event_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"role": role, "kind": kind, "text": text}, ensure_ascii=False)
                    + "\n"
                )

        return write

    common = (tracker, store, str(harness))
    pm = Divergent(
        *common,
        str(ROOT / "agent_defs/divergent_pm"),
        on_event=event("pm"),
        round_provider=lambda: 1,
    )
    architect = Architect(
        *common,
        str(ROOT / "agent_defs/architect"),
        on_event=event("architect"),
        round_provider=lambda: 1,
    )
    owner = Owner(*common, str(ROOT / "agent_defs/owner"), on_event=event("owner"))
    run_id = f"spec-0043-resume-{uuid.uuid4().hex}"

    def invoke(role: str, operation):
        with bind_usage_context(run_id=run_id, role=role, round_no=1):
            return operation()

    pm_out = invoke("pm", pm.propose_once)
    architect_out = invoke("architect", architect.propose_once)
    owner_out = invoke("owner", owner.admit_once)
    issues = []
    for number in range(1, tracker._counter + 1):
        item = tracker.issue(number)
        issues.append({"number": number, **item, "plane": plane(item["labels"])})
    summary = {
        "model": args.model,
        "source_summary": str(args.source_summary),
        "triage_artifacts": source["triage"]["artifacts"],
        "pm": pm_out.__dict__,
        "architect": architect_out.__dict__,
        "owner": owner_out.__dict__,
        "issues": issues,
        "usage": default_usage_store().summary(run_id=run_id),
        "openagents_started": False,
        "tracker": "offline-fake",
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pm": summary["pm"],
                "architect": summary["architect"],
                "owner": summary["owner"],
                "usage": summary["usage"],
                "openagents_started": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
