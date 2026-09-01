"""多 agent 活动注册表单测：update/read/clear + 分组排序 + run.json + 按轮归档 + 过程流 tracer。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_designer.loop.live import (
    append_agent_log,
    archive_agent,
    clear_live,
    read_agents,
    read_history,
    read_live_run,
    update_agent,
    update_live_run,
)


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
        round_no=1,
    )
    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="已推进 main v1",
        detail="改写预览",
    )
    agents = read_agents(data_dir=tmp_path)
    assert [a["agent_id"] for a in agents] == ["user-A", "dev-0"]  # user 在前
    assert agents[0]["running"] is True and agents[0]["turns"][0]["content"] == "hi"
    assert agents[0]["round"] == 1
    assert agents[1]["role"] == "developer" and agents[1]["detail"] == "改写预览"


def test_round_preserved_when_not_passed(tmp_path: Path) -> None:
    """round_no 不传时沿用槽内已有值（逐轮更新中间态时不必每次带 round）。"""
    update_agent(
        data_dir=tmp_path,
        agent_id="u",
        role="user",
        label="l",
        running=True,
        status="1",
        round_no=2,
    )
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="2")
    assert read_agents(data_dir=tmp_path)[0]["round"] == 2


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
    """status 变化追加进 log（kind=status），连续重复去重。"""
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
    assert all(e["t"] and e["kind"] == "status" for e in agent["log"])


def test_append_agent_log_adds_typed_steps_without_touching_status(tmp_path: Path) -> None:
    """过程流事件（assistant/工具调用/结果）带 kind 追加进 log，status/turns 不动；
    槽不存在 no-op；连续重复去重。"""
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
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="先看看 issue 涉及的文件", kind="assistant"
    )
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main", kind="tool"
    )
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main", kind="tool"
    )  # 去重
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="Switched to branch 'main'", kind="tool_result"
    )
    (agent,) = read_agents(data_dir=tmp_path)
    assert agent["status"] == "改 main 中…"
    assert [(e["kind"], e["text"]) for e in agent["log"]] == [
        ("status", "改 main 中…"),
        ("assistant", "先看看 issue 涉及的文件"),
        ("tool", "🔧 run_shell: git checkout main"),
        ("tool_result", "Switched to branch 'main'"),
    ]


def test_live_run_roundtrip_and_defaults(tmp_path: Path) -> None:
    """run.json：未跑过给静止缺省；update 后可读回；round_shas 不传沿用。"""
    state = read_live_run(data_dir=tmp_path)
    assert state["running"] is False and state["round"] == 0 and state["round_shas"] == []

    update_live_run(data_dir=tmp_path, running=True, round_no=1, total_rounds=5)
    update_live_run(
        data_dir=tmp_path, running=True, round_no=1, total_rounds=5, round_shas=["abc1234"]
    )
    update_live_run(data_dir=tmp_path, running=True, round_no=2, total_rounds=5)  # 沿用 shas
    state = read_live_run(data_dir=tmp_path)
    assert state["running"] is True and state["round"] == 2 and state["total_rounds"] == 5
    assert state["round_shas"] == ["abc1234"]
    assert state["started_at"] and state["updated_at"]

    update_live_run(
        data_dir=tmp_path,
        running=False,
        round_no=1,
        total_rounds=5,
        phase="blocked",
        blocked_issues=[7],
    )
    blocked = read_live_run(data_dir=tmp_path)
    assert blocked["phase"] == "blocked" and blocked["blocked_issues"] == [7]

    update_live_run(data_dir=tmp_path, running=False, round_no=5, total_rounds=5)
    assert read_live_run(data_dir=tmp_path)["running"] is False


def test_archive_agent_snapshots_slot_per_round(tmp_path: Path) -> None:
    """归档 = 槽位快照 + extra；槽不存在 no-op；append-only 跨轮累计。"""
    archive_agent(data_dir=tmp_path, agent_id="ghost", round_no=1, extra={"kind": "dev_run"})
    assert read_history(data_dir=tmp_path) == []

    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="已推进 main v1",
        detail="完整报告全文",
        round_no=1,
    )
    archive_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        round_no=1,
        extra={"kind": "dev_run", "issue_number": 3, "tag": "v1", "committed": True},
    )
    update_agent(
        data_dir=tmp_path,
        agent_id="user-A",
        role="user",
        label="A",
        running=False,
        status="已完成 · 体感 4",
        turns=[{"role": "user", "content": "hi"}],
        round_no=2,
    )
    archive_agent(
        data_dir=tmp_path,
        agent_id="user-A",
        round_no=2,
        extra={"kind": "user_session", "session_id": "s-1", "score": 4},
    )
    history = read_history(data_dir=tmp_path)
    assert len(history) == 2
    dev, user = history
    assert dev["kind"] == "dev_run" and dev["round"] == 1 and dev["issue_number"] == 3
    assert dev["detail"] == "完整报告全文" and dev["log"]  # 槽位过程流全量随快照
    assert user["kind"] == "user_session" and user["session_id"] == "s-1"
    assert user["turns"] == [{"role": "user", "content": "hi"}]
    assert all(r["archived_at"] for r in history)


def test_step_tracer_emits_process_stream() -> None:
    """StepTracer：TOOL start → tool；TOOL end → tool_result/tool_error；LLM end → assistant。"""
    pytest.importorskip("nexau")
    from nexau import SpanType

    from auto_designer.loop.live_tracer import StepTracer

    events: list[tuple[str, str]] = []
    tracer = StepTracer(lambda kind, text: events.append((kind, text)))

    span = tracer.start_span(
        "Tool: run_shell", SpanType.TOOL, inputs={"parameters": {"command": "git push origin main"}}
    )
    tracer.end_span(span, outputs="Everything up-to-date")
    # LLM：OpenAI 完整响应形态
    llm = tracer.start_span("OpenAI chat.completions.create", SpanType.LLM, inputs={})
    tracer.end_span(llm, outputs={"choices": [{"message": {"content": "我先改 main.md"}}]})
    # LLM：流式聚合 payload 形态
    llm2 = tracer.start_span("OpenAI chat.completions.create (stream)", SpanType.LLM, inputs={})
    tracer.end_span(llm2, outputs={"role": "assistant", "content": "改完了，准备 commit"})
    # LLM：Anthropic content blocks 形态
    llm3 = tracer.start_span("Anthropic messages.create", SpanType.LLM, inputs={})
    tracer.end_span(
        llm3, outputs={"content": [{"type": "text", "text": "推送 tag"}, {"type": "tool_use"}]}
    )
    # LLM：提取不到文本（纯 tool_calls）→ 不吐
    llm4 = tracer.start_span("OpenAI chat.completions.create", SpanType.LLM, inputs={})
    tracer.end_span(llm4, outputs={"choices": [{"message": {"content": None}}]})
    failed = tracer.start_span(
        "Tool: edit_file", SpanType.TOOL, inputs={"parameters": {"path": "x"}}
    )
    tracer.end_span(failed, error=RuntimeError("boom"))

    assert events == [
        ("tool", "🔧 run_shell: git push origin main"),
        ("tool_result", "Everything up-to-date"),
        ("assistant", "我先改 main.md"),
        ("assistant", "改完了，准备 commit"),
        ("assistant", "推送 tag"),
        ("tool", '🔧 edit_file: {"path": "x"}'),
        ("tool_error", "❌ edit_file: boom"),
    ]


def test_concurrent_update_agent_keeps_all_slots(tmp_path: Path) -> None:
    """Spec-0017/T1 竞态回归：并发 upsert 不同 agent_id，槽位一个不丢。

    加锁前 agents.json 是无锁读-改-写（mkstemp 原子写只防撕裂写），并发 upsert 会基于
    同一旧快照互相覆盖整个 registry（丢别人的槽）。屏障齐射逼出交错。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    n = 12
    barrier = threading.Barrier(n)

    def upsert(i: int) -> None:
        barrier.wait()
        update_agent(
            data_dir=tmp_path,
            agent_id=f"user-{i:02d}",
            role="user",
            label=f"U{i}",
            running=True,
            status=f"跑第 {i} 局",
            round_no=1,
        )

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(upsert, range(n)))

    agents = read_agents(data_dir=tmp_path)
    assert [a["agent_id"] for a in agents] == [f"user-{i:02d}" for i in range(n)]  # 全在且有序


