"""spec-0003/T2：nexau_runtime.load / Agent.run 单测（mock 后端，不依赖真 nexau）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_designer.nexau_runtime import Agent, load


def test_agent_run_passes_through_to_backend() -> None:
    seen: dict[str, str] = {}

    def backend(prompt: str, user_input: str) -> str:
        seen["prompt"] = prompt
        seen["input"] = user_input
        return "模型输出"

    agent = Agent(prompt="系统提示", backend=backend)
    assert agent.run("你好") == "模型输出"
    assert seen == {"prompt": "系统提示", "input": "你好"}


def test_agent_run_propagates_backend_error() -> None:
    def boom(prompt: str, user_input: str) -> str:
        raise RuntimeError("nexau 调用失败")

    with pytest.raises(RuntimeError):
        Agent(prompt="p", backend=boom).run("x")


def test_load_reads_prompt_and_builds_agent(tmp_path) -> None:
    role = tmp_path / "user_agent"
    role.mkdir()
    (role / "prompt.md").write_text("我是角色定义", encoding="utf-8")
    agent = load(str(role))
    assert isinstance(agent, Agent)
    assert agent.prompt == "我是角色定义"


def test_load_missing_dir_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load(str(tmp_path / "nope"))


def test_load_missing_prompt_raises(tmp_path) -> None:
    role = tmp_path / "role"
    role.mkdir()  # 目录在但缺 prompt.md
    with pytest.raises(FileNotFoundError):
        load(str(role))


def test_shipped_user_agent_def_loads() -> None:
    root = Path(__file__).resolve().parents[1] / "agent_defs" / "user_agent"
    agent = load(str(root))
    assert "User Simulator（用户模拟）" in agent.prompt
