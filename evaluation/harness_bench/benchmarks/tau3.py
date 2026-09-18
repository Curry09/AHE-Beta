"""tau3 native-user and reward contract."""

from __future__ import annotations

from pathlib import Path

from ..schema import CaseRef, InteractionMode, PlanError
from .base import BudgetResolution, CaseSpec, GraderPlan


class Tau3Plugin:
    name = "tau3-bench Core/Text"

    def resolve_case(self, case: CaseRef, fallback_seconds: int) -> CaseSpec:
        instruction = f"tau3 native task {case.task_id}"
        if case.root:
            path = Path(case.root)
            if path.is_file():
                instruction = path.read_text(encoding="utf-8")
        if not case.revision:
            raise PlanError("tau3 source revision must be pinned")
        return CaseSpec(
            ref=case,
            instruction=instruction,
            budget=BudgetResolution(
                agent_timeout_seconds=fallback_seconds,
                agent_source="fallback_no_official_timeout",
                clock="benchmark_native",
            ),
            supported_interactions=frozenset({InteractionMode.BENCHMARK_NATIVE}),
            grader=GraderPlan(
                isolation="benchmark_native",
                command=None,
                timeout_seconds=None,
            ),
            resources={"cpu": 2, "memory_mb": 6144, "storage_mb": 10240},
        )
