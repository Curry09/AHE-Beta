#!/usr/bin/env python3
"""Validate immutable trial results and emit one deterministic batch result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def validate(value: dict[str, Any], schema_path: Path, source: Path) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - environment preflight
        raise SystemExit("jsonschema is required to validate evaluation artifacts") from exc
    schema = read_json(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"invalid {source}: {details}")


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def aggregate(trials: list[dict[str, Any]]) -> dict[str, Any]:
    terminal = [trial for trial in trials if trial.get("outcome", {}).get("terminal_status")]
    valid = [
        trial for trial in terminal
        if trial["outcome"].get("category") not in {"infrastructure", "protocol"}
    ]
    passed = [trial for trial in valid if trial["outcome"].get("passed") is True]
    completed = [
        trial for trial in valid
        if trial["outcome"].get("category") not in {"harness", "user_simulator", "deadline"}
    ]
    scores = [trial["outcome"]["score"] for trial in valid if isinstance(trial["outcome"].get("score"), (int, float))]

    def group(key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trial in trials:
            groups[str(trial.get(key, trial.get("task", {}).get(key, "unknown")))].append(trial)
        result: dict[str, Any] = {}
        for name, items in sorted(groups.items()):
            valid_items = [item for item in items if item in valid]
            result[name] = {
                "total_trials": len(items),
                "valid_trials": len(valid_items),
                "task_pass_rate": rate(sum(item["outcome"].get("passed") is True for item in valid_items), len(valid_items)),
                "harness_completion_rate": rate(sum(item in completed for item in valid_items), len(valid_items)),
            }
        return result

    return {
        "total_trials": len(trials),
        "terminal_trials": len(terminal),
        "valid_trials": len(valid),
        "task_pass_rate": rate(len(passed), len(valid)),
        "harness_completion_rate": rate(len(completed), len(valid)),
        "user_acceptance_rate": rate(
            sum(trial.get("interaction", {}).get("user_acceptance") is True for trial in valid),
            sum("user_acceptance" in trial.get("interaction", {}) for trial in valid),
        ),
        "mean_score": round(sum(scores) / len(scores), 6) if scores else None,
        "by_benchmark": group("benchmark"),
        "by_condition": group("condition"),
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    trials_dir = args.batch_dir / "trials"
    paths = sorted(trials_dir.glob("*/result.json"))
    trials: list[dict[str, Any]] = []
    for path in paths:
        trial = read_json(path)
        validate(trial, SCHEMA_DIR / "trial-result.schema.json", path)
        trials.append(trial)
    if not trials:
        raise SystemExit(f"no immutable trial results found under {trials_dir}")

    batch = {
        "schema_version": "hse-batch-result-v1",
        "experiment_id": read_json(args.config)["experiment_id"],
        "batch_id": args.batch_id,
        "config_sha256": sha256(args.config),
        "manifest_sha256": sha256(args.manifest),
        "profile": args.profile,
        "conditions": sorted({trial["condition"] for trial in trials}),
        "trials": [trial["trial_id"] for trial in trials],
        "metrics": aggregate(trials),
    }
    validate(batch, SCHEMA_DIR / "batch-result.schema.json", args.batch_dir / "batch-result.json")
    atomic_write(args.batch_dir / "batch-result.json", batch)
    print(json.dumps(batch, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
