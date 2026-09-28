"""Terminal-Bench/Harbor task metadata adapter."""

from __future__ import annotations

import tomllib
from pathlib import Path

from ..schema import CaseRef, InteractionMode, PlanError
from .base import BudgetResolution, CaseSpec, GraderPlan, read_instruction


def _seconds(section: object, key: str) -> int | None:
    if not isinstance(section, dict) or section.get(key) is None:
        return None
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PlanError(f"invalid official timeout: {key}={value!r}")
    return int(value) if int(value) == value else int(value) + 1


class TerminalBenchPlugin:
    name = "Terminal-Bench 4.0"

    def resolve_case(self, case: CaseRef, fallback_seconds: int) -> CaseSpec:
        if not case.root:
            raise PlanError(f"{self.name}/{case.task_id} requires a pinned task root")
        root = Path(case.root)
        task_toml = root / "task.toml"
        payload = tomllib.loads(task_toml.read_text(encoding="utf-8"))
        official_agent = _seconds(payload.get("agent"), "timeout_sec")
        verifier = _seconds(payload.get("verifier"), "timeout_sec")
        build = _seconds(payload.get("environment"), "build_timeout_sec")
        resources = payload.get("environment", {})
        artifacts = payload.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise PlanError(f"{task_toml}: artifacts must be a list")
        return CaseSpec(
            ref=case,
            instruction=read_instruction(root),
            budget=BudgetResolution(
                agent_timeout_seconds=official_agent or fallback_seconds,
                agent_source=(
                    "official_task_metadata"
                    if official_agent is not None
                    else "fallback_no_official_timeout"
                ),
                verifier_timeout_seconds=verifier,
                environment_build_timeout_seconds=build,
            ),
            supported_interactions=frozenset(
                {InteractionMode.DIRECT, InteractionMode.SIMULATED_USER}
            ),
            grader=GraderPlan(
                isolation="fresh_sandbox",
                command="chmod +x /tests/test.sh && cd /tmp && bash /tests/test.sh",
                timeout_seconds=verifier,
                private_paths=("tests", "solution"),
                submission_paths=tuple(str(item) for item in artifacts),
            ),
            resources={
                "cpu": int(resources.get("cpus", 1)),
                "memory_mb": int(resources.get("memory_mb", 4096)),
                "storage_mb": int(resources.get("storage_mb", 10240)),
            },
        )
