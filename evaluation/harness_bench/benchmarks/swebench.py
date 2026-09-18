"""SWE-bench Verified patch/grader contract."""

from __future__ import annotations

import json
from pathlib import Path

from ..schema import CaseRef, InteractionMode, PlanError
from .base import BudgetResolution, CaseSpec, GraderPlan


class SweBenchPlugin:
    name = "SWE-bench Verified"

    def resolve_case(self, case: CaseRef, fallback_seconds: int) -> CaseSpec:
        if not case.root:
            raise PlanError("SWE-bench case root must point to its public case JSON")
        source = Path(case.root)
        if source.is_dir():
            source = source / "case.json"
        row = json.loads(source.read_text(encoding="utf-8"))
        instruction = row.get("problem_statement")
        if not isinstance(instruction, str) or not instruction.strip():
            raise PlanError(f"missing SWE-bench problem_statement in {source}")
        eval_script = row.get("eval_script")
        return CaseSpec(
            ref=case,
            instruction=instruction,
            budget=BudgetResolution(
                agent_timeout_seconds=fallback_seconds,
                agent_source="fallback_no_official_timeout",
                verifier_timeout_seconds=int(row.get("verifier_timeout_seconds", 1800)),
            ),
            supported_interactions=frozenset(
                {InteractionMode.DIRECT, InteractionMode.SIMULATED_USER}
            ),
            grader=GraderPlan(
                isolation="fresh_official_image",
                command=str(eval_script) if eval_script else None,
                timeout_seconds=int(row.get("verifier_timeout_seconds", 1800)),
                private_paths=("test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"),
                submission_paths=("model.patch",),
            ),
            resources={
                "cpu": int(row.get("cpu", 2)),
                "memory_mb": int(row.get("memory_mb", 6144)),
                "storage_mb": int(row.get("storage_mb", 10240)),
            },
        )
