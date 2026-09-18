"""Provider-neutral benchmark plugin contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..schema import CaseRef, InteractionMode


@dataclass(frozen=True)
class BudgetResolution:
    agent_timeout_seconds: int
    agent_source: str
    verifier_timeout_seconds: int | None = None
    environment_build_timeout_seconds: int | None = None
    clock: str = "trial_wall"


@dataclass(frozen=True)
class GraderPlan:
    isolation: str
    command: str | None
    timeout_seconds: int | None
    private_paths: tuple[str, ...] = ()
    submission_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseSpec:
    ref: CaseRef
    instruction: str
    budget: BudgetResolution
    supported_interactions: frozenset[InteractionMode]
    grader: GraderPlan
    resources: Mapping[str, int]


class BenchmarkPlugin(Protocol):
    name: str

    def resolve_case(self, case: CaseRef, fallback_seconds: int) -> CaseSpec: ...


def read_instruction(root: Path) -> str:
    path = root / "instruction.md"
    if not path.is_file():
        raise FileNotFoundError(f"public task instruction not found: {path}")
    return path.read_text(encoding="utf-8")
