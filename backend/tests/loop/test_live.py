"""多 agent 活动注册表单测：update/read/clear + 分组排序 + 缺省态。"""

from __future__ import annotations

from pathlib import Path

from auto_designer.loop.live import append_agent_log, clear_agents, read_agents, update_agent


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


def test_started_at_preserved_while_running_reset_on_new_activity(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="1")
    start1 = read_agents(data_dir=tmp_path)[0]["started_at"]
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="2")
    assert read_agents(data_dir=tmp_path)[0]["started_at"] == start1  # 持续中沿用
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=False, status="完"
    )
    assert read_agents(data_dir=tmp_path)[0]["started_at"] == start1  # 收尾仍沿用，供算总时长
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="3")
    assert read_agents(data_dir=tmp_path)[0]["started_at"] >= start1  # 新一段活动重置


def test_log_accumulates_status_timeline_with_dedup(tmp_path: Path) -> None:
    """status 变化追加进 log（工作过程时间线），连续重复去重——dev/designer 无 turns 靠它展示过程。"""
    for status in ["领取 issue #12", "改 main + 直推中…", "改 main + 直推中…", "已推进 main v3"]:
        update_agent(
            data_dir=tmp_path,
            agent_id="d",
            role="developer",
            label="dev#1",
            running=True,
            status=status,
        )
    (agent,) = read_agents(data_dir=tmp_path)
    assert [e["text"] for e in agent["log"]] == [
        "领取 issue #12",
        "改 main + 直推中…",
        "已推进 main v3",
    ]
    assert all(e["t"] for e in agent["log"])  # 每条带时间戳


def test_append_agent_log_adds_steps_without_touching_status(tmp_path: Path) -> None:
    """逐步过程（工具调用）追加进 log，status/turns 不动；槽不存在 no-op；连续重复去重。"""
    append_agent_log(data_dir=tmp_path, agent_id="ghost", text="孤儿步骤")  # 无槽 → no-op 不建槽
    assert read_agents(data_dir=tmp_path) == []

    update_agent(
        data_dir=tmp_path,
        agent_id="d",
        role="developer",
        label="dev#1",
        running=True,
        status="改 main 中…",
    )
    append_agent_log(data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main")
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main"
    )  # 去重
    append_agent_log(data_dir=tmp_path, agent_id="d", text="🔧 edit_file: agents/main.md")
    (agent,) = read_agents(data_dir=tmp_path)
    assert agent["status"] == "改 main 中…"
    assert [e["text"] for e in agent["log"]] == [
        "改 main 中…",
        "🔧 run_shell: git checkout main",
        "🔧 edit_file: agents/main.md",
    ]


def test_step_tracer_emits_tool_steps() -> None:
    """StepTracer：TOOL span start → 🔧 步骤；失败 end → ❌ 步骤；LLM span 不吐。"""
    from nexau import SpanType

    from auto_designer.loop.live_tracer import StepTracer

    steps: list[str] = []
    tracer = StepTracer(steps.append)
    span = tracer.start_span(
        "Tool: run_shell", SpanType.TOOL, inputs={"parameters": {"command": "git push origin main"}}
    )
    tracer.end_span(span)  # 正常结束不重复吐
    tracer.start_span("Anthropic messages.create", SpanType.LLM, inputs={})
    failed = tracer.start_span(
        "Tool: edit_file", SpanType.TOOL, inputs={"parameters": {"path": "x"}}
    )
    tracer.end_span(failed, error=RuntimeError("boom"))
    assert steps == [
        "🔧 run_shell: git push origin main",
        '🔧 edit_file: {"path": "x"}',
        "❌ edit_file: boom",
    ]


def test_clear_removes_all(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="x")
    clear_agents(data_dir=tmp_path)
    clear_agents(data_dir=tmp_path)  # 幂等
    assert read_agents(data_dir=tmp_path) == []
