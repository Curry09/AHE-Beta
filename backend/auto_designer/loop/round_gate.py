# Spec-0050/T2：本轮准入票终态闸——下一轮用户不得与本轮交付重叠。
"""Wait until this round's admitted issues reach a delivery terminal state.

Empty wait sets succeed immediately. `automation-failed`, `needs-human`, or wall-clock
timeout raise RoundDeliveryBlocked so the experiment does not start the next user round.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Any

NEEDS_HUMAN = "needs-human"
AUTOMATION_FAILED = "automation-failed"
# Spec-0062/T1: current and legacy terminal failures outrank even a closed issue.
_FAILURE_LABELS = frozenset({AUTOMATION_FAILED, NEEDS_HUMAN})
_DEFAULT_TIMEOUT_SEC = 14400.0
_DEFAULT_POLL_SEC = 15.0

_STATUS_DONE = "done"
_STATUS_BLOCKED = "blocked"
_STATUS_INFLIGHT = "inflight"


class RoundDeliveryBlocked(Exception):
    """This round's delivery did not reach a clean terminal state."""

    def __init__(self, *, numbers: list[int], reason: str) -> None:
        self.numbers = list(numbers)
        self.reason = reason
        super().__init__(f"round delivery blocked ({reason}): {self.numbers}")


def _env_float(*, name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _label_names(*, labels: object) -> list[str]:
    names: list[str] = []
    if not isinstance(labels, list):
        return names
    for item in labels:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, Mapping):
            names.append(str(item.get("name") or ""))
    return names


def classify_issue(*, state: str, labels: list[str]) -> str:
    """Classify one issue: done, blocked, or inflight.

    Spec-0062/T1: current/legacy failure labels block regardless of issue state.
    Otherwise closed succeeds and open remains in flight (Spec-0050/T2).
    """
    names = {item.strip() for item in labels if item and item.strip()}
    if _FAILURE_LABELS & names:
        return _STATUS_BLOCKED
    if str(state).strip().lower() == "closed":
        return _STATUS_DONE
    return _STATUS_INFLIGHT


def wait_round_delivery(
    *,
    numbers: list[int],
    fetch_issue: Callable[[int], Mapping[str, Any]],
    timeout_sec: float | None = None,
    poll_sec: float | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> None:
    """Block until every admitted issue is closed without a terminal failure label.

    Spec-0050/T2: empty `numbers` is immediate success and must not call `fetch_issue`.
    """
    unique = list(dict.fromkeys(int(n) for n in numbers))
    if not unique:
        return
    limit = (
        float(timeout_sec)
        if timeout_sec is not None
        else _env_float(name="ROUND_DELIVERY_TIMEOUT_SEC", default=_DEFAULT_TIMEOUT_SEC)
    )
    interval = (
        float(poll_sec)
        if poll_sec is not None
        else _env_float(name="ROUND_DELIVERY_POLL_SEC", default=_DEFAULT_POLL_SEC)
    )
    sleeper = sleep if sleep is not None else time.sleep
    clock = monotonic if monotonic is not None else time.monotonic
    deadline = clock() + limit
    while True:
        blocked: list[int] = []
        failure_reasons: set[str] = set()
        inflight: list[int] = []
        for number in unique:
            snapshot = fetch_issue(number)
            labels = _label_names(labels=snapshot.get("labels"))
            status = classify_issue(
                state=str(snapshot.get("state") or ""),
                labels=labels,
            )
            if status == _STATUS_BLOCKED:
                blocked.append(number)
                failure_reasons.update(_FAILURE_LABELS & {label.strip() for label in labels})
            elif status == _STATUS_INFLIGHT:
                inflight.append(number)
        if blocked:
            raise RoundDeliveryBlocked(numbers=blocked, reason=",".join(sorted(failure_reasons)))
        if not inflight:
            return
        if clock() >= deadline:
            raise RoundDeliveryBlocked(numbers=inflight, reason="timeout")
        sleeper(interval)
