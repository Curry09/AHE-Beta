from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.harness_bench.outcomes import OutcomeKind, TrialResult
from evaluation.harness_bench.report import compare_runs, summarize, summarize_run
from evaluation.harness_bench.schema import PlanError


def result(kind: OutcomeKind, attempt: int = 1) -> TrialResult:
    success = kind is OutcomeKind.TASK_SUCCESS
    return TrialResult(
        trial_id=f"trial-{attempt}-{kind.value}",
        attempt=attempt,
        outcome=kind,
        passed=success,
        terminal_reply=kind
        not in {OutcomeKind.EVALUATOR_DEADLINE, OutcomeKind.INFRASTRUCTURE_FAILURE},
        normal_reply=kind in {OutcomeKind.TASK_SUCCESS, OutcomeKind.TASK_FAILURE},
        grader_reached=kind in {OutcomeKind.TASK_SUCCESS, OutcomeKind.TASK_FAILURE},
        elapsed_seconds=1,
        costs={"harness_agent": 1.5},
    )


def test_summary_keeps_reply_and_pass_denominators_separate() -> None:
    summary = summarize(
        [
            result(OutcomeKind.TASK_SUCCESS),
            result(OutcomeKind.HARNESS_SELF_TIMEOUT),
            result(OutcomeKind.INFRASTRUCTURE_FAILURE),
        ]
    )

    assert summary["valid_trials"] == 2
    assert summary["invalid_attempts"] == 1
    assert summary["task_pass_rate"] == 0.5
    assert summary["terminal_reply_rate"] == 1.0
    assert summary["normal_reply_rate"] == 0.5
    assert summary["costs"]["harness_agent"] == 4.5


def _write_run(root: Path, *, harness: str, model: str = "glm-5.2") -> None:
    trial_id = f"trial-{harness}"
    manifest = {
        "schema_version": 1,
        "suite": "suite",
        "framework_commit": "commit",
        "cases": [{"benchmark": "bench", "task_id": "task", "digest": "digest"}],
        "harness_model": model,
        "interactions": [{"mode": "direct"}],
        "provider": {"type": "local"},
        "measurement": {"repetitions": 1, "scheduling_seed": 7},
        "fallback_agent_timeout_seconds": 1800,
        "resolved_cases": {"bench/task": {"agent_timeout_seconds": 1800}},
        "image_digests": {"agent": "sha256:image"},
        "trials": [
            {
                "trial_id": trial_id,
                "benchmark": "bench",
                "task_id": "task",
                "interaction": "direct",
                "policy": "direct",
                "seed": None,
                "repetition": 0,
                "harness": harness,
            }
        ],
    }
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    attempt = root / "trials" / trial_id / "attempt-1"
    attempt.mkdir(parents=True)
    (attempt / "result.json").write_text(
        json.dumps(result(OutcomeKind.TASK_SUCCESS).to_dict() | {"trial_id": trial_id}),
        encoding="utf-8",
    )
    summarize_run(root)


def test_compare_runs_allows_only_harness_as_treatment(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_run(left, harness="v0")
    _write_run(right, harness="v4")

    comparison = compare_runs(left, right)

    assert comparison["comparable_denominator"] is True
    assert comparison["pass_rate_delta"] == 0


def test_compare_runs_rejects_model_drift(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    _write_run(left, harness="v0")
    _write_run(right, harness="v4", model="another-model")

    with pytest.raises(PlanError, match="not a paired"):
        compare_runs(left, right)
