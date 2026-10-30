"""Run exact pinned separate Terminal-Bench verifiers (Spec-0083/T4)."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from ..contracts import GradingRequest, InputValidationError
from ..results import ExecutionEvidence, GradingResult
from .container import (
    TimeBudget,
    VerifierContainer,
    artifact_bytes,
    build_environment,
    input_hashes,
    sha256,
    write_files,
)
from .profiles import validate_task_bundle


def artifact_targets(metadata: dict[str, Any]) -> dict[str, str | None]:
    return {
        item if isinstance(item, str) else item.get("target", item["source"]): None
        if isinstance(item, str)
        else item.get("service")
        for item in metadata["artifacts"]
    }


def validate_mapping_plan(
    request: GradingRequest, targets: dict[str, str | None]
) -> dict[str, str]:
    mapping = request.config.get("artifact_map")
    if not isinstance(mapping, dict) and not hasattr(mapping, "items"):
        raise InputValidationError("artifact_map must map collected IDs to official destinations")
    if set(mapping.values()) != set(targets) or len(set(mapping.values())) != len(mapping):
        raise InputValidationError(
            "artifact destinations must exactly match the pinned official task"
        )
    return {
        name: "managed_service" if targets[destination] else "workspace"
        for name, destination in mapping.items()
    }


def validate_mapping(request: GradingRequest, targets: dict[str, str | None]) -> None:
    validate_mapping_plan(request, targets)
    for name, destination in request.config["artifact_map"].items():
        if name not in request.artifacts:
            raise InputValidationError(
                f"missing required artifact: {name}", status="missing_artifact"
            )
        item = request.artifacts[name]
        artifact_bytes(item)
        if targets[destination]:
            receipt = item.metadata
            if (
                item.source != "managed_service"
                or receipt.get("service") != targets[destination]
                or receipt.get("owner_session_id") != request.session_id
                or not receipt.get("service_id")
                or not receipt.get("sealed_at")
                or receipt.get("controller_owned") is not True
                or receipt.get("isolated") is not True
                or receipt.get("agent_stopped") is not True
            ):
                raise InputValidationError(
                    "original managed measurement ownership/isolation/seal is missing"
                )


def failed(request: GradingRequest, status: str, reason: str) -> GradingResult:
    return GradingResult(
        request.adapter, 1, status, reason=reason, input_hashes=input_hashes(request)
    )


def official_reward(
    request: GradingRequest,
    output: Path,
    container: VerifierContainer,
    execution: ExecutionEvidence,
    *,
    exit_code: int,
    log: str,
    binary: bool,
) -> GradingResult:
    path = container.copy_out("/logs/verifier/reward.txt", "reward.txt")
    diagnostic = container.copy_out("/logs/verifier/ctrf.json", "ctrf.json")
    if path is None:
        return failed(request, "crashed", "official verifier did not emit reward.txt")
    try:
        reward = float(path.read_text().strip())
        if not math.isfinite(reward) or not 0 <= reward <= 1 or (binary and reward not in {0, 1}):
            raise ValueError("invalid official reward")
    except ValueError:
        return failed(request, "crashed", "official reward is invalid")
    raw = {"reward": reward, "verifier_exit_code": exit_code, "log_tail": log}
    if diagnostic is not None:
        try:
            raw["ctrf"] = json.loads(diagnostic.read_text())
        except (ValueError, UnicodeError):
            pass
    paths = (path, output / "verifier.log") + ((diagnostic,) if diagnostic else ())
    precondition_failure = any(
        test.get("name") == "environment" and test.get("status") != "passed"
        for test in raw.get("ctrf", {}).get("results", {}).get("tests", [])
    )
    return GradingResult(
        request.adapter,
        1,
        "ungradable" if precondition_failure else "completed",
        passed=(reward == 1) if binary else None,
        score=reward,
        score_definition="official reward.txt",
        reason="official verifier environment/material precondition failed"
        if precondition_failure
        else None,
        execution=execution,
        raw_report=raw,
        report_paths=tuple(str(item) for item in paths),
        input_hashes=input_hashes(request),
        output_hashes={item.name: sha256(item.read_bytes()) for item in paths},
    )


class TerminalBenchAdapter:
    name = "terminal-bench"
    contract_version = 1

    def validate_plan(self, request: GradingRequest) -> dict[str, str]:
        _, _, metadata = validate_task_bundle(request)
        if metadata.get("verifier", {}).get("environment_mode") != "separate":
            raise InputValidationError(
                "only pinned separate verifier profiles are supported", status="unsupported"
            )
        if request.config.get("build_official_environment") is not True:
            raise InputValidationError(
                "official verifier environment must be built from the locked task bundle"
            )
        unknown = set(request.config) - {"revision", "build_official_environment", "artifact_map"}
        if unknown:
            raise ValueError(f"unknown Terminal adapter configuration: {sorted(unknown)}")
        return validate_mapping_plan(request, artifact_targets(metadata))

    def validate_inputs(self, request: GradingRequest) -> None:
        self.validate_plan(request)
        _, _, metadata = validate_task_bundle(request)
        validate_mapping(request, artifact_targets(metadata))

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> GradingResult:
        self.validate_inputs(request)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(request.timeout_seconds)
        files, modes, metadata = validate_task_bundle(request)
        write_files(files, attempt_dir / "task", modes)
        build_timeout = min(request.timeout_seconds, metadata["environment"]["build_timeout_sec"])
        timeout = min(request.timeout_seconds, metadata["verifier"]["timeout_sec"])
        try:
            image = build_environment(
                attempt_dir / "task/tests",
                "Dockerfile",
                attempt_dir,
                timeout=budget.remaining(build_timeout),
            )
            targets = artifact_targets(metadata)
            managed = any(targets.values())
            with VerifierContainer(
                image,
                attempt_dir,
                memory_mb=metadata["environment"]["memory_mb"],
                cpus=metadata["environment"]["cpus"],
                budget=budget,
            ) as container:
                for name, destination in request.config["artifact_map"].items():
                    local = attempt_dir / ("input-" + sha256(name.encode())[:16])
                    local.write_bytes(artifact_bytes(request.artifacts[name]))
                    container.copy_in(local, destination)
                exit_code, log = container.command(
                    ["bash", "/tests/test.sh"], timeout=timeout, workdir="/tmp"
                )
                evidence = ExecutionEvidence(
                    "trusted_recorded_measurement" if managed else "fresh_official_instance",
                    True,
                    image,
                    {
                        "revision": request.config["revision"],
                        "verifier_mode": "separate",
                        "agent_process_present": False,
                        "environment_built_from_verified_tree": True,
                    },
                )
                return official_reward(
                    request,
                    attempt_dir,
                    container,
                    evidence,
                    exit_code=exit_code,
                    log=log,
                    binary=True,
                )
        except subprocess.TimeoutExpired:
            return failed(request, "timed_out", "official build or verifier exceeded its budget")
        except (RuntimeError, OSError) as exc:
            return failed(request, "unavailable", str(exc))
