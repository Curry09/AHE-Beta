"""Reconnectable Harbor executor, with one Agent launch per frozen trial."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from evaluation.harbor.contracts import runtime_identity, runtime_source_files
from evaluation.harbor.job import job_config

from ..results import OutcomeKind, TrialResult
from .grading import grade_issues
from .tasks import verify_case


class EvaluationDetached(BaseException):
    """The controller detached; the existing Harbor worker keeps its identity."""


class HarborExecutor:
    reconnect_running = True

    def __init__(self, manifest: dict, root: Path, env_file: Path | None):
        self.manifest = manifest
        self.root = root.resolve()
        self.env_file = env_file.resolve() if env_file else None
        self.detached = threading.Event()
        self.processes = {}
        current = runtime_source_files()
        if current != manifest["executor_source_files"]:
            raise ValueError("Evaluation controller changed; resume from its frozen version")
        if runtime_identity()["digest"] != manifest["runtime_identity"]["digest"]:
            raise ValueError("Evaluation runtime changed; resume from its frozen version")

    def detach(self):
        self.detached.set()

    def _wait(self, launch):
        while True:
            command = Path(f"/proc/{launch['pid']}/cmdline")
            try:
                argv = command.read_bytes().split(b"\0")
                alive = b"evaluation.harbor.worker" in argv and launch["config"].encode() in argv
            except OSError:
                alive = False
            if not alive:
                process = self.processes.pop(launch["pid"], None)
                if process:
                    process.wait()
                return
            if self.detached.wait(2):
                raise EvaluationDetached()

    def __call__(self, trial, attempt, attempt_root):
        if self.detached.is_set():
            raise EvaluationDetached()
        case = next(
            c
            for c in self.manifest["cases"]
            if c["benchmark"] == trial["benchmark"] and c["task_id"] == trial["task_id"]
        )
        verify_case(case)
        execution = self.root / "trials" / trial["trial_id"] / "execution"
        execution.mkdir(parents=True, exist_ok=True)
        launch_path = execution / "launch.json"
        jobs = execution / "jobs"
        source = execution / "config.json"
        worker_receipt = execution / "worker.json"
        claim = execution / "claimed.json"
        if not launch_path.exists() and worker_receipt.exists():
            launch_path.write_text(worker_receipt.read_text())
        if not launch_path.exists() and claim.exists():
            return self._invalid(
                trial,
                attempt,
                "Launch was claimed without a worker receipt; refusing duplicate Agent execution",
                execution,
                outcome=OutcomeKind.INFRASTRUCTURE_FAILURE,
                raw=None,
                source_result=None,
                rewards=None,
            )
        if not launch_path.exists():
            config = job_config(self.manifest, trial, jobs, "trial-" + trial["trial_id"])
            config["integration_runtime_digest"] = self.manifest["runtime_identity"]["digest"]
            source.write_text(json.dumps(config, indent=2) + "\n")
            with claim.open("x") as handle:
                json.dump({"config": str(source), "actor_launches": 1}, handle)
            argv = [sys.executable, "-u", "-m", "evaluation.harbor.worker", str(source)]
            if self.env_file:
                argv += ["--env-file", str(self.env_file)]
            with (execution / "controller.log").open("ab") as log:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            launch = {"pid": process.pid, "config": str(source), "actor_launches": 1}
            self.processes[process.pid] = process
            temporary = launch_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(launch, indent=2) + "\n")
            temporary.replace(launch_path)
        else:
            launch = json.loads(launch_path.read_text())
        self._wait(launch)
        results = list(jobs.glob("*/*/result.json"))
        if len(results) != 1:
            return self._invalid(
                trial,
                attempt,
                "Harbor worker ended without a unique trial result",
                execution,
                outcome=OutcomeKind.INFRASTRUCTURE_FAILURE,
                raw=None,
                source_result=None,
                rewards=None,
            )
        original_path = results[0]
        raw = json.loads(original_path.read_text())
        if not raw.get("agent_execution"):
            return self._invalid(
                trial,
                attempt,
                "Harbor failed before Agent execution; see infrastructure logs",
                execution,
                outcome=OutcomeKind.INFRASTRUCTURE_FAILURE,
                raw=raw,
                source_result=original_path,
                rewards=None,
            )
        exception = raw.get("exception_info") or {}
        if exception.get("exception_type") in {
            "ReadTimeout",
            "WriteError",
            "RemoteProtocolError",
            "SandboxUnreachableException",
            "SandboxNotRunningException",
            "ConnectTimeout",
            "ConnectError",
            "SandboxException",
            "SandboxNotFoundException",
            "APIException",
            "ApiRateLimitError",
            "ApiUsageLimitError",
            "ApiInternalServerError",
            "ApiOverloadedError",
            "ApiConnectionClosedError",
            "ApiResponseStalledError",
            "ApiProviderResourceNotFoundError",
            "AgentAuthenticationError",
            "ModelNotFoundError",
            "NetworkConnectionError",
            "CommandCleanupError",
        } or "MCP transport infrastructure failed" in exception.get("exception_message", ""):
            return self._invalid(
                trial,
                attempt,
                "Task environment transport failed; see infrastructure logs",
                execution,
                outcome=OutcomeKind.INFRASTRUCTURE_FAILURE,
                raw=raw,
                source_result=original_path,
                rewards=None,
            )
        verdict = raw.get("verifier_result") or {}
        rewards = verdict.get("rewards")
        issues = grade_issues(
            case,
            rewards,
            original_path.parent / "verifier",
        )
        if verdict.get("exception_info") or (raw.get("exception_info") or {}).get(
            "exception_type", ""
        ).startswith("Verifier"):
            issues.append("Official verifier raised an exception")
        if issues:
            return self._invalid(
                trial,
                attempt,
                "; ".join(issues),
                execution,
                outcome=OutcomeKind.GRADER_FAILURE,
                raw=raw,
                source_result=original_path,
                rewards=rewards,
            )
        return self._result(trial, attempt, raw, rewards, original_path)

    def _invalid(self, trial, attempt, error, execution, *, outcome, raw, source_result, rewards):
        receipt = self._execution_receipt(trial, raw or {}, source_result)
        return TrialResult(
            trial_id=trial["trial_id"],
            attempt=attempt,
            outcome=outcome,
            passed=False,
            terminal_reply=receipt["terminal_reply"],
            normal_reply=receipt["normal_reply"],
            grader_reached=bool(
                ((raw or {}).get("verifier_execution") or {}).get("started_at")
                or ((raw or {}).get("verifier_result") or {}).get("rewards") is not None
                or ((raw or {}).get("verifier_result") or {}).get("exception_info")
            ),
            elapsed_seconds=receipt["elapsed_seconds"],
            metrics={
                **receipt["metrics"],
                "valid_grade": False,
                "unvalidated_rewards": rewards,
            },
            artifacts={
                "execution": str(execution),
                "source_result": str(source_result) if source_result else "",
            },
            error=error,
        )

    def _execution_receipt(self, trial, raw, source_result):
        """Agent execution facts survive missing or invalid official grades."""
        execution = raw.get("agent_execution") or {}
        exception = (raw.get("exception_info") or {}).get("exception_type")
        agent_exception = None if (exception or "").startswith("Verifier") else exception
        driver_record = {}
        user_record = {}
        terminal_reply = False
        if source_result is not None:
            agent = source_result.parent / "agent"
            driver = agent / "harness-driver-result.json"
            driver_record = json.loads(driver.read_text()) if driver.is_file() else {}
            user_path = agent / "user-session-result.json"
            user_record = json.loads(user_path.read_text()) if user_path.is_file() else {}
            terminal_reply = (agent / "harness-reply.txt").exists()
            candidate = next(h for h in self.manifest["harnesses"] if h["id"] == trial["harness"])
            if candidate.get("kind") == "harbor":
                trajectory = agent / "trajectory.json"
                if trajectory.is_file():
                    steps = json.loads(trajectory.read_text()).get("steps", [])
                    terminal_reply = bool(
                        steps
                        and steps[-1].get("source") == "agent"
                        and steps[-1].get("message")
                        and not steps[-1].get("tool_calls")
                    )
        elapsed = driver_record.get("elapsed_seconds", 0)
        if execution.get("started_at") and execution.get("finished_at"):
            elapsed = max(
                0,
                (
                    datetime.fromisoformat(execution["finished_at"])
                    - datetime.fromisoformat(execution["started_at"])
                ).total_seconds(),
            )
        usage = {}
        if source_result is not None:
            from evaluation.usage import collect

            candidate = next(h for h in self.manifest["harnesses"] if h["id"] == trial["harness"])
            usage = collect(
                source_result.parent / "agent", raw.get("agent_result"), candidate.get("agent")
            )
        return {
            "terminal_reply": terminal_reply,
            "normal_reply": terminal_reply
            and not agent_exception
            and driver_record.get("normal_reply", True),
            "elapsed_seconds": elapsed,
            "metrics": {
                "agent_exception": agent_exception,
                "harness_termination_reason": driver_record.get("termination_reason"),
                "agent_execution": execution,
                "actor_launches": 1,
                "usage": usage,
                "official_deadline_reached": agent_exception == "AgentTimeoutError"
                or driver_record.get("termination_reason") == "TimeoutError",
                **({"simulated_user": user_record} if user_record else {}),
            },
        }

    def _result(self, trial, attempt, raw, rewards, source_result):
        receipt = self._execution_receipt(trial, raw, source_result)
        score = rewards["reward"]
        exception = (raw.get("exception_info") or {}).get("exception_type")
        termination = receipt["metrics"]["harness_termination_reason"]
        outcome = (
            OutcomeKind.TASK_SUCCESS
            if score > 0
            else (
                OutcomeKind.EVALUATOR_DEADLINE
                if exception == "AgentTimeoutError" or termination == "TimeoutError"
                else OutcomeKind.HARNESS_SELF_TIMEOUT
                if termination == "HarnessSelfTimeout"
                else OutcomeKind.HARNESS_PROTOCOL_ERROR
                if termination == "HarnessProtocolError"
                else OutcomeKind.HARNESS_CRASH
                if exception == "NonZeroAgentExitCodeError"
                or termination == "HarnessExecutionError"
                else OutcomeKind.TASK_FAILURE
            )
        )
        return TrialResult(
            trial_id=trial["trial_id"],
            attempt=attempt,
            outcome=outcome,
            passed=outcome is OutcomeKind.TASK_SUCCESS,
            terminal_reply=receipt["terminal_reply"],
            normal_reply=receipt["normal_reply"],
            grader_reached=True,
            elapsed_seconds=receipt["elapsed_seconds"],
            metrics={
                "official_rewards": rewards,
                "valid_grade": True,
                **receipt["metrics"],
            },
            artifacts={"source_result": str(source_result)},
        )

    def regrade(self, trial_id):
        import asyncio

        from evaluation.harbor.regrade import regrade
        from evaluation.harbor.worker import load_credentials

        from ..state import RunStateStore

        trial = next(t for t in self.manifest["trials"] if t["trial_id"] == trial_id)
        trial_root = self.root / "trials" / trial_id
        state = RunStateStore(self.root, self.manifest)
        cursor = state.load()["trials"][trial_id]
        if (
            cursor["status"] not in {"terminal_invalid", "invalid"}
            or cursor.get("outcome") != OutcomeKind.GRADER_FAILURE.value
        ):
            raise ValueError(
                "Regrade requires a failed grading attempt; valid scores cannot be selected again"
            )
        originals = list((trial_root / "execution/jobs").glob("*/*/result.json"))
        if len(originals) != 1:
            raise ValueError("No unique retained trial to regrade")
        original = json.loads(originals[0].read_text())
        if not original.get("agent_execution"):
            raise ValueError("Cannot regrade a trial that never executed its Harness")
        case = next(
            c
            for c in self.manifest["cases"]
            if c["benchmark"] == trial["benchmark"] and c["task_id"] == trial["task_id"]
        )
        verify_case(case)
        load_credentials(self.env_file)
        destination = trial_root / "grading" / ("grade-" + uuid4().hex)
        job = job_config(self.manifest, trial, destination, "regrade")
        report = asyncio.run(regrade(Path(case["root"]), originals[0].parent, destination, job))
        issues = grade_issues(
            case,
            report.get("rewards"),
            destination / "verifier",
        )
        if not report["artifacts_unchanged"] or report.get("exception_type") or issues:
            raise ValueError("Retained grading remains invalid: " + "; ".join(issues))
        attempt = state.load()["trials"][trial_id]["attempts"]
        result = self._result(trial, attempt, original, report["rewards"], originals[0])
        previous_path = Path(cursor["result"]) if cursor.get("result") else None
        if previous_path is not None and previous_path.is_file():
            from dataclasses import replace

            previous = json.loads(previous_path.read_text())
            if previous.get("metrics", {}).get("experience"):
                result = replace(
                    result,
                    metrics={**result.metrics, "experience": previous["metrics"]["experience"]},
                    artifacts={
                        **result.artifacts,
                        "experience": previous.get("artifacts", {}).get("experience", ""),
                    },
                )
        output = destination / "result.json"
        output.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
        state.transition(
            trial_id,
            "terminal",
            outcome=result.outcome.value,
            result=str(output),
            grading_attempt=str(destination),
        )
        return report
