"""Resumable trial scheduler; benchmark/provider details live behind executor."""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..report import summarize_run
from ..results import (
    GraderFailure,
    InfrastructureFailure,
    OutcomeKind,
    ProtocolInvalid,
    TrialResult,
)
from ..state import RunStateStore

TrialExecutor = Callable[[Mapping[str, Any], int, Path], TrialResult]


class Orchestrator:
    def __init__(
        self,
        manifest: Mapping[str, Any],
        run_root: str | Path,
        executor: TrialExecutor,
        *,
        max_invalid_attempts: int = 1,
    ) -> None:
        self.manifest = dict(manifest)
        self.root = Path(run_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.max_invalid_attempts = max_invalid_attempts
        self.state = RunStateStore(self.root, manifest)

    def run(self) -> dict[str, Any]:
        trials = {str(item["trial_id"]): item for item in self.manifest["trials"]}
        concurrency = int(self.manifest.get("provider", {}).get("concurrency", 1))
        if concurrency <= 0:
            raise ValueError("manifest provider.concurrency must be positive")
        runnable = [
            (trial_id, trial)
            for trial_id, trial in trials.items()
            if self.state.load()["trials"][trial_id]["status"]
            not in {"terminal", "terminal_invalid"}
        ]
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="hbench") as pool:
            futures = [
                pool.submit(self._run_trial, trial_id, trial) for trial_id, trial in runnable
            ]
            try:
                for future in futures:
                    future.result()
            except BaseException:
                detach = getattr(self.executor, "detach", None)
                if detach:
                    detach()
                pool.shutdown(wait=True, cancel_futures=True)
                raise
        return summarize_run(self.root)

    def _run_trial(self, trial_id: str, trial: Mapping[str, Any]) -> None:
        cursor = self.state.load()["trials"][trial_id]
        previous_attempt = int(cursor.get("attempts", 0))
        reconnect = cursor["status"] == "running" and getattr(
            self.executor, "reconnect_running", False
        )
        attempt = previous_attempt if reconnect else previous_attempt + 1
        while attempt <= self.max_invalid_attempts:
            attempt_root = self.root / "trials" / trial_id / f"attempt-{attempt}"
            attempt_root.mkdir(parents=True, exist_ok=True)
            self.state.transition(trial_id, "running", attempts=attempt)
            try:
                result = self.executor(trial, attempt, attempt_root)
            except Exception as exc:  # executor ownership is normalized here
                result = self._failure_result(trial_id, attempt, exc, attempt_root)
            (attempt_root / "result.json").write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if result.valid_trial:
                self.state.transition(
                    trial_id,
                    "terminal",
                    attempts=attempt,
                    outcome=result.outcome.value,
                    result=str(attempt_root / "result.json"),
                )
                return
            self.state.transition(
                trial_id,
                "invalid",
                attempts=attempt,
                outcome=result.outcome.value,
                result=str(attempt_root / "result.json"),
            )
            if not result.retryable_attempt:
                self.state.transition(
                    trial_id,
                    "terminal_invalid",
                    attempts=attempt,
                    outcome=result.outcome.value,
                )
                return
            attempt += 1
        self.state.transition(trial_id, "terminal_invalid", attempts=attempt - 1)

    @staticmethod
    def _failure_result(
        trial_id: str, attempt: int, exc: Exception, attempt_root: Path
    ) -> TrialResult:
        mapping = {
            InfrastructureFailure: OutcomeKind.INFRASTRUCTURE_FAILURE,
            GraderFailure: OutcomeKind.GRADER_FAILURE,
            ProtocolInvalid: OutcomeKind.PROTOCOL_INVALID,
        }
        outcome = next(
            (kind for exception, kind in mapping.items() if isinstance(exc, exception)),
            OutcomeKind.PROTOCOL_INVALID,
        )
        (attempt_root / "exception.log").write_text(traceback.format_exc(), encoding="utf-8")
        return TrialResult(
            trial_id=trial_id,
            attempt=attempt,
            outcome=outcome,
            passed=False,
            terminal_reply=False,
            normal_reply=False,
            grader_reached=False,
            elapsed_seconds=0,
            error=f"{type(exc).__name__}: {exc}",
        )
