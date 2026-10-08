"""Execute an operator-fixed custom verifier in isolation (Spec-0083/T4)."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path, PurePosixPath

from ..contracts import GradingRequest, InputValidationError
from ..results import ExecutionEvidence, GradingResult
from .container import (
    TimeBudget,
    VerifierContainer,
    artifact_bytes,
    immutable_image,
    input_hashes,
    require_material,
    resolve_image,
    sha256,
)
from .terminal_bench import failed


class CustomAdapter:
    name = "custom"
    contract_version = 1

    def validate_inputs(self, request: GradingRequest) -> None:
        require_material(request, "script")
        immutable_image(request)
        unknown = set(request.config) - {"image", "argv", "artifact_map"}
        if unknown:
            raise ValueError(f"unknown custom configuration: {sorted(unknown)}")
        argv = request.config.get("argv")
        if (
            not isinstance(argv, (list, tuple))
            or not argv
            or not all(isinstance(arg, str) and arg and "\x00" not in arg for arg in argv)
        ):
            raise ValueError("custom argv must be a nonempty string array")
        if "/grader/script.py" not in argv:
            raise ValueError("custom argv must execute the frozen /grader/script.py")
        mapping = request.config.get("artifact_map", {})
        if not hasattr(mapping, "items"):
            raise ValueError("custom artifact_map must be an object")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("duplicate custom artifact destinations")
        for key, path in mapping.items():
            if (
                not isinstance(path, str)
                or not path.startswith("/inputs/")
                or ".." in PurePosixPath(path).parts
            ):
                raise ValueError("custom inputs must be placed below /inputs/")
            if key not in request.artifacts:
                raise InputValidationError(
                    f"missing custom input: {key}", status="missing_artifact"
                )
            artifact_bytes(request.artifacts[key])

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> GradingResult:
        self.validate_inputs(request)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(request.timeout_seconds)
        try:
            image = resolve_image(
                immutable_image(request), timeout=budget.remaining(), budget=budget
            )
            with VerifierContainer(
                image, attempt_dir, memory_mb=1024, cpus=1, budget=budget
            ) as container:
                script = attempt_dir / "script.py"
                script.write_bytes(require_material(request, "script"))
                container.copy_in(script, "/grader/script.py")
                for name, destination in request.config.get("artifact_map", {}).items():
                    local = attempt_dir / ("input-" + sha256(name.encode())[:16])
                    local.write_bytes(artifact_bytes(request.artifacts[name]))
                    container.copy_in(local, destination)
                code, _ = container.command(
                    list(request.config["argv"]),
                    timeout=request.timeout_seconds,
                    user="65534:65534",
                    workdir="/tmp",
                )
                path = container.copy_out("/logs/verifier/result.json", "custom-result.json")
                if code or path is None:
                    return failed(
                        request, "crashed", "custom verifier failed or did not write result.json"
                    )
                raw = json.loads(path.read_text())
                if not isinstance(raw, dict) or not isinstance(raw.get("passed"), bool):
                    return failed(request, "crashed", "custom result requires a boolean passed")
                score = raw.get("score")
                if score is not None and (
                    isinstance(score, bool)
                    or not isinstance(score, (float, int))
                    or not math.isfinite(score)
                ):
                    return failed(request, "crashed", "invalid custom score")
                evidence = ExecutionEvidence(
                    "isolated_custom_verifier",
                    True,
                    image,
                    {
                        "network": "none",
                        "user": "65534:65534",
                        "script_sha256": request.materials["script"].sha256,
                        "official": False,
                    },
                )
                return GradingResult(
                    self.name,
                    1,
                    "completed",
                    passed=raw["passed"],
                    score=score,
                    score_definition="operator custom rule",
                    execution=evidence,
                    raw_report=raw,
                    report_paths=(str(path),),
                    input_hashes=input_hashes(request),
                    output_hashes={path.name: sha256(path.read_bytes())},
                )
        except subprocess.TimeoutExpired:
            return failed(request, "timed_out", "custom verifier exceeded its budget")
        except (RuntimeError, OSError) as exc:
            return failed(request, "unavailable", str(exc))
        except (ValueError, UnicodeError) as exc:
            return failed(request, "crashed", f"invalid custom result: {exc}")
