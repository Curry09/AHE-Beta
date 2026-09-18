#!/usr/bin/env python3
"""Grade the captured harness patch in a fresh Daytona SWE-bench sandbox."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Resources
from run_daytona_harnessv0_requests6028 import (
    BASE_COMMIT,
    DATASET,
    IMAGE,
    INSTANCE_ID,
    score_targets,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    rows = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("instance_id") == INSTANCE_ID
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected one dataset row, got {len(rows)}")
    row = rows[0]
    fail_to_pass = json.loads(row["FAIL_TO_PASS"])
    pass_to_pass = json.loads(row["PASS_TO_PASS"])

    daytona_key = os.environ.get("DAYTONA_API_KEY") or getpass("Daytona API key: ")
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    sandbox = None
    score = None
    grader_exit_code = None
    cleanup_error = None
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    try:
        print(f"CREATE_GRADER image={IMAGE}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image=IMAGE,
                resources=Resources(cpu=1, memory=2, disk=10),
                ephemeral=True,
                ttl_minutes=20,
                labels={"purpose": "swebench-grader", "instance": INSTANCE_ID},
            ),
            timeout=900,
        )
        print(f"GRADER_CREATED {sandbox.id}", flush=True)
        sandbox.fs.upload_file(str(run_dir / "model.patch"), "/tmp/model.patch")
        sandbox.fs.upload_file(row["test_patch"].encode(), "/tmp/official-test.patch")
        grader = sandbox.process.exec(
            "cd /testbed && "
            "git apply /tmp/model.patch && "
            f"git checkout {BASE_COMMIT} -- tests/test_utils.py && "
            "git apply /tmp/official-test.patch && "
            "/opt/miniconda3/envs/testbed/bin/pytest -rA tests/test_utils.py",
            timeout=600,
        )
        grader_exit_code = grader.exit_code
        grader_output = grader.result or ""
        (run_dir / "grader-fresh-daytona.log").write_text(
            grader_output, encoding="utf-8"
        )
        score = score_targets(grader_output, fail_to_pass, pass_to_pass)
        if "test session starts" not in grader_output:
            raise RuntimeError(
                f"grader did not start pytest (exit {grader_exit_code}): "
                f"{grader_output[-1000:]}"
            )
        print(
            f"GRADER_SCORE f2p={score['fail_to_pass_success']}/"
            f"{score['fail_to_pass_total']} p2p={score['pass_to_pass_success']}/"
            f"{score['pass_to_pass_total']} unrelated_errors="
            f"{score['unrelated_error_count']}",
            flush=True,
        )
    finally:
        if sandbox is not None:
            try:
                client.delete(sandbox, timeout=120, wait=True)
                print(f"GRADER_DELETED {sandbox.id}", flush=True)
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
                print(f"GRADER_CLEANUP_WARNING {cleanup_error}", flush=True)

    prior_score = manifest.get("grader_score")
    manifest.update(
        {
            "in_place_grader_attempt": {
                "score": prior_score,
                "invalid_reason": (
                    "Harness-side tests populated /tmp/test_utils.py before the test "
                    "file was reset; extract_zipped_paths then compared stale cache data."
                ),
            },
            "grader_exit_code": grader_exit_code,
            "grader_score": score,
            "passed": bool(score and score["resolved"]),
            "grading_semantics": (
                "Fresh Daytona sandbox; SWE-bench psf/requests parser over declared "
                "FAIL_TO_PASS and PASS_TO_PASS nodes"
            ),
            "fresh_grading": {
                "sandbox_id": sandbox.id if sandbox is not None else None,
                "sandbox_deleted": cleanup_error is None,
                "cleanup_error": cleanup_error,
                "image": IMAGE,
                "graded_at": datetime.now(UTC).isoformat(),
                "log": str(run_dir / "grader-fresh-daytona.log"),
            },
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"MANIFEST {manifest_path}", flush=True)
    return 0 if manifest["passed"] and cleanup_error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
