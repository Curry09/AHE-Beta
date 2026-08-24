#!/usr/bin/env python3
"""Offline Spec-0043 role-contract evaluator.

Input is JSONL with ``role``, ``artifact`` and optional context fields
(``report_number``, ``known_sessions``, ``visible_proposals``, ``review_batch``).
It performs structural, task-independent checks only; semantic judging remains
an explicit LLM-eval layer and is never approximated with vocabulary bans.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from auto_designer.designer.role_contract import (
    validate_owner,
    validate_pm,
    validate_synthesis,
    validate_triage,
)


def evaluate(record: dict) -> list[dict[str, str]]:
    role = record.get("role")
    artifact = record.get("artifact") if isinstance(record.get("artifact"), dict) else {}
    if role == "triager":
        violations = validate_triage(artifact, report_number=int(record["report_number"]))
    elif role in ("pm", "divergent"):
        violations = validate_pm(artifact, known_sessions=set(record.get("known_sessions", [])))
    elif role in ("synthesize", "designer"):
        violations = validate_synthesis(
            artifact, visible_proposals=set(record.get("visible_proposals", []))
        )
    elif role == "owner":
        violations = validate_owner(artifact, review_batch=set(record.get("review_batch", [])))
    else:
        return [{"code": "unknown-role", "detail": str(role)}]
    return [{"code": item.code, "detail": item.detail} for item in violations]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    counts: Counter[str] = Counter()
    rows = []
    with args.trace.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            violations = evaluate(record)
            for violation in violations:
                counts[violation["code"]] += 1
            rows.append({"line": line_no, "role": record.get("role"), "violations": violations})
    print(json.dumps({"records": len(rows), "violations": sum(counts.values()),
                      "by_code": dict(counts), "results": rows}, ensure_ascii=False, indent=2))
    return 1 if counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
