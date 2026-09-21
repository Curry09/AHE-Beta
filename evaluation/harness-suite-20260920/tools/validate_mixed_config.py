#!/usr/bin/env python3
"""Validate the mixed scaling preparation config without launching a run.

The preparation config intentionally remains non-launchable until task, grader,
and image freeze receipts are supplied.  ``--check-launch`` turns pending
freeze fields and source-manifest drift into a non-zero result for CI/runner
gates; the default mode is a read-only preparation audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_SIZES = {"N1": 1, "N4": 4, "N8": 8, "N16": 16, "N32": 32}


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(config_path: Path, check_launch: bool) -> int:
    config = _read_json(config_path)
    assignment_path = config_path.parent / config["tasks_file"]
    assignments = _read_json(assignment_path)
    tasks = assignments["tasks"]
    errors: list[str] = []
    warnings: list[str] = []

    task_by_key = {task["task_key"]: task for task in tasks}
    if len(tasks) != 32:
        errors.append(f"expected 32 task assignments, found {len(tasks)}")
    if len(task_by_key) != len(tasks):
        errors.append("task_key values are not unique")

    ordinary = [task for task in tasks if task["stratum"] == "ordinary"]
    mechanism = [task for task in tasks if task["stratum"] == "mechanism"]
    if len(ordinary) != 24:
        errors.append(f"expected 24 ordinary tasks, found {len(ordinary)}")
    if len(mechanism) != 8:
        errors.append(f"expected 8 mechanism tasks, found {len(mechanism)}")

    for task in tasks:
        mode = task["interaction"]
        persona = task["persona_id"]
        if mode == "direct" and persona is not None:
            errors.append(f"{task['task_key']}: direct task must not have persona_id")
        if mode == "simulated_user" and not persona:
            errors.append(f"{task['task_key']}: simulated task is missing persona_id")
        if mode not in {"direct", "simulated_user"}:
            errors.append(f"{task['task_key']}: unsupported interaction {mode!r}")

    persona_path = config_path.parent / "../../../backend/persona_library.json"
    persona_ids = {entry["id"] for entry in _read_json(persona_path)}
    missing_personas = sorted(
        {task["persona_id"] for task in tasks if task["persona_id"]} - persona_ids
    )
    if missing_personas:
        errors.append(f"persona IDs not found in library: {', '.join(missing_personas)}")
    actual_persona_hash = _sha256(persona_path)
    expected_persona_hash = assignments["source"]["persona_library_sha256"]
    if actual_persona_hash != expected_persona_hash:
        errors.append("persona library SHA-256 differs from the assignment freeze reference")

    scaling = config["scaling_sets"]
    for name, expected_size in EXPECTED_SIZES.items():
        values = scaling.get(name)
        if values is None:
            errors.append(f"missing scaling set {name}")
            continue
        if len(values) != expected_size:
            errors.append(f"{name}: expected {expected_size} tasks, found {len(values)}")
        if len(set(values)) != len(values):
            errors.append(f"{name}: duplicate task keys")
        unknown = sorted(set(values) - set(task_by_key))
        if unknown:
            errors.append(f"{name}: unknown task keys: {', '.join(unknown)}")
        expected_from_first_n = {
            task["task_key"] for task in tasks if task["first_n"] <= expected_size
        }
        if set(values) != expected_from_first_n:
            errors.append(f"{name}: membership does not match first_n assignments")

    for left, right in zip(("N1", "N4", "N8", "N16"), ("N4", "N8", "N16", "N32")):
        if not set(scaling.get(left, [])).issubset(set(scaling.get(right, []))):
            errors.append(f"scaling sets are not nested: {left} is not a subset of {right}")

    manifest_path = config_path.parent / "../mechanism-seeds/manifest.json"
    manifest = _read_json(manifest_path)
    manifest_ids = {entry["id"] for section in ("historical", "new") for entry in manifest[section]}
    assigned_mechanisms = {task["task_key"] for task in mechanism}
    if not assigned_mechanisms.issubset(manifest_ids):
        errors.append("one or more mechanism assignments are absent from mechanism-seeds/manifest.json")
    for manifest_set, expected_set in (("mechanism_4", {"M03", "M01"}), ("mechanism_8", assigned_mechanisms)):
        observed = set(manifest["scaling_sets"].get(manifest_set, []))
        if manifest_set == "mechanism_4":
            # The plan has only M03 at N=4; M01 is added at N=8.  This is a
            # source-manifest drift warning, not an inferred correction.
            expected_set = {task["task_key"] for task in mechanism if task["first_n"] <= 4}
        if observed != expected_set:
            warnings.append(
                f"{manifest_set} in mechanism manifest is {sorted(observed)}, "
                f"while the plan assignments require {sorted(expected_set)}"
            )

    pending = [
        "task_revision",
        "grader_revision",
        "image_digest",
    ]
    previously_frozen = {"O03", "O09", "O14"}
    pending_tasks = sorted(set(task_by_key) - previously_frozen)
    pending.extend(pending_tasks)
    warnings.append(
        f"{len(pending_tasks)} of 32 task records plus {len(pending) - len(pending_tasks)} "
        "global freeze item(s) remain pending; this file is not launch authorization"
    )
    if check_launch and pending:
        errors.append("launch check failed: freeze items remain pending")

    print(f"config: {config_path}")
    print(f"assignments: {len(tasks)} ({len(ordinary)} ordinary, {len(mechanism)} mechanism)")
    print(f"persona sha256: {actual_persona_hash}")
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("PASS: preparation structure is internally consistent")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="evaluation/harness-suite-20260920/configs/mixed-scaling-20260922.json",
        help="path to the mixed scaling config",
    )
    parser.add_argument(
        "--check-launch",
        action="store_true",
        help="also fail when any freeze item is pending",
    )
    args = parser.parse_args()
    return _check(Path(args.config).resolve(), args.check_launch)


if __name__ == "__main__":
    sys.exit(main())
