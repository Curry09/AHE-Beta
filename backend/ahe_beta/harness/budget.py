"""Spec-0082/T2: request budgets and infrastructure termination are separate limits."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestLimits:
    request_seconds: float | None
    outer_seconds: float
    grace_seconds: float


def product_budget_environment(limits: RequestLimits) -> dict[str, str]:
    if limits.request_seconds is None:
        return {}
    seconds = limits.request_seconds
    value = str(int(seconds)) if seconds == int(seconds) else str(seconds)
    return {
        key: value
        for key in ("HARNESS_TASK_BUDGET_SECONDS", "HARNESS_CALL_TIMEOUT", "HARNESS_TURN_TIMEOUT")
    }


def request_limits(environment: Mapping[str, str], *, fallback: float) -> RequestLimits:
    """Explicit frozen configuration wins; old launchers retain a bounded fallback."""

    def positive(key: str, default: float | None = None) -> float | None:
        raw = environment.get(key)
        if raw is None or not raw.strip():
            return default
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a positive finite number")
        return value

    request = positive("AHE_BETA_HARNESS_REQUEST_BUDGET_SECONDS")
    grace = positive("AHE_BETA_HARNESS_TERMINATION_GRACE_SECONDS", 60.0)
    assert grace is not None
    # Older products use different environment names. Leave those values alone,
    # but ensure infrastructure termination cannot preempt their declared budget.
    legacy = []
    for key in ("HARNESS_TASK_BUDGET_SECONDS", "HARNESS_CALL_TIMEOUT", "HARNESS_TURN_TIMEOUT"):
        try:
            legacy.append(positive(key))
        except ValueError:
            # Older products may treat malformed knobs as their own defaults.
            # Only our public, frozen settings are strict launcher inputs.
            continue
    inner = request if request is not None else max([fallback, *[v for v in legacy if v]])
    return RequestLimits(request, inner + grace, grace)


class TaskBudget:
    """Spec-0084/T3: one task clock; message/control activity never renews it."""

    def __init__(self, seconds: float | None, *, clock=None) -> None:
        import time

        if seconds is not None and (
            type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
        ):
            raise ValueError("Task budget must be positive finite seconds or null")
        self.seconds = seconds
        self.clock = clock or time.monotonic
        self.started_at: float | None = None
        self.deadline: float | None = None

    def start(self) -> None:
        if self.started_at is None:
            self.started_at = self.clock()
            if self.seconds is not None:
                self.deadline = self.started_at + self.seconds

    def remaining(self) -> float | None:
        if self.deadline is None:
            return self.seconds
        return max(0.0, self.deadline - self.clock())

    def expired(self) -> bool:
        return self.deadline is not None and self.clock() >= self.deadline
