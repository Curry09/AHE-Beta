"""Stable outcome taxonomy and validity rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class OutcomeKind(StrEnum):
    TASK_SUCCESS = "task_success"
    TASK_FAILURE = "task_failure"
    HARNESS_SELF_TIMEOUT = "harness_self_timeout"
    EVALUATOR_DEADLINE = "evaluator_deadline"
    HARNESS_CRASH = "harness_crash"
    HARNESS_PROTOCOL_ERROR = "harness_protocol_error"
    GRADER_FAILURE = "grader_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    PROTOCOL_INVALID = "protocol_invalid"

    @property
    def valid_trial(self) -> bool:
        return self in {
            self.TASK_SUCCESS,
            self.TASK_FAILURE,
            self.HARNESS_SELF_TIMEOUT,
            self.EVALUATOR_DEADLINE,
            self.HARNESS_CRASH,
            self.HARNESS_PROTOCOL_ERROR,
        }

    @property
    def retryable_attempt(self) -> bool:
        return self in {
            self.INFRASTRUCTURE_FAILURE,
            self.GRADER_FAILURE,
        }


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    attempt: int
    outcome: OutcomeKind
    passed: bool
    terminal_reply: bool
    normal_reply: bool
    grader_reached: bool
    elapsed_seconds: float
    costs: Mapping[str, float] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, str] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.passed != (self.outcome is OutcomeKind.TASK_SUCCESS):
            raise ValueError("passed must be true exactly for task_success")
        if self.normal_reply and not self.terminal_reply:
            raise ValueError("normal_reply requires terminal_reply")
        if self.attempt < 1 or self.elapsed_seconds < 0:
            raise ValueError("attempt and elapsed_seconds must be non-negative")

    @property
    def valid_trial(self) -> bool:
        return self.outcome.valid_trial

    @property
    def retryable_attempt(self) -> bool:
        return self.outcome.retryable_attempt

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "outcome": self.outcome.value, "valid_trial": self.valid_trial}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrialResult:
        return cls(
            trial_id=str(value["trial_id"]),
            attempt=int(value["attempt"]),
            outcome=OutcomeKind(str(value["outcome"])),
            passed=bool(value["passed"]),
            terminal_reply=bool(value["terminal_reply"]),
            normal_reply=bool(value["normal_reply"]),
            grader_reached=bool(value["grader_reached"]),
            elapsed_seconds=float(value["elapsed_seconds"]),
            costs=dict(value.get("costs", {})),
            metrics=dict(value.get("metrics", {})),
            artifacts=dict(value.get("artifacts", {})),
            error=str(value["error"]) if value.get("error") else None,
        )


class InfrastructureFailure(RuntimeError):
    pass


class GraderFailure(RuntimeError):
    pass


class ProtocolInvalid(RuntimeError):
    pass
