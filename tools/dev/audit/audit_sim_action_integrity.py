#!/usr/bin/env python3
"""Audit persisted sim sessions without mutating frozen experiment artifacts.

For every terminal TurnLog, compare the recorded action with the explicit action in its
corresponding ``main_act`` persona trace. A recorded Accept without the same explicit model
action is reported as an invalid fallback, never inferred from prose or verdict.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

BROAD_ACCEPT = {"accept", "accept_with_reservations"}


def _json_files(roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        candidates = root.rglob("*.json") if root.is_dir() else (root,)
        for path in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path


def _sessions(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("sim_trace"), dict):
            yield value
        elif "turns" in value and "end_reason" in value:
            yield {"sim_trace": value}
        else:
            for child in value.values():
                yield from _sessions(child)
    elif isinstance(value, list):
        for child in value:
            yield from _sessions(child)


def _round_label(session: dict[str, Any], path: Path) -> str:
    for key in ("audit_round", "round", "round_no"):
        if key in session:
            return str(session[key])
    text = str(path)
    match = re.search(r"(?:harness[-_]?v|hv|round[-_]?)(\d+)", text, re.IGNORECASE)
    return f"v{match.group(1)}" if match else "unknown"


def _last_main_act(turn: dict[str, Any]) -> dict[str, Any]:
    calls = turn.get("persona_trace") or []
    matches = [
        call
        for call in calls
        if isinstance(call, dict) and str(call.get("role") or "") == "main_act"
    ]
    if not matches:
        return {}
    parsed = matches[-1].get("parsed")
    return parsed if isinstance(parsed, dict) else {}


def audit_paths(roots: Iterable[Path]) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    by_round: dict[str, Counter[str]] = {}
    invalid: list[dict[str, Any]] = []

    for path in _json_files(roots):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            totals["unreadable_files"] += 1
            continue
        for session in _sessions(value):
            trace = session.get("sim_trace") or {}
            turns = trace.get("turns") or []
            terminal = next(
                (
                    turn
                    for turn in reversed(turns)
                    if isinstance(turn, dict) and str(turn.get("action") or "")
                ),
                None,
            )
            if terminal is None:
                continue
            totals["sessions"] += 1
            label = _round_label(session, path)
            bucket = by_round.setdefault(label, Counter())
            bucket["sessions"] += 1
            recorded = str(terminal.get("action") or "")
            explicit = str(_last_main_act(terminal).get("action") or "")
            if recorded in BROAD_ACCEPT:
                totals["raw_broad_accept"] += 1
                bucket["raw_broad_accept"] += 1
                if explicit == recorded:
                    totals["explicit_broad_accept"] += 1
                    bucket["explicit_broad_accept"] += 1
                else:
                    totals["invalid_accept_fallback"] += 1
                    bucket["invalid_accept_fallback"] += 1
                    invalid.append(
                        {
                            "path": str(path),
                            "session_id": str(session.get("session_id") or ""),
                            "round": label,
                            "recorded_action": recorded,
                            "explicit_action": explicit or None,
                        }
                    )

    keys = ("sessions", "raw_broad_accept", "explicit_broad_accept", "invalid_accept_fallback")
    return {
        "schema": "sim-action-integrity/v1",
        "totals": {key: totals[key] for key in keys},
        "by_round": {
            label: {key: counter[key] for key in keys}
            for label, counter in sorted(by_round.items())
        },
        "invalid": invalid,
        "unreadable_files": totals["unreadable_files"],
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="session JSON files or directories")
    parser.add_argument("--output", type=Path, help="write a separate correction artifact")
    parser.add_argument("--source-pin", default="unknown", help="source commit/image identifier")
    parser.add_argument("--model-pin", default="unknown", help="persona model identifier")
    return parser.parse_args()


def main() -> int:
    args = _args()
    report = audit_paths(args.roots)
    report["source_pin"] = args.source_pin
    report["model_pin"] = args.model_pin
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
