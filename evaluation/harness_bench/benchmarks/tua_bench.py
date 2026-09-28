"""TUA task adapter; verifier enters only after Harness shutdown."""

from __future__ import annotations

from ..schema import CaseRef
from .base import CaseSpec, GraderPlan
from .terminal_bench import TerminalBenchPlugin


class TuaBenchPlugin(TerminalBenchPlugin):
    name = "TUA-Bench"

    def resolve_case(self, case: CaseRef, fallback_seconds: int) -> CaseSpec:
        resolved = super().resolve_case(case, fallback_seconds)
        return CaseSpec(
            ref=resolved.ref,
            instruction=resolved.instruction,
            budget=resolved.budget,
            supported_interactions=resolved.supported_interactions,
            grader=GraderPlan(
                isolation="same_task_sandbox_after_agent_exit",
                command=resolved.grader.command,
                timeout_seconds=resolved.grader.timeout_seconds,
                private_paths=resolved.grader.private_paths,
                submission_paths=resolved.grader.submission_paths,
            ),
            resources=resolved.resources,
        )
