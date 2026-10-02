#!/usr/bin/env python3
"""Replay frozen sessions through the four demand-side roles without Gitea/OpenAgents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Explicit demand model override; otherwise use profile/run")
    add_inputs(parser)
    return parser.parse_args()


def _hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "agent_defs").glob("*/systemprompt.md"))
    }


def main() -> int:
    args = _args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sessions = output / "sessions"
    shutil.copytree(args.sessions.resolve(), sessions)
    harness = output / "harness_repo"
    shutil.copytree(
        ROOT / "harness_template", harness, ignore=shutil.ignore_patterns(".git", "__pycache__")
    )

    load_secrets(args.secrets_file)
    role_environment("DEMAND", model=args.model)
    args.model = os.environ["DEMAND_LLM_MODEL"]
    os.environ.update(
        AUTO_DESIGNER_USAGE_PATH=str(output / "usage.jsonl"),
    )

    from auto_designer.demand.divergent import Divergent
    from auto_designer.demand.issue_schema import REPORT, plane
    from auto_designer.demand.owner import Owner
    from auto_designer.demand.synthesizer import Synthesizer
    from auto_designer.demand.triage import Triager
    from auto_designer.models import IssueDraft
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.usage import bind_usage_context, default_usage_store
    from auto_designer.user.session_store import SessionStore

    tracker = FakeTracker()
    index_path = sessions / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    mapping: dict[int, int] = {}
    for entry in index:
        for old in entry.get("issue_numbers", []):
            old = int(old)
            if old in mapping:
                continue
            reason = str(entry.get("reason", "")).strip()
            ref = tracker.create_issue(
                IssueDraft(
                    title=f"用户体验报告：{reason[:80] or '会话体验未达预期'}",
                    body=(
                        f"session_id: {entry['session_id']}\n\n"
                        f"体验评分：{entry.get('score')}\n\n用户说明：{reason}"
                    ),
                    labels=[REPORT, "round-1"],
                )
            )
            mapping[old] = ref.number
    for entry in index:
        entry["issue_numbers"] = [
            mapping[int(n)] for n in entry.get("issue_numbers", []) if int(n) in mapping
        ]
        path = sessions / f"{entry['session_id']}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["issue_refs"] = [
            {
                "number": mapping[int(ref["number"])],
                "url": f"fake://issues/{mapping[int(ref['number'])]}",
                "state": "open",
            }
            for ref in doc.get("issue_refs", [])
            if int(ref["number"]) in mapping
        ]
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    store = SessionStore(sessions)
    event_path = output / "agent-events.jsonl"
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
    triager = Triager(*common, str(ROOT / "agent_defs/triage_agent"), on_event=event("triager"))
    pm = Divergent(
        *common,
        str(ROOT / "agent_defs/divergent_pm"),
        on_event=event("pm"),
        round_provider=lambda: 1,
    )
    synth = Synthesizer(
        *common,
        str(ROOT / "agent_defs/synthesizer"),
        on_event=event("synthesizer"),
        round_provider=lambda: 1,
    )
    owner = Owner(*common, str(ROOT / "agent_defs/owner"), on_event=event("owner"))
    run_id = f"spec-0043-offline-{uuid.uuid4().hex}"

    def invoke(role: str, operation):
        with bind_usage_context(run_id=run_id, role=role, round_no=1):
            return operation()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(invoke, "triager", triager.triage_once)
        b = pool.submit(invoke, "pm", pm.propose_once)
        triage_out, pm_out = a.result(), b.result()
    synth_out = invoke("synthesizer", synth.propose_once)
    owner_out = invoke("owner", owner.admit_once)
    issues = []
    for number in range(1, tracker._counter + 1):  # frozen diagnostic snapshot
        item = tracker.issue(number)
        issues.append({"number": number, **item, "plane": plane(item["labels"])})
    summary = {
        "model": args.model,
        "run_id": run_id,
        "source_sessions": len(index),
        "derived_report_mapping": mapping,
        "prompt_sha256": _hashes(),
        "triage": triage_out.__dict__,
        "pm": pm_out.__dict__,
        "synthesizer": synth_out.__dict__,
        "owner": owner_out.__dict__,
        "usage": default_usage_store().summary(run_id=run_id),
        "issues": issues,
        "openagents_started": False,
        "tracker": "offline-fake",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "model",
                    "source_sessions",
                    "triage",
                    "pm",
                    "synthesizer",
                    "owner",
                    "usage",
                    "openagents_started",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
