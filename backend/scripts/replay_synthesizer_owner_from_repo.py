#!/usr/bin/env python3
"""Restore saved proposal artifacts, then rerun Synthesize and Owner only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

import run as run_mod  # noqa: E402


def _numbers(value: str) -> list[int]:
    result: list[int] = []
    for part in value.split(","):
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            result.extend(range(start, end + 1))
        elif part.strip():
            result.append(int(part))
    return list(dict.fromkeys(result))


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--harness-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--triage-issues", type=_numbers, required=True)
    parser.add_argument("--divergent-issues", type=_numbers, required=True)
    parser.add_argument("--discard-issues", type=_numbers, default=[])
    parser.add_argument("--model", default="z-ai/glm-5.2")
    return parser.parse_args()


def _wis_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (WORKSPACE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    args = _args()
    args.output.mkdir(parents=True, exist_ok=False)
    gitea = {**run_mod._load_env(ROOT / "deploy" / "gitea" / ".env"), "REPO": args.repo}
    wis = _wis_env()
    os.environ.update(
        DEMAND_LLM_MODEL=args.model,
        DEMAND_LLM_BASE_URL=wis["wis_base_url"],
        DEMAND_LLM_API_KEY=wis["wis_api_key"],
        NO_PROXY="localhost,127.0.0.1",
        no_proxy="localhost,127.0.0.1",
    )
    run_mod._isolate_git_credentials()

    from auto_designer.demand.issue_schema import (
        DECLINED,
        FROM_DIVERGENT,
        FROM_TRIAGE,
        OPENAGENTS,
        PROPOSAL,
        READY,
        REPORT,
        plane,
    )
    from auto_designer.demand.owner import Owner
    from auto_designer.demand.synthesizer import Synthesizer
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore

    tracker = GiteaTracker(gitea["GITEA_URL"], gitea["OWNER"], gitea["REPO"], gitea["TOKEN"])
    for number in args.triage_issues:
        issue = tracker.get_issue(number=number)
        labels = [label for label in issue["labels"] if label not in {REPORT, READY, OPENAGENTS}]
        tracker.update_issue(
            number,
            title=issue["title"],
            body=issue["body"],
            labels=list(dict.fromkeys([*labels, PROPOSAL, FROM_TRIAGE])),
        )
    for number in args.divergent_issues:
        issue = tracker.get_issue(number=number)
        labels = [label for label in issue["labels"] if label not in {READY, OPENAGENTS, DECLINED}]
        tracker.transition_issue(
            number,
            state="open",
            labels=list(dict.fromkeys([*labels, PROPOSAL, FROM_DIVERGENT])),
        )
    for number in args.discard_issues:
        issue = tracker.get_issue(number=number)
        labels = [label for label in issue["labels"] if label not in {PROPOSAL, READY, OPENAGENTS}]
        tracker.transition_issue(
            number, state="closed", labels=list(dict.fromkeys([*labels, DECLINED]))
        )
        tracker.add_comment(
            number, "Replay artifact isolated before rerunning Synthesize and Owner."
        )

    before = tracker.list_open_issues()
    if sum(plane(issue.labels) == PROPOSAL for issue in before) != len(
        args.triage_issues + args.divergent_issues
    ):
        raise RuntimeError("proposal restoration count mismatch")

    store = SessionStore(args.sessions)
    events = args.output / "agent-events.jsonl"

    def event(role: str):
        def write(kind: str, text: str) -> None:
            with events.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"role": role, "kind": kind, "text": text}, ensure_ascii=False)
                    + "\n"
                )

        return write

    synthesizer = Synthesizer(
        tracker,
        store,
        str(args.harness_repo),
        str(ROOT / "agent_defs" / "synthesizer"),
        on_event=event("synthesizer"),
        round_provider=lambda: 1,
    )
    owner = Owner(
        tracker,
        store,
        str(args.harness_repo),
        str(ROOT / "agent_defs" / "owner"),
        on_event=event("owner"),
        review=True,
    )
    design = synthesizer.propose_once()
    admission = owner.admit_once()
    result = {
        "model": args.model,
        "restored_proposals": len(args.triage_issues + args.divergent_issues),
        "synthesizer": design.__dict__,
        "owner": admission.__dict__,
        "openagents_started": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
