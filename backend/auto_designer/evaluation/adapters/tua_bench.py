"""Reconstruct the first pinned Excel verifier without altering it (Spec-0083/T4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..contracts import GradingRequest, InputValidationError
from ..results import ExecutionEvidence, GradingResult
from .container import (
    TimeBudget,
    VerifierContainer,
    artifact_bytes,
    build_environment,
    require_material,
    sha256,
    write_files,
)
from .profiles import validate_task_bundle
from .terminal_bench import failed, official_reward, validate_mapping

# Material identity is filled from the official remote file during implementation;
# its bytes must be fixed, even though the test's original URL uses resolve/main.
EXPECTED_SHA256 = "7ece6ea65cf8bfe157a5d8b5140bd071f417430ba76fc69a5da6b1ba534dcb9b"


class TUABenchAdapter:
    name = "tua-bench"
    contract_version = 1

    def validate_inputs(self, request: GradingRequest) -> None:
        validate_task_bundle(request)
        if request.config.get("build_official_environment") is not True:
            raise InputValidationError(
                "reconstruct the pinned official task environment before grading"
            )
        unknown = set(request.config) - {"revision", "build_official_environment", "artifact_map"}
        if unknown:
            raise ValueError(f"unknown TUA adapter configuration: {sorted(unknown)}")
        expected = require_material(request, "expected")
        if sha256(expected) != EXPECTED_SHA256:
            raise InputValidationError(
                "expected workbook is not the pinned official answer material"
            )
        validate_mapping(request, {"/app/BoomerangSales.xlsx": None})

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> GradingResult:
        self.validate_inputs(request)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(request.timeout_seconds)
        files, modes, metadata = validate_task_bundle(request)
        write_files(files, attempt_dir / "task", modes)
        try:
            image = build_environment(
                attempt_dir / "task/environment",
                "Dockerfile",
                attempt_dir,
                timeout=budget.remaining(metadata["environment"]["build_timeout_sec"]),
            )
            with VerifierContainer(
                image,
                attempt_dir,
                memory_mb=metadata["environment"]["memory_mb"],
                cpus=metadata["environment"]["cpus"],
                budget=budget,
            ) as container:
                container.copy_in(attempt_dir / "task/tests/.", "/tests")
                expected = attempt_dir / "expected.xlsx"
                expected.write_bytes(require_material(request, "expected"))
                container.copy_in(
                    expected, "/tmp/010-pivot-product-revenue/8_BoomerangSales_gt1.xlsx"
                )
                for name, destination in request.config["artifact_map"].items():
                    local = attempt_dir / "submitted.xlsx"
                    local.write_bytes(artifact_bytes(request.artifacts[name]))
                    container.copy_in(local, destination)
                # Verify-only process: no Harness/agent is started in this reconstructed instance.
                exit_code, log = container.command(
                    ["bash", "/tests/test.sh"],
                    timeout=min(request.timeout_seconds, metadata["verifier"]["timeout_sec"]),
                    user=metadata["verifier"]["user"],
                    workdir="/tmp",
                )
                evidence = ExecutionEvidence(
                    "agent_stopped_task_environment",
                    True,
                    image,
                    {
                        "environment": "reconstructed_official_task",
                        "agent_process_present": False,
                        "revision": request.config["revision"],
                        "expected_sha256": EXPECTED_SHA256,
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
