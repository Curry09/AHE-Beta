"""Resolve benchmark time budgets without importing a benchmark runtime."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AGENT_TIMEOUT_SECONDS = 1800
REMOTE_COMMAND_GRACE_SECONDS = 180
SANDBOX_TTL_GRACE_SECONDS = 900


@dataclass(frozen=True)
class TaskTimeouts:
    """Time limits resolved from pinned task metadata or the suite fallback."""

    agent_seconds: int
    agent_source: str
    verifier_seconds: int | None = None
    environment_build_seconds: int | None = None


def _positive_seconds(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive number of seconds")
    seconds = math.ceil(float(value))
    if seconds <= 0:
        raise ValueError(f"{field} must be a positive number of seconds")
    return seconds


def resolve_task_timeouts(
    task_toml: str | Path | None = None,
    *,
    fallback_agent_seconds: int = DEFAULT_AGENT_TIMEOUT_SECONDS,
) -> TaskTimeouts:
    """Prefer official ``[agent].timeout_sec`` and otherwise use 1800 seconds.

    Verifier and environment-build budgets are returned when the pinned task
    declares them so sandbox TTLs and grader calls cannot undercut the task.
    """

    fallback = _positive_seconds(fallback_agent_seconds, field="fallback_agent_seconds")
    if task_toml is None:
        return TaskTimeouts(
            agent_seconds=fallback,
            agent_source="fallback_no_official_timeout",
        )

    path = Path(task_toml)
    if not path.is_file():
        raise FileNotFoundError(f"task metadata not found: {path}")
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    agent = payload.get("agent")
    verifier = payload.get("verifier")
    environment = payload.get("environment")

    if isinstance(agent, dict) and agent.get("timeout_sec") is not None:
        agent_seconds = _positive_seconds(agent["timeout_sec"], field="agent.timeout_sec")
        source = "official_task_metadata"
    else:
        agent_seconds = fallback
        source = "fallback_no_official_timeout"

    verifier_seconds = None
    if isinstance(verifier, dict) and verifier.get("timeout_sec") is not None:
        verifier_seconds = _positive_seconds(verifier["timeout_sec"], field="verifier.timeout_sec")

    environment_build_seconds = None
    if isinstance(environment, dict) and environment.get("build_timeout_sec") is not None:
        environment_build_seconds = _positive_seconds(
            environment["build_timeout_sec"],
            field="environment.build_timeout_sec",
        )

    return TaskTimeouts(
        agent_seconds=agent_seconds,
        agent_source=source,
        verifier_seconds=verifier_seconds,
        environment_build_seconds=environment_build_seconds,
    )


def remote_command_timeout(agent_seconds: int) -> int:
    """Allow protocol flush/collection after the trial deadline, not more work."""

    return _positive_seconds(agent_seconds, field="agent_seconds") + REMOTE_COMMAND_GRACE_SECONDS


def sandbox_ttl_minutes(*budgets: int | None, minimum_minutes: int = 30) -> int:
    """Size a sandbox lifetime above all sequential work it must host."""

    total = sum(
        _positive_seconds(value, field="sandbox budget") for value in budgets if value is not None
    )
    return max(
        minimum_minutes,
        math.ceil((total + SANDBOX_TTL_GRACE_SECONDS) / 60),
    )
