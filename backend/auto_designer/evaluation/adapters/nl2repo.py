"""Pinned TinyDB post-processing and official score parser (Spec-0083/T4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..contracts import GradingRequest, InputValidationError
from ..results import ExecutionEvidence, GradingResult
from .container import (
    TimeBudget,
    VerifierContainer,
    archive_files,
    artifact_bytes,
    immutable_image,
    input_hashes,
    require_material,
    resolve_image,
    sha256,
    write_files,
)
from .terminal_bench import failed

REVISION = "781a1da1ee41fb8edb0bed22f586d69111610edf"
# The OCI manifest digest was resolved from the official tinydb:1.0 repository.
# Never resolve that mutable tag again during grading contract version 1.
OFFICIAL_IMAGE = "ghcr.io/multimodal-art-projection/nl2repobench/tinydb@sha256:3db19fe6b19b93ed836def4c78e351fc95454018a3978057ffdf99e3bb2ff1cc"
MATERIAL_HASHES = {
    "post_processor": "a681bcb48c6199b74a72c92b97f30b63a6f0da7875428e82c6e370f82000e450",
    "test_commands": "3bd822b96ae432d75e8a3d09a40c856f17f3164f200f1eb0fee6b684be49ace9",
    "test_files": "af7f0b2bd342822f2fa8e6a9fda610570f911f30d3108379ea4184c0866727c3",
    "test_count": "fc56dbc6d4652b315b86b71c8d688c1ccdea9c5f1fd07763d2659fde2e2fc49a",
}

# Execute only the exact official preprocessing/parser functions inside the
# verifier. The official module's Docker orchestration/imports are not copied.
RUNNER = """import ast,json,logging,os,re,shutil,subprocess
from typing import List, Dict, Any
tree=ast.parse(open('/grader/post_processor.py').read())
names={'remove_package_files','remove_test_files','analyze_pytest_results'}
module=ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names],type_ignores=[])
exec(compile(module,'official-post-processor','exec'),globals())
logger=logging.getLogger('official-nl2repo')
test_files=json.load(open('/grader/test_files'))
commands=json.load(open('/grader/test_commands'))
count=int(open('/grader/test_count').read())
remove_package_files('/submission',logger)
remove_test_files('/submission',test_files,logger)
shutil.copytree('/submission','/workspace',dirs_exist_ok=True)
os.chdir('/workspace')
os.environ['PYTHONPATH']='/workspace:'+os.environ.get('PYTHONPATH','')
results=[]
for command in commands:
    proc=subprocess.run(command,shell=True,capture_output=True,text=True)
    results.append({'command':command,'exit_code':proc.returncode,'output':proc.stdout+proc.stderr})
    print(proc.stdout+proc.stderr,flush=True)
score=analyze_pytest_results(results,count,logger)
json.dump({'command_results':results,'pytest_results':score},open('/logs/verifier/result.json','w'))
"""


class NL2RepoAdapter:
    name = "nl2repo"
    contract_version = 1

    def validate_plan(self, request: GradingRequest) -> dict[str, str]:
        task = request.source.get("instance_id") or request.instance_id or request.task_id
        if (
            task != "tinydb"
            or request.source.get("revision") != REVISION
            or request.config.get("revision") != REVISION
        ):
            raise InputValidationError(
                "only the pinned official TinyDB profile is supported", status="unsupported"
            )
        for key, digest in MATERIAL_HASHES.items():
            if sha256(require_material(request, key)) != digest:
                raise InputValidationError(f"{key} does not match the pinned official source")
        image = immutable_image(request)
        if "@" in image and image != OFFICIAL_IMAGE:
            raise InputValidationError("NL2Repo image must identify the official TinyDB repository")
        unknown = set(request.config) - {"revision", "image", "operator_pass_threshold"}
        if unknown:
            raise ValueError(f"unknown NL2Repo configuration: {sorted(unknown)}")
        threshold = request.config.get("operator_pass_threshold")
        if threshold is not None and (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 1
        ):
            raise ValueError("operator_pass_threshold must be between 0 and 1")

        return {"generated_repository": "workspace"}

    def validate_inputs(self, request: GradingRequest) -> None:
        self.validate_plan(request)
        if "generated_repository" not in request.artifacts:
            raise InputValidationError(
                "generated_repository tar is missing", status="missing_artifact"
            )
        files = archive_files(artifact_bytes(request.artifacts["generated_repository"]))
        if not files:
            raise InputValidationError("generated repository is empty")

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> GradingResult:
        self.validate_inputs(request)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(request.timeout_seconds)
        try:
            image = resolve_image(
                immutable_image(request), timeout=budget.remaining(), budget=budget
            )
            official_image = resolve_image(
                OFFICIAL_IMAGE, timeout=budget.remaining(), budget=budget
            )
            if image != official_image:
                return failed(
                    request, "ungradable", "configured image differs from the official TinyDB image"
                )
            write_files(
                archive_files(artifact_bytes(request.artifacts["generated_repository"])),
                attempt_dir / "submission",
            )
            runner = attempt_dir / "runner.py"
            runner.write_text(RUNNER)
            with VerifierContainer(image, attempt_dir, budget=budget) as container:
                container.copy_in(attempt_dir / "submission", "/submission")
                for key, material in request.materials.items():
                    if key in MATERIAL_HASHES:
                        container.copy_in(
                            material.path,
                            "/grader/" + ("post_processor.py" if key == "post_processor" else key),
                        )
                container.copy_in(runner, "/grader/runner.py")
                code, _ = container.command(
                    ["python", "/grader/runner.py"],
                    timeout=request.timeout_seconds,
                    workdir="/workspace",
                )
                result_path = container.copy_out(
                    "/logs/verifier/result.json", "official-result.json"
                )
                if code or result_path is None:
                    return failed(
                        request, "crashed", "official post-processing did not produce a result"
                    )
                raw = json.loads(result_path.read_text())
                score = float(raw["pytest_results"]["success_rate"])
                threshold = request.config.get("operator_pass_threshold")
                if threshold is not None:
                    raw["operator_policy"] = {
                        "pass_threshold": threshold,
                        "official_binary_rule": False,
                    }
                evidence = ExecutionEvidence(
                    "fresh_official_instance",
                    True,
                    image,
                    {
                        "official_image": OFFICIAL_IMAGE,
                        "revision": REVISION,
                        "post_processor_sha256": MATERIAL_HASHES["post_processor"],
                        "official_binary_rule": False,
                    },
                )
                return GradingResult(
                    self.name,
                    1,
                    "completed",
                    passed=None if threshold is None else score >= threshold,
                    score=score,
                    score_definition="official min(passed / fixed test_case_count, 1)",
                    execution=evidence,
                    raw_report=raw,
                    report_paths=(str(result_path), str(attempt_dir / "verifier.log")),
                    input_hashes=input_hashes(request),
                    output_hashes={"official-result.json": sha256(result_path.read_bytes())},
                )
        except subprocess.TimeoutExpired:
            return failed(
                request, "timed_out", "official image preparation or test commands exceeded budget"
            )
        except (RuntimeError, OSError) as exc:
            return failed(request, "unavailable", str(exc))
        except (ValueError, KeyError) as exc:
            return failed(request, "crashed", f"invalid official result: {exc}")
