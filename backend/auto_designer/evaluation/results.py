"""Normalized grading results, separate from official reports (Spec-0083/T1)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .contracts import freeze, plain

STATUSES = frozenset(
    {
        "completed",
        "not_configured",
        "unsupported",
        "missing_artifact",
        "ungradable",
        "unavailable",
        "crashed",
        "timed_out",
        "not_evaluated",
    }
)
EXECUTION_CONTRACTS = frozenset(
    {
        "fresh_official_instance",
        "agent_stopped_task_environment",
        "trusted_recorded_measurement",
        "isolated_custom_verifier",
    }
)


@dataclass(frozen=True)
class ExecutionEvidence:
    contract: str
    verified: bool
    image_digest: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract not in EXECUTION_CONTRACTS:
            raise ValueError(f"unknown execution contract: {self.contract}")
        if type(self.verified) is not bool:
            raise ValueError("execution verified must be boolean")
        if self.verified and (
            not isinstance(self.image_digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_digest)
        ):
            raise ValueError("verified execution requires an immutable Docker image ID")
        object.__setattr__(self, "details", freeze(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "verified": self.verified,
            "image_digest": self.image_digest,
            "details": plain(self.details),
        }


@dataclass(frozen=True)
class GradingResult:
    adapter: str
    contract_version: int
    status: str
    passed: bool | None = None
    score: float | None = None
    score_definition: str | None = None
    reason: str | None = None
    execution: ExecutionEvidence | None = None
    raw_report: Mapping[str, Any] = field(default_factory=dict)
    report_paths: tuple[str, ...] = ()
    input_hashes: Mapping[str, str] = field(default_factory=dict)
    output_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown grading status: {self.status}")
        if self.passed is not None and not isinstance(self.passed, bool):
            raise ValueError("passed must be boolean or null")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, (float, int))
            or not math.isfinite(self.score)
        ):
            raise ValueError("score must be finite")
        # Legacy SWE fault rows may have passed=false; normalized reports never do.
        if self.status != "completed":
            object.__setattr__(self, "passed", None)
        for name in ("raw_report", "input_hashes", "output_hashes"):
            object.__setattr__(self, name, freeze(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "contract_version": self.contract_version,
            "status": self.status,
            "passed": self.passed,
            "score": self.score,
            "score_definition": self.score_definition,
            "reason": self.reason,
            "execution": self.execution.to_dict() if self.execution else None,
            "raw_report": plain(self.raw_report),
            "report_paths": list(self.report_paths),
            "input_hashes": plain(self.input_hashes),
            "output_hashes": plain(self.output_hashes),
        }
