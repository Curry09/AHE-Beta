"""Multi-agent activity registry unit tests: update/read/clear + grouping sort + run.json + per-round archive + process flow tracer."""

from __future__ import annotations

from pathlib import Path

import pytest

from ahe_beta.loop.live import (
    append_agent_log,
    archive_agent,
    clear_live,
    prepare_live_resume,
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
        label="Independent developer",
        running=True,
        status="harness Replying…",
        turns=[{"role": "user", "content": "hi"}],
        round_no=1,
    )
    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="Advanced main v1",
        detail="Rewrite preview",
    )
    agents = read_agents(data_dir=tmp_path)
    assert [a["agent_id"] for a in agents] == ["user-A", "dev-0"]  # user first
    assert agents[0]["running"] is True and agents[0]["turns"][0]["content"] == "hi"
    assert agents[0]["round"] == 1
    assert agents[1]["role"] == "developer" and agents[1]["detail"] == "Rewrite preview"


def test_round_preserved_when_not_passed(tmp_path: Path) -> None:
    """When round_no is not passed, reuse existing value in slot (no need to carry round each time when updating intermediate state per round)."""
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
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="run"
    )
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=False, status="Done"
    )
    agents = read_agents(data_dir=tmp_path)
    assert len(agents) == 1 and agents[0]["running"] is False and agents[0]["status"] == "Done"


def test_started_at_preserved_while_running_reset_on_new_activity(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="1")
    start1 = read_agents(data_dir=tmp_path)[0]["started_at"]
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="2")
    assert read_agents(data_dir=tmp_path)[0]["started_at"] == start1  # Reuse during ongoing
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=False, status="Done"
    )
    # Reuse on completion, for total duration calculation
    assert read_agents(data_dir=tmp_path)[0]["started_at"] == start1
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="3")
    # Reset on new activity segment
    assert read_agents(data_dir=tmp_path)[0]["started_at"] >= start1


def test_log_accumulates_status_timeline_with_dedup(tmp_path: Path) -> None:
    """status change appended to log (kind=status), consecutive duplicates deduplicated."""
    for status in [
        "Claim issue #12",
        "Edit main + Direct push in progress…",
        "Edit main + Direct push in progress…",
        "Advanced main v3",
    ]:
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
        "Claim issue #12",
        "Edit main + Direct push in progress…",
        "Advanced main v3",
    ]
    assert all(e["t"] and e["kind"] == "status" for e in agent["log"])


def test_append_agent_log_adds_typed_steps_without_touching_status(tmp_path: Path) -> None:
    """Process flow events (assistant/tool call/result) appended to log with kind, status/turns unchanged;
    no-op if slot does not exist; consecutive duplicates deduplicated."""
    # No slot → no-op, do not create slot
    append_agent_log(data_dir=tmp_path, agent_id="ghost", text="Orphan step")
    assert read_agents(data_dir=tmp_path) == []

    update_agent(
        data_dir=tmp_path,
        agent_id="d",
        role="developer",
        label="dev#1",
        running=True,
        status="Edit main In progress…",
    )
    append_agent_log(
        data_dir=tmp_path,
        agent_id="d",
        text="Take a look first issue Files involved",
        kind="assistant",
    )
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main", kind="tool"
    )
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="🔧 run_shell: git checkout main", kind="tool"
    )  # Deduplicate
    append_agent_log(
        data_dir=tmp_path, agent_id="d", text="Switched to branch 'main'", kind="tool_result"
    )
    (agent,) = read_agents(data_dir=tmp_path)
    assert agent["status"] == "Edit main In progress…"
    assert [(e["kind"], e["text"]) for e in agent["log"]] == [
        ("status", "Edit main In progress…"),
        ("assistant", "Take a look first issue Files involved"),
        ("tool", "🔧 run_shell: git checkout main"),
        ("tool_result", "Switched to branch 'main'"),
    ]


