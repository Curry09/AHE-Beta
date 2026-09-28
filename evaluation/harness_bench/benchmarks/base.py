"""Provider-neutral benchmark plugin contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..schema import CaseRef, InteractionMode

OUTER_AGENT_GRACE_SECONDS = 600


def outer_agent_timeout_seconds(official_agent_timeout_seconds: int) -> int:
    """Return the Harbor watchdog deadline including persistence grace."""
    if official_agent_timeout_seconds <= 0:
        raise ValueError("official agent timeout must be positive")
    return official_agent_timeout_seconds + OUTER_AGENT_GRACE_SECONDS


@dataclass(frozen=True)
class BudgetResolution:
    agent_timeout_seconds: int
    agent_source: str
    verifier_timeout_seconds: int | None = None
    environment_build_timeout_seconds: int | None = None
    clock: str = "trial_wall"

    @property
    def outer_agent_timeout_seconds(self) -> int:
        """Watchdog deadline; grace is for persistence, not model work."""
        return outer_agent_timeout_seconds(self.agent_timeout_seconds)


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
