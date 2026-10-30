"""Spec-0084/T3: task clocks, immutable conditions and real SDK capacity failures."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time

import httpx
import pytest
from test_seed_terminal_status import runtime as runtime
from test_seed_terminal_status import tool_reply


def frame(**changes):
    return {
        "type": "message",
        "text": "Finish the task",
        "task_id": "task-1",
        "message_id": "m-1",
        "contract_id": "a" * 64,
        "followup_input": "unavailable",
        "task_budget_seconds": 7200,
        "remaining_budget_seconds": 7200,
        "budget_source": "task_metadata",
        **changes,
    }


def test_enqueue_anchors_deadline_and_queue_followup_never_refunds(runtime):
    entry, *_ = runtime
    now = [100.0]
    frames = entry._TaskFrames(clock=lambda: now[0])
    first = frames.accept(frame())
    assert frames.deadline == 7300
    now[0] = 3000
    second = frames.accept(frame(message_id="m-2", remaining_budget_seconds=7200))
    assert frames.limit(first)[0] == frames.limit(second)[0] == 7300
    now[0] = 7400
    assert frames.limit(second)[0] < now[0]


def test_followup_can_only_shorten_deadline(runtime):
    entry, *_ = runtime
    now = [100.0]
    frames = entry._TaskFrames(clock=lambda: now[0])
    frames.accept(frame())
    now[0] = 200
    second = frames.accept(frame(message_id="m-2", remaining_budget_seconds=1000))
    assert frames.limit(second) == (1200, "task_budget_exhausted")


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": "other"},
        {"message_id": "m-1"},
        {"contract_id": "b" * 64},
        {"remaining_budget_seconds": 7201},
        {"remaining_budget_seconds": -1},
        {"remaining_budget_seconds": True},
        {"remaining_budget_seconds": None},
        {"followup_input": "always"},
        {"followup_input": []},
        {"message_id": []},
        {"remaining_budget_seconds": 1, "message_activity_seconds": -1},
    ],
)
def test_invalid_or_changed_frames_cannot_replace_active_task(runtime, changes):
    entry, *_ = runtime
    frames = entry._TaskFrames(clock=lambda: 100)
    frames.accept(frame())
    with pytest.raises(ValueError):
        frames.accept(
            frame(message_id="m-2", **changes) if "message_id" not in changes else frame(**changes)
        )
    assert frames.deadline == 7300


def test_manual_unknown_conditions_have_no_assumed_task_timeout(runtime):
    entry, *_ = runtime
    frames = entry._TaskFrames(clock=lambda: 100)
    item = frames.accept({"type": "message", "text": "Do useful work"})
    assert frames.limit(item) == (None, None)
    assert item["message_id"] and item["task_id"]


def test_builtin_first_does_not_start_clock_or_complete_task(runtime):
    entry, *_ = runtime
    frames = entry._TaskFrames(clock=lambda: 100)
    item = frames.accept(frame(text="/help"))
    assert frames.limit(item) == (None, None)
    later = frames.accept(frame(message_id="m-2"))
    assert frames.limit(later) == (7300, "task_budget_exhausted")


def test_expired_queued_goal_never_calls_agent(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [tool_reply("complete_task", {"result": "should not run"})]
    agent = entry._build_agent(None, "expired-session", "expired-agent")
    _, _, status = entry._reply(
        agent,
        "goal",
        lambda old: old,
        deadline=lambda: (time.monotonic() - 1, "task_budget_exhausted"),
    )
    assert status == "incomplete"
    assert agent._harness_termination_reason == "task_budget_exhausted"
    assert requests == []


@pytest.mark.parametrize("startup_delay", [0, 0.3])
def test_budget_cancels_native_async_model_without_new_solving_in_grace(
    runtime, monkeypatch, startup_delay
):
    entry, requests, replies, _ = runtime
    cancelled = threading.Event()
    model_limit = None

    async def blocked(request):
        nonlocal model_limit
        model_limit = time.monotonic() + 0.2
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    replies[:] = [blocked]
    agent = entry._build_agent(None, "budget-session", "budget-agent")
    native_run = agent.run

    def run_with_startup_delay(**kwargs):
        # The fixture replaces time.sleep globally; Event.wait retains a real
        # delay and proves cancellation is independent of cold SDK startup.
        threading.Event().wait(startup_delay)
        return native_run(**kwargs)

    monkeypatch.setattr(agent, "run", run_with_startup_delay)
    startup_limit = time.monotonic() + 10

    def deadline():
        # This case tests an in-flight native async request. The separate queued
        # expiry case covers a budget that runs out before a request begins.
        if model_limit is None:
            return startup_limit, "test_model_startup_timeout"
        return model_limit, "task_budget_exhausted"

    same, _, status = entry._reply(
        agent,
        "goal",
        lambda old: pytest.fail("unneeded rebuild"),
        deadline=deadline,
    )
    assert same is agent and status == "incomplete"
    assert agent._harness_termination_reason == "task_budget_exhausted"
    assert cancelled.is_set() and len(requests) == 1


def test_deterministic_context_overflow_does_not_repeat_outer_agent_run(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [
        httpx.Response(
            400,
            json={
                "error": {
                    "code": "context_length_exceeded",
                    "message": "maximum context length exceeded",
                    "type": "invalid_request_error",
                }
            },
        )
    ]
    agent = entry._build_agent(None, "overflow-session", "overflow-agent")
    agent.executor.llm_caller.retry_attempts = 1
    _, text, status = entry._reply(agent, "goal", lambda old: old)
    assert status == "incomplete" and "context_overflow" in text
    assert agent._harness_termination_reason == "context_overflow"
    assert len(requests) == 1  # SDK retries explicitly disabled in this test.


def test_main_preserves_ids_and_runtime_conditions_without_editing_task(
    runtime, monkeypatch, capsys
):
    entry, requests, replies, _ = runtime
    replies[:] = [tool_reply("complete_task", {"result": "Done"})]
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps(frame()) + "\n"))
    entry.main()
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    terminal = next(row for row in output if row["type"] == "reply")
    assert (terminal["task_id"], terminal["message_id"], terminal["status"]) == (
        "task-1",
        "m-1",
        "completed",
    )
    assert "followup_input=unavailable" in requests[0]["messages"][0]["content"]
    assert requests[0]["messages"][1]["content"] == "Finish the task"


def test_seed_uses_explicit_input_threshold_and_keeps_output_allowance(runtime, monkeypatch):
    entry, requests, replies, _ = runtime
    monkeypatch.setenv("LLM_MAX_CONTEXT_TOKENS", "229376")
    replies[:] = [tool_reply("complete_task", {"result": "Done"})]
    agent = entry._build_agent(None, "limits-session", "limits-agent")
    assert agent.config.max_context_tokens == 229376
    entry._reply(agent, "goal", lambda old: old)
    assert requests[0]["max_tokens"] == 32768
