"""多 agent 活动注册表单测：update/read/clear + 分组排序 + 缺省态。"""

from __future__ import annotations

from pathlib import Path

from auto_designer.loop.live import clear_agents, read_agents, update_agent


def test_read_empty_is_empty_list(tmp_path: Path) -> None:
    assert read_agents(data_dir=tmp_path) == []


def test_update_upserts_and_keeps_separate_slots(tmp_path: Path) -> None:
    update_agent(
        data_dir=tmp_path,
        agent_id="user-A",
        role="user",
        label="独立开发者",
        running=True,
        status="harness 回复中…",
        turns=[{"role": "user", "content": "hi"}],
    )
    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="已提交 fix/issue-1",
        detail="改写预览",
    )
    agents = read_agents(data_dir=tmp_path)
    assert [a["agent_id"] for a in agents] == ["user-A", "dev-0"]  # user 在前
    assert agents[0]["running"] is True and agents[0]["turns"][0]["content"] == "hi"
    assert agents[1]["role"] == "developer" and agents[1]["detail"] == "改写预览"


def test_update_same_id_overwrites_in_place(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="跑")
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=False, status="完"
    )
    agents = read_agents(data_dir=tmp_path)
    assert len(agents) == 1 and agents[0]["running"] is False and agents[0]["status"] == "完"


def test_clear_removes_all(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="x")
    clear_agents(data_dir=tmp_path)
    clear_agents(data_dir=tmp_path)  # 幂等
    assert read_agents(data_dir=tmp_path) == []