def test_live_run_roundtrip_and_defaults(tmp_path: Path) -> None:
    """run.json: not yet run gives static default; readable after update; round_shas reused if not passed."""
    state = read_live_run(data_dir=tmp_path)
    assert state["running"] is False and state["round"] == 0 and state["round_shas"] == []

    update_live_run(data_dir=tmp_path, running=True, round_no=1, total_rounds=5)
    update_live_run(
        data_dir=tmp_path, running=True, round_no=1, total_rounds=5, round_shas=["abc1234"]
    )
    update_live_run(data_dir=tmp_path, running=True, round_no=2, total_rounds=5)  # Reuse shas
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
    """Archive = slot snapshot + extra; no-op if slot does not exist; append-only accumulation across rounds."""
    archive_agent(data_dir=tmp_path, agent_id="ghost", round_no=1, extra={"kind": "dev_run"})
    assert read_history(data_dir=tmp_path) == []

    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="Advanced main v1",
        detail="Full report text",
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
        status="Completed · Perceived experience 4",
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
    # Slot process flow fully included in snapshot
    assert dev["detail"] == "Full report text" and dev["log"]
    assert user["kind"] == "user_session" and user["session_id"] == "s-1"
    assert user["turns"] == [{"role": "user", "content": "hi"}]
    assert all(r["archived_at"] for r in history)


def test_step_tracer_emits_process_stream() -> None:
    """StepTracer：TOOL start → tool；TOOL end → tool_result/tool_error；LLM end → assistant。"""
    pytest.importorskip("nexau")
    from nexau import SpanType

    from ahe_beta.loop.live_tracer import StepTracer

    events: list[tuple[str, str]] = []
    tracer = StepTracer(lambda kind, text: events.append((kind, text)))

    span = tracer.start_span(
        "Tool: run_shell", SpanType.TOOL, inputs={"parameters": {"command": "git push origin main"}}
    )
    tracer.end_span(span, outputs="Everything up-to-date")
    # LLM: OpenAI complete response form
    llm = tracer.start_span("OpenAI chat.completions.create", SpanType.LLM, inputs={})
    tracer.end_span(
        llm,
        outputs={"choices": [{"message": {"content": "I will make the changes first main.md"}}]},
    )
    # LLM: streaming aggregated payload form
    llm2 = tracer.start_span("OpenAI chat.completions.create (stream)", SpanType.LLM, inputs={})
    tracer.end_span(
        llm2, outputs={"role": "assistant", "content": "Changes complete，Prepare commit"}
    )
    # LLM: Anthropic content blocks form
    llm3 = tracer.start_span("Anthropic messages.create", SpanType.LLM, inputs={})
    tracer.end_span(
        llm3, outputs={"content": [{"type": "text", "text": "Push tag"}, {"type": "tool_use"}]}
    )
    # LLM: text not extractable (pure tool_calls) → no output
    llm4 = tracer.start_span("OpenAI chat.completions.create", SpanType.LLM, inputs={})
    tracer.end_span(llm4, outputs={"choices": [{"message": {"content": None}}]})
    failed = tracer.start_span(
        "Tool: edit_file", SpanType.TOOL, inputs={"parameters": {"path": "x"}}
    )
    tracer.end_span(failed, error=RuntimeError("boom"))

    assert events == [
        ("tool", "🔧 run_shell: git push origin main"),
        ("tool_result", "Everything up-to-date"),
        ("assistant", "I will make the changes first main.md"),
        ("assistant", "Changes complete，Prepare commit"),
        ("assistant", "Push tag"),
        ("tool", '🔧 edit_file: {"path": "x"}'),
        ("tool_error", "❌ edit_file: boom"),
    ]


