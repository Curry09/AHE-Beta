from __future__ import annotations

from pathlib import Path

import pytest
from timeout_policy import (
    DEFAULT_AGENT_TIMEOUT_SECONDS,
    remote_command_timeout,
    resolve_task_timeouts,
    sandbox_ttl_minutes,
)


def test_missing_official_timeout_uses_1800_second_fallback() -> None:
    budget = resolve_task_timeouts()

    assert budget.agent_seconds == DEFAULT_AGENT_TIMEOUT_SECONDS == 1800
    assert budget.agent_source == "fallback_no_official_timeout"
    assert budget.verifier_seconds is None


def test_official_task_metadata_wins_over_fallback(tmp_path: Path) -> None:
    task = tmp_path / "task.toml"
    task.write_text(
        """
[agent]
timeout_sec = 7200.0
[verifier]
timeout_sec = 60.0
[environment]
build_timeout_sec = 600.0
""".strip(),
        encoding="utf-8",
    )

    budget = resolve_task_timeouts(task)

    assert budget.agent_seconds == 7200
    assert budget.agent_source == "official_task_metadata"
    assert budget.verifier_seconds == 60
    assert budget.environment_build_seconds == 600


def test_missing_agent_section_still_uses_fallback(tmp_path: Path) -> None:
    task = tmp_path / "task.toml"
    task.write_text("[verifier]\ntimeout_sec = 120\n", encoding="utf-8")

    budget = resolve_task_timeouts(task)

    assert budget.agent_seconds == 1800
    assert budget.agent_source == "fallback_no_official_timeout"
    assert budget.verifier_seconds == 120


@pytest.mark.parametrize("value", [0, -1, True, "3600"])
def test_invalid_official_agent_timeout_is_rejected(tmp_path: Path, value: object) -> None:
    task = tmp_path / "task.toml"
    rendered = str(value).lower() if isinstance(value, bool) else repr(value)
    task.write_text(f"[agent]\ntimeout_sec = {rendered}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="agent.timeout_sec"):
        resolve_task_timeouts(task)


def test_outer_limits_cannot_undercut_agent_budget() -> None:
    assert remote_command_timeout(1800) == 1980
    assert sandbox_ttl_minutes(600, 7200, minimum_minutes=30) == 145
