"""Official fresh-container SWE-bench objective evidence (spec-0051/T4)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def derive_accept_validity(
    *, end_reason: str, request_outcomes: list[dict[str, Any]], evaluation: dict[str, Any] | None
) -> str:
    """Fail-closed derivation; subjective acceptance never implies technical success."""
    if end_reason != "accepted":
        return "not_applicable"
    if any(row.get("status") in {"timed_out", "crashed"} for row in request_outcomes):
        return "false_accept"
    if not evaluation or evaluation.get("status") != "completed":
        return "unverified_accept"
    if evaluation.get("fresh") is not True or evaluation.get("passed") is not True:
        return "false_accept"
    return "valid_accept"


class SWEbenchEvaluator:
    """Invoke the official SWE-bench harness for exactly one prediction.

    The official runner creates a fresh instance container, applies model_patch,
    applies the benchmark test patch, executes the canonical repo-specific test
    script, and emits a machine report.  We retain that report directory instead
    of trying to reproduce its grading rules here.
    """

    def __init__(
        self,
        dataset_path: str | Path,
        results_root: str | Path,
        *,
        timeout: float = 1800.0,
        python_executable: str = sys.executable,
    ) -> None:
        self.dataset_path = Path(dataset_path).expanduser().resolve()
        self.results_root = Path(results_root).expanduser().resolve()
        self.timeout = timeout
        self.python_executable = python_executable

    @classmethod
    def from_env(cls) -> SWEbenchEvaluator | None:
        # Flow-only experiments can explicitly disable the expensive official
        # evaluator. Normal runs keep the default enabled and fail closed.
        if os.environ.get("AUTO_DESIGNER_OBJECTIVE_EVALUATION", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
            "skip",
        }:
            return None
        dataset = os.environ.get("SWEBENCH_PARQUET", "").strip()
        root = os.environ.get("SWEBENCH_EVAL_RESULTS_ROOT", "").strip()
        if not dataset or not root:
            return None
        return cls(dataset, root)

    @staticmethod
    def image_for(instance_id: str) -> str:
        safe = instance_id.replace("__", "_1776_")
        return f"swebench/sweb.eval.x86_64.{safe}:latest"

    def _normalized_dataset(self, *, instance_id: str, destination: Path) -> Path:
        """Write one pinned parquet row as JSON for the official 4.1 CLI."""
        if self.dataset_path.suffix == ".parquet":
            from datasets import load_dataset

            dataset = load_dataset("parquet", data_files=str(self.dataset_path), split="train")
            rows = [row for row in dataset if row["instance_id"] == instance_id]
        else:
            from swebench.harness.utils import load_swebench_dataset

            rows = load_swebench_dataset(str(self.dataset_path), instance_ids=[instance_id])
        if len(rows) != 1:
            raise ValueError(f"expected exactly one dataset row for {instance_id}, got {len(rows)}")
        row = dict(rows[0])
        destination.write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
        return destination

    def evaluate(self, *, instance_id: str, patch: str) -> dict[str, Any]:
        run_id = f"ad-{instance_id}-{uuid.uuid4().hex[:12]}"
        run_root = self.results_root / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        prediction_path = run_root / "prediction.jsonl"
        prediction_path.write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "model_name_or_path": "auto-designer",
                    "model_patch": patch,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        patch_sha = hashlib.sha256(patch.encode()).hexdigest()
        image = self.image_for(instance_id)
        evaluation_dataset = self._normalized_dataset(
            instance_id=instance_id,
            destination=run_root / "instance.json",
        )
        started_at = _now()
        evidence: dict[str, Any] = {
            "evaluator": "swebench.harness.run_evaluation",
            "instance_id": instance_id,
            "run_id": run_id,
            "dataset": str(self.dataset_path),
            "evaluation_dataset": str(evaluation_dataset),
            "image": image,
            "fresh": True,
            "patch_sha256": patch_sha,
            "prediction_path": str(prediction_path),
            "started_at": started_at,
        }
        inspected = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, text=True
        )
        if inspected.returncode == 0:
            evidence["image_digest"] = str(json.loads(inspected.stdout)[0].get("Id") or image)
        command = [
            self.python_executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            str(evaluation_dataset),
            "--split",
            "test",
            "--instance_ids",
            instance_id,
            "--predictions_path",
            str(prediction_path),
            "--max_workers",
            "1",
            "--run_id",
            run_id,
            "--timeout",
            str(int(self.timeout)),
            "--report_dir",
            str(run_root),
        ]
        evidence["command"] = command
        try:
            proc = subprocess.run(
                command,
                cwd=run_root,
                capture_output=True,
                text=True,
                timeout=self.timeout + 300,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                **evidence,
                "status": "timed_out",
                "passed": False,
                "exit_code": None,
                "stdout": (exc.stdout or "")[-20_000:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-20_000:] if isinstance(exc.stderr, str) else "",
                "finished_at": _now(),
            }
        report_path = run_root / f"auto-designer.{run_id}.json"
        report = None
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report = None
        if proc.returncode != 0 or not isinstance(report, dict):
            return {
                **evidence,
                "status": "unavailable"
                if "No module named 'swebench'" in proc.stderr
                else "crashed",
                "passed": False,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-20_000:],
                "stderr": proc.stderr[-20_000:],
                "finished_at": _now(),
            }
        passed = instance_id in set(report.get("resolved_ids") or [])
        return {
            **evidence,
            "status": "completed",
            "passed": passed,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-20_000:],
            "stderr": proc.stderr[-20_000:],
            "official_report_path": str(report_path),
            "official_report": report,
            "finished_at": _now(),
        }
