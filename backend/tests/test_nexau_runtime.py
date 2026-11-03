"""spec-0003/T2: nexau_runtime.load / Agent.run unit tests (mock backend, no dependency on real nexau)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ahe_beta.nexau_runtime import Agent, load


def test_agent_run_passes_through_to_backend() -> None:
    seen: dict[str, str] = {}

    def backend(prompt: str, user_input: str) -> str:
        seen["prompt"] = prompt
        seen["input"] = user_input
        return "Model output"

    agent = Agent(prompt="System prompt", backend=backend)
    assert agent.run("Hello") == "Model output"
    assert seen == {"prompt": "System prompt", "input": "Hello"}


def test_agent_run_propagates_backend_error() -> None:
    def boom(prompt: str, user_input: str) -> str:
        raise RuntimeError("nexau Call failed")

    with pytest.raises(RuntimeError):
        Agent(prompt="p", backend=boom).run("x")


def test_load_reads_prompt_and_builds_agent(tmp_path) -> None:
    role = tmp_path / "user_agent"
    role.mkdir()
    (role / "prompt.md").write_text("I am the role definition", encoding="utf-8")
    agent = load(str(role))
    assert isinstance(agent, Agent)
    assert agent.prompt == "I am the role definition"


def test_load_missing_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load(str(tmp_path / "nope"))


def test_load_missing_prompt_raises(tmp_path) -> None:
    role = tmp_path / "role"
    role.mkdir()  # Directory exists but prompt.md missing
    with pytest.raises(FileNotFoundError):
        load(str(role))


def test_shipped_user_agent_def_loads() -> None:
    root = Path(__file__).resolve().parents[1] / "agent_defs" / "user_agent"
    agent = load(str(root))
    assert "# Role: User Simulator" in agent.prompt
