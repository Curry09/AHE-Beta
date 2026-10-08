"""Spec-0083/T4: SWE adapter with a private official CLI executor."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..contracts import GradingRequest, InputValidationError
from ..results import ExecutionEvidence, GradingResult
from .container import TimeBudget, input_hashes, require_material, resolve_image, run_docker


class SWEbenchAdapter:
    name = "swebench"
    contract_version = 1

    def validate_inputs(self, request: GradingRequest) -> None:
        require_material(request, "dataset")
        if not request.instance_id:
            raise InputValidationError("SWE instance_id is required")
        if request.source.get("suite") not in {None, "swebench", "SWE-bench Verified", "swe-bench"}:
            raise InputValidationError("SWE adapter conflicts with task source")
        if request.config:
            unknown = set(request.config) - {"official_dataset_row"}
            if unknown:
                raise ValueError(f"unknown SWE adapter configuration: {sorted(unknown)}")

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> GradingResult:
        self.validate_inputs(request)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(request.timeout_seconds)
        error = _SWEbenchRunner.preflight()
        if error:
            return GradingResult(
                self.name, 1, "unavailable", reason=error, input_hashes=input_hashes(request)
            )
        tag = "grade-" + uuid.uuid4().hex
        namespace = "auto-designer-frozen"
        official = _SWEbenchRunner.image_for(request.instance_id)
        frozen = f"{namespace}/sweb.eval.x86_64.{request.instance_id.lower().replace('__', '_1776_')}:{tag}"
        try:
            digest = resolve_image(official, timeout=budget.remaining(), budget=budget)
            run_docker(["tag", digest, frozen])
            dataset = request.materials["dataset"].path
            if request.config.get("official_dataset_row"):
                dataset = attempt_dir / "instance.json"
                dataset.write_text(json.dumps([dict(request.config["official_dataset_row"])]))
            evaluator = _SWEbenchRunner(
                dataset,
                attempt_dir,
                timeout=budget.remaining(),
                outer_timeout=budget.remaining(),
                image_namespace=namespace,
                instance_image_tag=tag,
            )
            raw = evaluator.evaluate(instance_id=request.instance_id, patch=request.patch)
            still_frozen = (
                resolve_image(frozen, timeout=budget.remaining(30), budget=budget) == digest
            )
            evidence = ExecutionEvidence(
                "fresh_official_instance",
                raw.get("fresh") is True and still_frozen and raw.get("image_digest") == digest,
                digest,
                {"official_image": official, "frozen_image": frozen, "evaluator_version": "4.1.0"},
            )
            if raw.get("status") == "completed" and not evidence.verified:
                status, reason = "ungradable", "frozen official image identity changed"
            else:
                status, reason = str(raw["status"]), raw.get("reason")
            report = attempt_dir / "adapter-result.json"
            report.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
            return GradingResult(
                self.name,
                1,
                status,
                passed=raw.get("passed"),
                score=float(raw["passed"]) if status == "completed" else None,
                score_definition="official SWE-bench resolved",
                reason=reason,
                execution=evidence,
                raw_report=raw,
                report_paths=(str(report),),
                input_hashes=input_hashes(request),
            )
        except subprocess.TimeoutExpired:
            return GradingResult(
                self.name, 1, "timed_out", reason="official image preparation timed out"
            )
        except (RuntimeError, OSError) as exc:
            return GradingResult(self.name, 1, "unavailable", reason=str(exc))
        except (ValueError, KeyError, TypeError) as exc:
            return GradingResult(self.name, 1, "crashed", reason=f"invalid official result: {exc}")
        finally:
            try:
                run_docker(["image", "rm", frozen])
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _SWEbenchRunner:
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
        image_namespace: str | None = None,
        instance_image_tag: str | None = None,
        outer_timeout: float | None = None,
    ) -> None:
        self.dataset_path = Path(dataset_path).expanduser().resolve()
        self.results_root = Path(results_root).expanduser().resolve()
        self.timeout = timeout
        self.python_executable = python_executable
        self.image_namespace = image_namespace
        self.instance_image_tag = instance_image_tag
        self.outer_timeout = outer_timeout

    @staticmethod
    def preflight() -> str | None:
        """Spec-0075/T2: check optional runtime and Docker without allocating instances."""
        try:
            if importlib.util.find_spec("swebench") is None:
                return "evaluation extra is not installed"
            if importlib.metadata.version("swebench") != "4.1.0":
                return "evaluation requires locked swebench 4.1.0"
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return "Docker daemon is unavailable"
        except (OSError, subprocess.TimeoutExpired, importlib.metadata.PackageNotFoundError):
            return "evaluation dependencies or Docker are unavailable"
        return None

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
        elif self.dataset_path.suffix in {".json", ".jsonl"}:
            # Keep deterministic unit/integration fixtures usable without importing the
            # optional SWE-bench package. Production Verified inputs remain parquet.
            if self.dataset_path.suffix == ".jsonl":
                rows = [
                    json.loads(line)
                    for line in self.dataset_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            else:
                payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else [payload]
            rows = [row for row in rows if row.get("instance_id") == instance_id]
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
        if self.image_namespace and self.instance_image_tag:
            image = (
                f"{self.image_namespace}/sweb.eval.x86_64."
                f"{instance_id.lower().replace('__', '_1776_')}:{self.instance_image_tag}"
            )
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
            "evaluation_dataset_sha256": hashlib.sha256(
                evaluation_dataset.read_bytes()
            ).hexdigest(),
            "prediction_sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
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
        # Spec-0083/T4: a unique local tag freezes the selected official image;
        # the runner invokes the official CLI with this frozen identity.
        if self.image_namespace and self.instance_image_tag:
            command += [
                "--namespace",
                self.image_namespace,
                "--instance_image_tag",
                self.instance_image_tag,
            ]
        try:
            evidence["evaluator_version"] = importlib.metadata.version("swebench")
        except importlib.metadata.PackageNotFoundError:
            evidence["evaluator_version"] = "unavailable"
        try:
            proc = subprocess.run(
                command,
                cwd=run_root,
                capture_output=True,
                text=True,
                timeout=self.outer_timeout
                if self.outer_timeout is not None
                else self.timeout + 300,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key
                    in {
                        "PATH",
                        "HOME",
                        "LANG",
                        "LC_ALL",
                        "TMPDIR",
                        "SYSTEMROOT",
                        "DOCKER_HOST",
                        "DOCKER_TLS_VERIFY",
                        "DOCKER_CERT_PATH",
                        "DOCKER_CONFIG",
                    }
                },
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
            except (json.JSONDecodeError, UnicodeError, OSError):
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
        # Spec-0075/T2: absence from resolved is not evidence of an official failure.
        classification = _report_outcome(report=report, instance_id=instance_id)
        # Spec-0075/T2: official 4.1 can label a pytest startup failure unresolved.
        # A summary without executed tests must not become a technical failure score.
        startup_error = _official_test_start_error(
            run_root=run_root, run_id=run_id, instance_id=instance_id
        )
        if startup_error is not None:
            return {
                **evidence,
                "status": "crashed",
                "passed": False,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-20_000:],
                "stderr": proc.stderr[-20_000:],
                "official_report_path": str(report_path),
                "official_report": report,
                "reason": "official_test_start_failed",
                "test_start_error": startup_error,
                "finished_at": _now(),
            }
        if classification is None:
            return {
                **evidence,
                "status": "crashed",
                "passed": False,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-20_000:],
                "stderr": proc.stderr[-20_000:],
                "official_report_path": str(report_path),
                "official_report": report,
                "reason": "unclassified_official_report",
                "finished_at": _now(),
            }
        if classification == "empty":
            return {
                **evidence,
                "status": "not_evaluated",
                "passed": None,
                "fresh": False,
                "reason": "official_empty_prediction",
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-20_000:],
                "stderr": proc.stderr[-20_000:],
                "official_report_path": str(report_path),
                "official_report": report,
                "finished_at": _now(),
            }
        passed = classification
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


def _official_test_start_error(*, run_root: Path, run_id: str, instance_id: str) -> str | None:
    """Identify explicit pytest startup diagnostics, without replacing official grading."""
    output_path = (
        run_root
        / "logs/run_evaluation"
        / run_id
        / "auto-designer"
        / instance_id
        / "test_output.txt"
    )
    if not output_path.resolve().is_relative_to(run_root.resolve()) or not output_path.is_file():
        return None
    output = output_path.read_text(encoding="utf-8", errors="replace")
    if ">>>>> Start Test Output" not in output:
        return None
    section = output.split(">>>>> Start Test Output", 1)[1].split(">>>>> End Test Output", 1)[0]
    for line in section.splitlines():
        if re.match(r"^(?:ImportError while loading conftest|(?:_+ )?ERROR collecting )", line):
            return line[:500]
    return None


def _report_outcome(*, report: dict[str, Any], instance_id: str) -> bool | str | None:
    """Accept an explicit resolved/unresolved target only, rejecting error/incomplete rows."""
    sets: dict[str, set[str]] = {}
    for key in (
        "resolved_ids",
        "unresolved_ids",
        "error_ids",
        "incomplete_ids",
        "missing_ids",
        "empty_patch_ids",
    ):
        values = report.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            return None
        if len(set(values)) != len(values):
            return None
        sets[key] = set(values)
    if any(instance_id in sets[key] for key in ("error_ids", "incomplete_ids", "missing_ids")):
        return None
    resolved = instance_id in sets["resolved_ids"]
    unresolved = instance_id in sets["unresolved_ids"]
    # SWE-bench 4.1 reporting explicitly skips empty patches before fresh execution.
    # https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py
    if instance_id in sets["empty_patch_ids"]:
        return "empty" if not resolved and not unresolved else None
    if resolved == unresolved:
        return None
    return resolved
