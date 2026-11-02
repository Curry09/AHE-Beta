"""Spec-0084/T3: process identity and one authoritative task budget."""

from __future__ import annotations

import pytest
from test_launcher import _COUNTER_ENTRY, _launcher

from ahe_beta.execution_contract import make_execution_contract
from ahe_beta.harness import launcher
from ahe_beta.harness.budget import TaskBudget


def contract(seconds=7200):
    return make_execution_contract(
        session_id="s-1",
        task_id="task-1",
        task_digest="a" * 64,
        followup_input="unavailable",
        task_budget_seconds=seconds,
        budget_source="task_metadata",
    )


@pytest.fixture
def handle(tmp_path, monkeypatch):
    h = _launcher(tmp_path, _COUNTER_ENTRY).launch("main")
    sent = []
    monkeypatch.setattr(h, "_write", sent.append)
    yield h, sent
    h.close()


def test_task_budget_starts_once_and_no_followup_refund():
    now = [10.0]
    budget = TaskBudget(7200, clock=lambda: now[0])
    assert budget.remaining() == 7200
    budget.start()
    now[0] = 1800
    budget.start()
    assert budget.deadline == 7210
    assert budget.remaining() == 5410


def test_7200_contract_overrides_short_runtime_fallback_and_keeps_identity(handle):
    h, sent = handle
    h.bind_execution_contract(contract())
    h.write_message("goal")
    first_deadline = h._task_budget.deadline
    h.write_message("more facts")
    assert h.request_budget_seconds == 7200
    assert h._limits.outer_seconds == 7260
    assert h._task_budget.deadline == first_deadline
    assert sent[1]["remaining_budget_seconds"] <= sent[0]["remaining_budget_seconds"]
    assert sent[0]["task_id"] == sent[1]["task_id"] == "task-1"
    assert sent[0]["message_id"] != sent[1]["message_id"]
    assert h._request_id == sent[0]["message_id"]


def test_contract_is_immutable_after_bind(handle):
    h, _ = handle
    h.bind_execution_contract(contract())
    with pytest.raises(ValueError, match="cannot change"):
        h.bind_execution_contract(contract(3600))


def test_unmatched_reply_cannot_complete_active_request(handle):
    h, sent = handle
    h.bind_execution_contract(contract())
    h.write_message("goal")
    correct = {
        "type": "reply",
        "task_id": "task-1",
        "message_id": sent[0]["message_id"],
        "text": "done",
        "status": "completed",
        "termination_reason": "complete_task",
    }
    assert not h._accept_reply({**correct, "message_id": "old"})
    assert not h._accept_reply({**correct, "task_id": "other"})
    assert not h._accept_reply(
        {key: value for key, value in correct.items() if key != "message_id"}
    )
    assert h.in_flight and not h.request_outcomes
    assert h._accept_reply(correct)
    assert h.last_request_status == "completed"
    assert h.request_outcomes[0]["termination_reason"] == "complete_task"
    assert not h._accept_reply(correct)
    assert len(h.request_outcomes) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"status": "completed"},
        {"status": "garbage", "termination_reason": "complete_task"},
        {"status": [], "termination_reason": "complete_task"},
    ],
)
def test_missing_terminal_fields_never_default_to_success(handle, fields):
    h, sent = handle
    h.bind_execution_contract(contract())
    h.write_message("goal")
    assert h._accept_reply(
        {
            "type": "reply",
            "task_id": "task-1",
            "message_id": sent[0]["message_id"],
            "text": "done",
            **fields,
        }
    )
    assert h.last_request_status == "incomplete"
    assert h.request_outcomes[-1]["termination_reason"] == "protocol_invalid_terminal"


def test_builtin_ack_does_not_end_goal_or_clear_deadline(handle):
    h, sent = handle
    h.bind_execution_contract(contract())
    h.write_message("goal")
    original = h._task_budget.deadline
    h.write_message("/help")
    assert h._accept_reply(
        {
            "type": "reply",
            "kind": "builtin_command",
            "status": "acknowledged",
            "termination_reason": "builtin_command",
            "task_id": "task-1",
            "message_id": sent[1]["message_id"],
            "text": "help",
        }
    )
    assert h.in_flight and h._request_id == sent[0]["message_id"]
    assert h._task_budget.deadline == original
    assert h.last_request_status == "builtin_command"


def test_control_does_not_reset_clock(handle, monkeypatch):
    h, _ = handle
    h.bind_execution_contract(contract())
    h.write_message("goal")
    original = (h._t0, h._task_budget.deadline)

    def poll(seconds):
        h.last_sideband.append({"type": "status", "text": "working"})
        return "pending", 1

    monkeypatch.setattr(h, "poll", poll)
    h.control("status")
    assert (h._t0, h._task_budget.deadline) == original


def test_deadline_stops_then_grace_only_allows_termination(handle, monkeypatch):
    h, sent = handle
    h.bind_execution_contract(contract(10))
    now = [100.0]
    h._task_budget.clock = lambda: now[0]
    killed = []
    with monkeypatch.context() as patch:
        patch.setattr(launcher.time, "monotonic", lambda: now[0])
        patch.setattr(h, "_kill_group", killed.append)
        h.write_message("goal")
        now[0] = 111
        h._check_deadlines()
        assert sent[-1]["type"] == "interrupt"
        assert sent[-1]["reason"] == "task_budget_exhausted"
        with pytest.raises(RuntimeError, match="exhausted"):
            h.write_message("continue")
        assert not killed
        now[0] = 171
        with pytest.raises(RuntimeError, match="termination grace"):
            h._check_deadlines()
        assert killed and h.last_request_status == "timed_out"


def test_unknown_contract_budget_does_not_invent_1800_seconds(handle):
    h, _ = handle
    h.bind_execution_contract(contract(None))
    h.write_message("goal")
    assert h.request_budget_seconds is None
    assert h._task_budget.deadline is None
    assert h._limits.outer_seconds == float("inf")