def test_concurrent_update_agent_keeps_all_slots(tmp_path: Path) -> None:
    """Spec-0017/T1 race condition regression: concurrent upsert of different agent_id, no slot lost.

    Before locking, agents.json is lock-free read-modify-write (mkstemp atomic write only prevents torn write), concurrent upsert
    based on same old snapshot mutually overwrite entire registry (lose others' slots). Barrier volley forces interleaving.
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
            status=f"Run round {i} round",
            round_no=1,
        )

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(upsert, range(n)))

    agents = read_agents(data_dir=tmp_path)
    # Complete and ordered across all slots
    assert [a["agent_id"] for a in agents] == [f"user-{i:02d}" for i in range(n)]


def test_concurrent_append_log_and_archive_lose_nothing(tmp_path: Path) -> None:
    """Spec-0017/T1: Concurrent append_agent_log does not lose lines; concurrent archive_agent does not lose archive entries."""
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
            append_agent_log(data_dir=tmp_path, agent_id=f"a{i}", text=f"a{i} Steps {k}")

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(log_steps, range(n)))
    for i, agent in enumerate(read_agents(data_dir=tmp_path)):
        steps = [e["text"] for e in agent["log"] if e["kind"] == "step"]
        # 10 lines per slot, all present and ordered
        assert steps == [f"a{i} Steps {k}" for k in range(10)]

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
    assert len(history) == n  # Append-only concurrent archiving does not lose entries
    assert {h["session_id"] for h in history} == {f"s-{i}" for i in range(n)}


def test_clear_removes_all(tmp_path: Path) -> None:
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="x")
    update_live_run(data_dir=tmp_path, running=True, round_no=1, total_rounds=5)
    archive_agent(data_dir=tmp_path, agent_id="u", round_no=1, extra={"kind": "user_session"})
    clear_live(data_dir=tmp_path)
    clear_live(data_dir=tmp_path)  # Idempotent
    assert read_agents(data_dir=tmp_path) == []
    assert read_history(data_dir=tmp_path) == []
    assert read_live_run(data_dir=tmp_path)["running"] is False


def test_prepare_resume_preserves_history_and_marks_stale_slots(tmp_path: Path) -> None:
    update_agent(
        data_dir=tmp_path,
        agent_id="u",
        role="user",
        label="U",
        running=True,
        status="Calling model",
        round_no=2,
    )
    archive_agent(
        data_dir=tmp_path,
        agent_id="u",
        round_no=1,
        extra={"kind": "user_session", "session_id": "done"},
    )
    update_live_run(data_dir=tmp_path, running=True, round_no=2, total_rounds=3)

    prepare_live_resume(data_dir=tmp_path, phase="architect")

    assert read_history(data_dir=tmp_path)[0]["session_id"] == "done"
    assert read_agents(data_dir=tmp_path)[0]["running"] is False
    assert "waiting for recovery" in read_agents(data_dir=tmp_path)[0]["status"]
    assert read_live_run(data_dir=tmp_path)["phase"] == "recovering:architect"


def test_triager_sorts_between_user_and_architect(tmp_path: Path) -> None:
    # Spec-0026/T1: read_agents sorts by _ROLE_ORDER, with triager positioned between user and architect.
    for role in ("developer", "architect", "triager", "user"):
        update_agent(
            data_dir=tmp_path, agent_id=role, role=role, label=role, running=True, status="x"
        )
    order = [a["role"] for a in read_agents(data_dir=tmp_path)]
    assert order == ["user", "triager", "architect", "developer"]


def test_meta_passthrough_and_sticky(tmp_path: Path) -> None:
    # Spec-0026/T1: meta is read-through only; when not provided, reuse the previous value (sticky); old callers that do not pass meta degrade to None without crashing.
    meta = {
        "identity": "SR-001",
        "level": "expert",
        "domain": "data-eng",
        "goal": "Create a repository",
    }
    update_agent(
        data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="1", meta=meta
    )
    assert read_agents(data_dir=tmp_path)[0]["meta"] == meta
    # Omit meta → reuse previous value
    update_agent(data_dir=tmp_path, agent_id="u", role="user", label="l", running=True, status="2")
    assert read_agents(data_dir=tmp_path)[0]["meta"] == meta
    # Agent that never passes meta → None, does not crash
    update_agent(
        data_dir=tmp_path, agent_id="d", role="developer", label="l", running=True, status="x"
    )
    assert read_agents(data_dir=tmp_path)[1]["meta"] is None