def test_concurrent_append_log_and_archive_lose_nothing(tmp_path: Path) -> None:
    """Spec-0017/T1：并发 append_agent_log 不丢行；并发 archive_agent 不丢归档条目。"""
    from concurrent.futures import ThreadPoolExecutor

    n = 8
    for i in range(n):
        update_agent(
            data_dir=tmp_path,
            agent_id=f"a{i}",
            role="user",
            label=f"A{i}",
            running=True,
            status="s",
            round_no=1,
        )

    def log_steps(i: int) -> None:
        for k in range(10):
            append_agent_log(data_dir=tmp_path, agent_id=f"a{i}", text=f"a{i} 步骤 {k}")

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(log_steps, range(n)))
    for i, agent in enumerate(read_agents(data_dir=tmp_path)):
        steps = [e["text"] for e in agent["log"] if e["kind"] == "step"]
        assert steps == [f"a{i} 步骤 {k}" for k in range(10)]  # 每槽 10 行按序全在

    def archive(i: int) -> None:
        archive_agent(
            data_dir=tmp_path,
            agent_id=f"a{i}",
            round_no=1,
            extra={"kind": "user_session", "session_id": f"s-{i}"},
        )

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(archive, range(n)))
    history = read_history(data_dir=tmp_path)
    assert len(history) == n  # append-only 并发归档不丢
    assert {h["session_id"] for h in history} == {f"s-{i}" for i in range(n)}


