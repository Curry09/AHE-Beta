#!/usr/bin/env python3
"""Replay the historical backlog subset with original issue numbers, then rerun Owner.

Only source issues numbered <= 14 are considered, excluding merged/declined issues.
Copied issue numbers must match the source exactly; a gap stops this historical
number-preserving replay. This is not a general backlog-copy or issue-remap tool.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import requests
from tools.dev import add_inputs, role_environment, run_inputs

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))

from auto_designer.experiment.controllers import ordinary as run_mod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--harness-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Explicit demand model override; otherwise use profile/run")
    add_inputs(parser, run=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    _, _, gitea = run_inputs(args.run_dir, args.secrets_file)
    role_environment("DEMAND", model=args.model)
    args.model = os.environ["DEMAND_LLM_MODEL"]
    base = gitea["GITEA_URL"].rstrip("/")
    headers = {"Authorization": f"token {gitea['TOKEN']}", "Content-Type": "application/json"}
    check = requests.get(
        f"{base}/api/v1/repos/{gitea['OWNER']}/{args.target_repo}", headers=headers, timeout=30
    )
    if check.status_code != 404:
        raise SystemExit(f"target must not exist: HTTP {check.status_code}")
    made = requests.post(
        f"{base}/api/v1/user/repos",
        headers=headers,
        json={"name": args.target_repo, "private": False, "auto_init": False},
        timeout=30,
    )
    made.raise_for_status()

    run_mod._isolate_git_credentials()

    from auto_designer.demand.issue_schema import (  # noqa: PLC0415
        DECLINED,
        MERGED,
        OPENAGENTS,
        PROPOSAL,
        READY,
        plane,
    )
    from auto_designer.demand.owner import Owner  # noqa: PLC0415
    from auto_designer.models import IssueDraft  # noqa: PLC0415
    from auto_designer.tracker.gitea import GiteaTracker  # noqa: PLC0415
    from auto_designer.user.session_store import SessionStore  # noqa: PLC0415

    def tracker(repo: str) -> GiteaTracker:
        return GiteaTracker(base_url=base, owner=gitea["OWNER"], repo=repo, token=gitea["TOKEN"])

    source = tracker(args.source_repo)
    target = tracker(args.target_repo)
    copied: list[int] = []
    for item in sorted(source.list_issues(state="all", limit=100), key=lambda row: row["number"]):
        if item["number"] > 14 or MERGED in item["labels"] or DECLINED in item["labels"]:
            continue
        labels = [x for x in item["labels"] if x not in {READY, OPENAGENTS}]
        labels = list(dict.fromkeys([*labels, PROPOSAL]))
        ref = target.create_issue(IssueDraft(title=item["title"], body=item["body"], labels=labels))
        if ref.number != item["number"]:
            raise RuntimeError(f"issue number drift: {item['number']} -> {ref.number}")
        copied.append(ref.number)

    sessions = args.output / "sessions"
    shutil.copytree(args.sessions.resolve(), sessions)
    events = args.output / "owner-events.jsonl"

    def event(kind: str, text: str) -> None:
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": kind, "text": text}, ensure_ascii=False) + "\n")

    outcome = Owner(
        target,
        SessionStore(sessions),
        str(args.harness_repo.resolve()),
        str(ROOT / "agent_defs" / "owner"),
        on_event=event,
    ).admit_once()
    issues = target.list_issues(state="all", limit=100)
    summary = {
        "model": args.model,
        "source_repo": args.source_repo,
        "target_repo": args.target_repo,
        "copied": copied,
        "owner": outcome.__dict__,
        "issues": [
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "labels": i["labels"],
                "plane": plane(i["labels"]),
            }
            for i in issues
        ],
        "openagents_started": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
