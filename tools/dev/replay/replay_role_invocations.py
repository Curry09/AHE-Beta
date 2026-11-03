#!/usr/bin/env python3
# Spec-0049/T5: freeze demand calls for offline replay (only feed input.prompt, diff structured).
"""Replay frozen demand-side role invocations against a replacement agent_def.

Skips implementer / replayable=false records and never starts Gitea or vigil.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.dev import add_inputs, load_secrets, role_environment

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay frozen demand role invocations")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--side", default="demand")
    parser.add_argument("--role", required=True)
    parser.add_argument("--agent-def", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    add_inputs(parser)
    return parser.parse_args(argv)


def load_invocations(*, run_dir: Path, side: str, role: str) -> list[dict]:
    folder = run_dir / side
    if not folder.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_path"] = str(path)
        records.append(data)
    return [item for item in records if item.get("role") == role]


def replay_records(
    *,
    records: list[dict],
    agent_def: Path,
    repo: Path,
    runner,
) -> dict:
    skipped = 0
    diffs: list[dict] = []
    for item in records:
        if item.get("side") == "delivery" or item.get("role") == "implementer":
            skipped += 1
            continue
        if item.get("replayable") is False:
            skipped += 1
            continue
        prompt = (item.get("input") or {}).get("prompt") or ""
        old = (item.get("output") or {}).get("structured")
        text = runner(
            agent_def,
            prompt,
            store_repo=repo,
            role=str(item.get("role") or "owner"),
            subject=item.get("subject") or {"kind": "round", "id": ""},
        )
        try:
            new = json.loads(text) if isinstance(text, str) else text
        except (ValueError, TypeError):
            new = {"raw": text}
        diffs.append(
            {
                "invocation_id": item.get("invocation_id"),
                "path": item.get("_path"),
                "old": old,
                "new": new,
                "changed": old != new,
            }
        )
    return {"skipped": skipped, "replayed": len(diffs), "diffs": diffs}


def _default_runner(agent_def, prompt, *, store_repo, role, subject) -> str:
    from ahe_beta.demand.agent_runtime import run_agent_def
    from ahe_beta.user.session_store import SessionStore

    return run_agent_def(
        agent_def,
        prompt,
        store=SessionStore(store_repo / "sessions"),
        repo=store_repo,
        role=role,
        timeout=120,
        subject=subject,
    )


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    load_secrets(args.secrets_file)
    role_environment("DEMAND")
    repo = args.repo or args.run_dir
    records = load_invocations(run_dir=args.run_dir, side=args.side, role=args.role)
    result = replay_records(
        records=records,
        agent_def=args.agent_def,
        repo=repo,
        runner=_default_runner,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
