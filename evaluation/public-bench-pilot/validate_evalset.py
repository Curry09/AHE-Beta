#!/usr/bin/env python3
"""Offline integrity and agent/controller-boundary checks for the pilot set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREPARED = HERE / "prepared"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main() -> int:
    manifest = json.loads((PREPARED / "prepared-manifest.json").read_text())
    expected_counts = {
        "SWE-bench Verified": 6,
        "Terminal-Bench 4.0": 5,
        "TUA-Bench": 4,
        "tau3-bench Core/Text": 4,
    }
    assert manifest["total_tasks"] == 19
    assert manifest["counts"] == expected_counts

    checked = 0
    for line in (PREPARED / "checksums.sha256").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = PREPARED / relative
        assert path.is_file(), f"missing checksummed file: {relative}"
        assert sha256_file(path) == expected, f"checksum mismatch: {relative}"
        checked += 1

    agent_files = {
        "swe": PREPARED / "agent-inputs/swe-bench-verified.jsonl",
        "terminal": PREPARED / "agent-inputs/terminal-bench-4.0.jsonl",
        "tua": PREPARED / "agent-inputs/tua-bench.jsonl",
        "tau3": PREPARED / "agent-inputs/tau3-routing.jsonl",
    }
    rows = {name: load_jsonl(path) for name, path in agent_files.items()}
    assert {name: len(items) for name, items in rows.items()} == {
        "swe": 6,
        "terminal": 5,
        "tua": 4,
        "tau3": 4,
    }
    forbidden_keys = {
        "patch",
        "test_patch",
        "solution",
        "tests",
        "evaluation_criteria",
        "reference_answer",
        "oracle",
    }
    for group in rows.values():
        for row in group:
            overlap = forbidden_keys & row.keys()
            assert not overlap, f"private keys leaked into agent input: {sorted(overlap)}"

    run_matrix = load_jsonl(PREPARED / "run-matrix.jsonl")
    assert len(run_matrix) == 19
    assert len({row["case_id"] for row in run_matrix}) == 19
    assert all(row["smoke_runs"] == 1 for row in run_matrix)
    assert all(row["grader_isolation"] for row in run_matrix)

    controller = PREPARED / "controller-private"
    assert len(load_jsonl(controller / "swe-bench-verified-full.jsonl")) == 6
    tau_rows = load_jsonl(controller / "tau3-selected-tasks.jsonl")
    assert [(row["domain"], str(row["task"]["id"])) for row in tau_rows] == [
        ("airline", "7"),
        ("retail", "76"),
        ("telecom", "[service_issue]overdue_bill_suspension[PERSONA:Easy]"),
        ("banking_knowledge", "task_001"),
    ]

    source_roots = {
        "terminal": controller / "task-sources/terminal-bench-4.0/tasks",
        "tua": controller / "task-sources/tua-bench/tasks",
    }
    expected_dirs = {
        "terminal": {
            "html-js-filter",
            "music-harmony",
            "production-planning",
            "payments-pipeline-fix",
            "lake-temp-glm",
        },
        "tua": {
            "000-count-nuclei",
            "010-pivot-product-revenue",
            "080-convert-novel-epub",
            "106-create-charles-ssh-user",
        },
    }
    for name, root in source_roots.items():
        actual = {path.name for path in root.iterdir() if path.is_dir()}
        assert actual == expected_dirs[name], f"{name} task directories differ"
        for task_id in actual:
            task = root / task_id
            for required in ("instruction.md", "task.toml", "environment", "tests"):
                assert (task / required).exists(), f"{name}/{task_id} missing {required}"

    print(
        json.dumps(
            {
                "valid": True,
                "total_tasks": 19,
                "checksummed_files": checked,
                "agent_input_rows": sum(len(items) for items in rows.values()),
                "run_matrix_rows": len(run_matrix),
                "controller_boundary": "verified",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
