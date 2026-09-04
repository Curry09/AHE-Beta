#!/usr/bin/env python3
"""Offline Spec-0043/0055 role-contract and evidence-boundary evaluator.

Input is JSONL (or a directory of invocation JSON files) with ``role``, ``artifact`` and optional context fields
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
from auto_designer.designer.evidence_contract import (
    project_for_role,
    validate_envelope,
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
    result = [{"code": item.code, "detail": item.detail} for item in violations]
    envelope = record.get("envelope")
    if envelope is not None:
        for code in validate_envelope(envelope):
            result.append({"code": f"evidence:{code}", "detail": "invalid 0055 evidence envelope"})
        role = str(role or "")
        projected = project_for_role(envelope, role)
        # A role projection is intentionally smaller than the canonical envelope.
        # These checks catch accidental prompt construction from the unprojected
        # object in replay fixtures.
        if role.lower() in {"owner", "designer", "synthesize"}:
            for key in ("source_report", "user_evidence", "objective_evidence", "harness_source"):
                if key in projected:
                    result.append({
                        "code": f"evidence:visibility:{role}:{key}",
                        "detail": "role projection exposes a forbidden lane",
                    })
    return result


def _records(path: Path) -> list[dict]:
    rows: list[dict] = []
    if path.is_dir():
        paths = sorted(path.glob("*.json"))
        for item in paths:
            try:
                row = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _input_metrics(records: list[dict]) -> dict[str, dict[str, int | float]]:
    metrics: dict[str, dict[str, int | float]] = {}
    for row in records:
        role = str(row.get("role") or "unknown")
        inp = row.get("input") if isinstance(row.get("input"), dict) else {}
        prompt = str(inp.get("prompt") or row.get("prompt") or "")
        bucket = metrics.setdefault(
            role,
            {
                "records": 0,
                "chars": 0,
                "token_estimate": 0,
                "tool_calls": 0,
                "evidence_refs": 0,
                "latency_ms": 0.0,
            },
        )
        bucket["records"] += 1
        bucket["chars"] += len(prompt)
        bucket["token_estimate"] += max(0, (len(prompt) + 3) // 4)
        metrics_row = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        bucket["tool_calls"] += int(metrics_row.get("tool_calls") or row.get("tool_calls") or 0)
        bucket["latency_ms"] += float(metrics_row.get("latency_ms") or 0.0)
        evidence = inp.get("evidence") if isinstance(inp.get("evidence"), dict) else {}
        bucket["evidence_refs"] += len(evidence.get("evidence_refs") or [])
    return metrics


def compare_inputs(baseline: list[dict], layered: list[dict]) -> dict[str, object]:
    """Compare frozen old/new role invocation fixtures without calling an LLM."""
    before = _input_metrics(baseline)
    after = _input_metrics(layered)
    roles = sorted(set(before) | set(after))
    delta: dict[str, dict[str, int | float]] = {}
    for role in roles:
        b = before.get(role, {})
        a = after.get(role, {})
        delta[role] = {
            key: (
                float(a.get(key, 0)) - float(b.get(key, 0))
                if key == "latency_ms"
                else int(a.get(key, 0)) - int(b.get(key, 0))
            )
            for key in (
                "records", "chars", "token_estimate", "tool_calls", "evidence_refs", "latency_ms"
            )
        }
    return {"baseline": before, "layered": after, "delta": delta}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional old-input JSONL; emits per-role input-size deltas for a frozen replay.",
    )
    args = parser.parse_args()
    counts: Counter[str] = Counter()
    rows = []
    records = _records(args.trace)
    for line_no, record in enumerate(records, 1):
        violations = evaluate(record)
        for violation in violations:
            counts[violation["code"]] += 1
        rows.append({"line": line_no, "role": record.get("role"), "violations": violations})
    report: dict[str, object] = {
        "records": len(rows),
        "violations": sum(counts.values()),
        "by_code": dict(counts),
        "input_metrics": _input_metrics(records),
        "results": rows,
    }
    if args.baseline:
        report["comparison"] = compare_inputs(_records(args.baseline), records)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if counts else 0


if __name__ == "__main__":
    raise SystemExit(main())