def test_clear_removes_all(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="x")
    update_live_run(data_dir=tmp_path, running=True, round_no=1, total_rounds=5)
    archive_agent(data_dir=tmp_path, agent_id="u", round_no=1, extra={"kind": "user_session"})
    clear_live(data_dir=tmp_path)
    clear_live(data_dir=tmp_path)  # 幂等
    assert read_agents(data_dir=tmp_path) == []
    assert read_history(data_dir=tmp_path) == []
    assert read_live_run(data_dir=tmp_path)["running"] is False


def test_triager_sorts_between_user_and_designer(tmp_path: Path) -> None:
    # Spec-0026/T1：read_agents 按 _ROLE_ORDER 排序，triager 介于 user 与 designer 之间。
    for role in ("developer", "designer", "triager", "user"):
        update_agent(
            data_dir=tmp_path, agent_id=role, role=role, label=role, running=True, status="x"
        )
    order = [a["role"] for a in read_agents(data_dir=tmp_path)]
    assert order == ["user", "triager", "designer", "developer"]


def test_meta_passthrough_and_sticky(tmp_path: Path) -> None:
    # Spec-0026/T1：meta 只读透传；不传时沿用上一次（sticky）；老调用不传退化为 None 不崩。
    meta = {"identity": "SR-001", "level": "expert", "domain": "data-eng", "goal": "建个库"}
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="1", meta=meta
    )
    assert read_agents(data_dir=tmp_path)[0]["meta"] == meta
    # 不传 meta -> 沿用上一次
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="2")
    assert read_agents(data_dir=tmp_path)[0]["meta"] == meta
    # 从不传 meta 的 agent -> None，不崩
    update_agent(
        data_dir=tmp_path, agent_id="d", role="developer", label="l", running=True, status="x"
    )
    assert read_agents(data_dir=tmp_path)[1]["meta"] is None
