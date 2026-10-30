from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock

from evaluation.harbor.scheduler import Orchestrator
from evaluation.results import InfrastructureFailure, OutcomeKind, TrialResult


def manifest() -> dict:
    return {
        "manifest_digest": "digest",
        "trials": [{"trial_id": "trial-1"}],
    }


def test_orchestrator_retries_only_invalid_attempt(tmp_path: Path) -> None:
    calls = []

    def executor(trial, attempt, attempt_root):
        calls.append(attempt)
        if attempt == 1:
            raise InfrastructureFailure("provider disconnected")
        return TrialResult(
            trial_id=trial["trial_id"],
            attempt=attempt,
            outcome=OutcomeKind.TASK_SUCCESS,
            passed=True,
            terminal_reply=True,
            normal_reply=True,
            grader_reached=True,
            elapsed_seconds=3,
        )

    summary = Orchestrator(manifest(), tmp_path, executor, max_invalid_attempts=2).run()

    assert calls == [1, 2]
    assert summary["valid_trials"] == 1
    assert summary["invalid_attempts"] == 1
    Orchestrator(manifest(), tmp_path, executor, max_invalid_attempts=2).run()
    assert calls == [1, 2]


def test_unknown_executor_bug_is_protocol_invalid_not_infrastructure_retry(
    tmp_path: Path,
) -> None:
    calls = []

    def executor(trial, attempt, attempt_root):
        calls.append(attempt)
        raise ValueError("executor contract bug")

    summary = Orchestrator(manifest(), tmp_path, executor, max_invalid_attempts=2).run()

    assert calls == [1]
    assert summary["outcomes"]["protocol_invalid"] == 1
    assert summary["outcomes"]["infrastructure_failure"] == 0


def test_orchestrator_runs_distinct_trials_up_to_provider_concurrency(tmp_path: Path) -> None:
    run_manifest = {
        "manifest_digest": "digest",
        "provider": {"concurrency": 2},
        "trials": [{"trial_id": "trial-1"}, {"trial_id": "trial-2"}],
    }
    barrier = Barrier(2, timeout=2)
    lock = Lock()
    active = 0
    peak = 0

    def executor(trial, attempt, attempt_root):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        barrier.wait()
        with lock:
            active -= 1
        return TrialResult(
            trial_id=trial["trial_id"],
            attempt=attempt,
            outcome=OutcomeKind.TASK_SUCCESS,
            passed=True,
            terminal_reply=True,
            normal_reply=True,
            grader_reached=True,
            elapsed_seconds=1,
        )

    summary = Orchestrator(run_manifest, tmp_path, executor).run()

    assert peak == 2
    assert summary["valid_trials"] == 2
