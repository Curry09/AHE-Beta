"""Inner tool-using agent (AgenticPersonaClient, spec-0008/T4).

Offline bounded tool-calling loop: tool_call→observe→final contract; blind degrades to plain text;
exceed step limit / invalid JSON fallback; end-to-end via run_session + billing-split fixture without affecting the outer engine;
ScriptedPersonaClient does not regress. FakeToolLLM + FakeSandbox fully offline.
"""

from __future__ import annotations

import json

import pytest

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.loop import run_session
from ahe_beta.user.sim.persona_client import (
    AgenticPersonaClient,
    PersonaProtocolError,
    ScriptedPersonaClient,
)
from ahe_beta.user.sim.workspace import materialize


def _persona(d1: D1Eval) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="p",
            d1=d1,
            d2=D2Domain(),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


class FakeToolLLM:
    """Return text sequentially per script; when script exhausted, return minimal legal object for current stage."""

    def __init__(self, scripted: list[str] | None = None) -> None:
        self.scripted = list(scripted or [])
        self.calls: list[list[dict]] = []

    def __call__(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        last = messages[-1]["content"]
        if "<rate_experience>" in last:
            return json.dumps({"score": 4, "reason": "ok"})
        if "<file_issue>" in last:
            return json.dumps({"issue": "meh"})
        if self.scripted:
            return self.scripted.pop(0)
        if "<main_judge>" in last or "<main_rejudge>" in last:
            return json.dumps({"perceive": "looks fine", "verdict": "satisfied"})
        if "<main_intent>" in last or "<main_reintent>" in last:
            return json.dumps(
                {"intent": "accept if complete", "needs_final_check": False, "check_goal": ""}
            )
        if "<main_final_check>" in last:
            return json.dumps({"perceive": "checked", "check_status": "completed"})
        if "<main_act>" in last:
            if "'accept'" in last:
                return json.dumps({"action": "accept", "message": "ok", "gap": False})
            return json.dumps(
                {"action": "send_message", "message": "please do the task", "gap": False}
            )
        return json.dumps({"perceive": "looks fine", "verdict": "satisfied"})


class FakeSandbox:
    def __init__(self, workspace: str | None = None) -> None:
        self.cwd = workspace or "/fake"
        self.runs: list[tuple] = []
        self.cleaned = False

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        self.runs.append((cmd, timeout))
        return {"ok": True, "stdout": "OK", "stderr": "", "returncode": 0}

    def resolve(self, path: str) -> str:
        return path

    def cleanup(self) -> None:
        self.cleaned = True


# --------------------------------------------------------------------------
# (a) Multi-step: tool_call -> observe -> final contract
# --------------------------------------------------------------------------
def test_tool_call_then_final_contract() -> None:
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "run_shell", "args": {"cmd": "python billing/core.py"}}),
            json.dumps(
                {"perceive": "ran it", "verdict": "satisfied", "action": "accept", "message": "ok"}
            ),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.COMPETENT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert sb.runs and sb.runs[0][0] == "python billing/core.py"
    assert out["verdict"] == "satisfied" and out["action"] == "accept"
    assert len(llm.calls) == 2 and sb.cleaned
    from ahe_beta.user.sim.persona_client import drain_call_traces

    traces = drain_call_traces(c)
    assert len(traces) == 1
    assert traces[0]["system"]  # Actual inner_system fed in, not full-session SYS placeholder
    assert traces[0]["user"] == "<task>x</task>"
    kinds = [s["kind"] for s in traces[0]["steps"]]
    assert kinds[:2] == ["assistant", "tool"]
    assert "tool_result" in kinds or "tool_error" in kinds
    assert kinds[-1] == "assistant"


# --------------------------------------------------------------------------
# (b) blind/no tools -> pure text judgment, no sandbox constructed
# --------------------------------------------------------------------------
def test_blind_degrades_to_text_only() -> None:
    created: list[int] = []
    llm = FakeToolLLM(
        [
            json.dumps(
                {
                    "perceive": "skim",
                    "verdict": "unsure",
                    "action": "send_message",
                    "message": "hmm",
                }
            )
        ]
    )

    def factory(workspace=None):
        created.append(1)
        return FakeSandbox(workspace)

    c = AgenticPersonaClient(llm, sandbox_factory=factory)
    c.bind_session(_persona(D1Eval.BLIND), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert created == []  # blind no tools, do not enter tool loop
    assert out["action"] == "send_message"


# --------------------------------------------------------------------------
# (c) max_inner_steps is pure tool quota; when exhausted, force subjective conclusion separately
# --------------------------------------------------------------------------
def test_tool_budget_exhaustion_reserves_forced_conclusion() -> None:
    sb = FakeSandbox()
    toolcall = json.dumps({"tool": "run_shell", "args": {"cmd": "echo hi"}})
    conclusion = json.dumps({"perceive": "three checks were enough", "verdict": "satisfied"})
    llm = FakeToolLLM([toolcall, toolcall, toolcall, conclusion])
    c = AgenticPersonaClient(llm, max_inner_steps=3, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<main_judge><task>x</task></main_judge>")
    assert out == {"perceive": "three checks were enough", "verdict": "satisfied"}
    assert len(sb.runs) == 3
    assert len(llm.calls) == 4
    assert "No more tools are available" in llm.calls[-1][-1]["content"]


def test_forced_conclusion_never_dispatches_more_tools() -> None:
    sb = FakeSandbox()
    toolcall = json.dumps({"tool": "run_shell", "args": {"cmd": "echo hi"}})
    llm = FakeToolLLM([toolcall, toolcall, toolcall])
    c = AgenticPersonaClient(llm, max_inner_steps=1, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    with pytest.raises(PersonaProtocolError, match="forced_conclusion_tool_not_allowed"):
        c.respond("SYS", "<main_judge><task>x</task></main_judge>")
    assert len(sb.runs) == 1


# --------------------------------------------------------------------------
# (d) Invalid JSON -> first retry with "return only JSON"; if both fail, safely degrade (unsure/free)
# --------------------------------------------------------------------------
def test_invalid_json_retry_then_raises_typed_error() -> None:
    # Both invalid: do not treat parse-failure shell as real action.
    llm = FakeToolLLM(["this is not json at all", "still not json"])
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    with pytest.raises(PersonaProtocolError, match="unparseable_json"):
        c.respond("SYS", "<task>x</task>")
    assert len(llm.calls) == 2  # Retry does occur


def test_invalid_json_retry_recovers() -> None:
    # First invalid, retry yields legal contract -> restore actual intent, not downgrade/fabricate
    good = json.dumps(
        {"perceive": "ok", "verdict": "satisfied", "action": "accept", "message": "great"}
    )
    llm = FakeToolLLM(["oops not json", good])
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert out["action"] == "accept" and out["verdict"] == "satisfied"
    assert len(llm.calls) == 2


def test_main_act_private_tool_object_is_retried_not_accepted() -> None:
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "run_shell", "args": {"cmd": "git diff"}}),
            json.dumps({"action": "accept", "message": "checked", "gap": False}),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond(
        "SYS",
        "<main_act>\n<action_space>\n['accept', 'send_message']\n</action_space>\n</main_act>",
    )
    assert out["action"] == "accept"
    assert len(llm.calls) == 2
    assert "tool_not_allowed_in_stage" in llm.calls[1][-1]["content"]


def test_terminal_accept_contract_allows_omitted_message_and_gap() -> None:
    llm = FakeToolLLM([json.dumps({"action": "accept"})])
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond(
        "SYS",
        "<main_act>\n<action_space>\n['accept', 'send_message']\n</action_space>\n</main_act>",
    )
    assert out == {"action": "accept"}
    assert len(llm.calls) == 1


def test_judge_tool_returned_after_contract_retry_is_dispatched() -> None:
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            "truncated",
            json.dumps({"tool": "run_shell", "args": {"cmd": "git diff --check"}}),
            json.dumps({"perceive": "diff is clean", "verdict": "satisfied"}),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<main_judge><task>x</task></main_judge>")
    assert out == {"perceive": "diff is clean", "verdict": "satisfied"}
    assert sb.runs[0][0] == "git diff --check"


def test_final_check_tool_budget_is_capped_at_four() -> None:
    sb = FakeSandbox()
    toolcall = json.dumps({"tool": "run_shell", "args": {"cmd": "echo check"}})
    conclusion = json.dumps({"perceive": "four checks completed", "check_status": "completed"})
    llm = FakeToolLLM([toolcall] * 4 + [conclusion])
    c = AgenticPersonaClient(llm, max_inner_steps=8, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<main_final_check><check_goal>x</check_goal></main_final_check>")
    assert out == {"perceive": "four checks completed", "check_status": "completed"}
    assert len(sb.runs) == 4  # Interactive checks execute commands, retaining the bounded episode.
    assert len(llm.calls) == 5


def test_opening_judge_cannot_dispatch_private_tools() -> None:
    created: list[int] = []
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "run_shell", "args": {"cmd": "git diff"}}),
            json.dumps({"perceive": "task text only", "verdict": "unsure", "task_load": "normal"}),
        ]
    )

    def factory(workspace=None):
        created.append(1)
        return FakeSandbox(workspace)

    c = AgenticPersonaClient(llm, sandbox_factory=factory)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")
    user = (
        "<main_judge><task>x</task>\n# SIZE UP THIS TASK (first turn only)\n"
        'Return {"task_load":"normal"}</main_judge>'
    )
    out = c.respond("SYS", user)
    assert out["task_load"] == "normal"
    assert created == []
    assert "tool_not_allowed_in_stage" in llm.calls[1][-1]["content"]


def test_blind_final_check_is_explicitly_unavailable() -> None:
    llm = FakeToolLLM()
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.BLIND), "/ws")

    out = c.respond("SYS", "<main_final_check><check_goal>x</check_goal></main_final_check>")
    assert out["check_status"] == "unavailable"
    assert llm.calls == []


def test_run_session_two_illegal_act_tool_objects_yield_zero_accept() -> None:
    llm = FakeToolLLM(
        [
            json.dumps(
                {"perceive": "nothing has started", "verdict": "unsure", "task_load": "normal"}
            ),
            json.dumps({"intent": "start", "needs_final_check": False, "check_goal": ""}),
            json.dumps({"tool": "run_shell", "args": {"cmd": "git diff"}}),
            json.dumps({"tool": "run_shell", "args": {"cmd": "git status"}}),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    res = run_session(_persona(D1Eval.EXPERT), c, ScriptedHarness(), "task")
    assert res.evaluation_status == "invalid"
    assert res.end_reason == "evaluator_invalid"
    assert res.evaluation_error and res.evaluation_error["code"] == "tool_not_allowed_in_stage"
    assert all(turn.action not in {"accept", "accept_with_reservations"} for turn in res.turns)


# --------------------------------------------------------------------------
# (e) End-to-end: run_session + real fixture, outer engine unaffected
# --------------------------------------------------------------------------
def test_integration_run_session_unaffected() -> None:
    persona = _persona(D1Eval.COMPETENT)
    ws = materialize(WorkspaceSpec(fixture="billing-split"))
    # Default accept each round; OPENING projected as send_message, next round accept terminates
    llm = FakeToolLLM()
    c = AgenticPersonaClient(llm)  # Real Sandbox over ws
    c.bind_session(persona, ws)

    res = run_session(persona, c, ScriptedHarness(), "task")
    assert res.turns  # Up and running
    assert res.feeling is not None  # Self-assessment output (outer process complete)


# --------------------------------------------------------------------------
# (f) ScriptedPersonaClient does not regress
# --------------------------------------------------------------------------
def test_scripted_client_still_works() -> None:
    user = (
        "<harness_output>\n(empty)\n</harness_output>\n\n"
        "<action_space>\n['send_message']\n</action_space>\n\n"
        "<mood>\npatience=full, trust=balanced\n</mood>"
    )
    out = ScriptedPersonaClient().respond("sys", user)
    assert out["action"] == "send_message"


# --------------------------------------------------------------------------
# (g) Mid-process report_issue: does not terminate; can idle; write to drain → SessionResult
# --------------------------------------------------------------------------
def test_report_issue_tool_continues_and_drains() -> None:
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "report_issue", "args": {"body": "split is off by a cent"}}),
            json.dumps(
                {
                    "perceive": "noted the bug, still trying",
                    "verdict": "failed_blame_harness",
                    "action": "send_message",
                    "message": "try again please",
                }
            ),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.COMPETENT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert out["action"] == "send_message"  # Not terminated due to issue creation
    notes = c.drain_issue_notes()
    assert notes == ["split is off by a cent"]
    assert c.drain_issue_notes() == []  # Already cleared


def test_report_issue_idle_when_unused() -> None:
    """Allow idling: when report_issue is never called, notes remain empty and do not affect existing paths."""
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            json.dumps(
                {"perceive": "ok", "verdict": "satisfied", "action": "accept", "message": "thanks"}
            ),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.COMPETENT), "/ws")
    c.respond("SYS", "<task>x</task>")
    assert c.drain_issue_notes() == []


def test_report_issue_empty_body_rejected() -> None:
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "report_issue", "args": {"body": "  "}}),
            json.dumps(
                {"perceive": "skip", "verdict": "unsure", "action": "accept", "message": "bye"}
            ),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.COMPETENT), "/ws")
    c.respond("SYS", "<task>x</task>")
    assert c.drain_issue_notes() == []


def test_run_session_collects_mid_session_issue_notes() -> None:
    persona = _persona(D1Eval.COMPETENT)
    llm = FakeToolLLM(
        [
            # OPENING · judge: first round judges only by task text, does not call private tool
            json.dumps(
                {
                    "perceive": "still starting",
                    "verdict": "unsure",
                    "task_load": "normal",
                }
            ),
            # OPENING · intent / act
            json.dumps({"intent": "start the task", "needs_final_check": False, "check_goal": ""}),
            json.dumps(
                {
                    "action": "send_message",
                    "message": "please implement X",
                    "gap": False,
                }
            ),
            # Next round · judge: record one real issue first, then judge; intent / act → accept
            json.dumps({"tool": "report_issue", "args": {"body": "docs are wrong about /status"}}),
            json.dumps({"perceive": "done", "verdict": "satisfied"}),
            json.dumps(
                {"intent": "accept and move on", "needs_final_check": False, "check_goal": ""}
            ),
            json.dumps({"action": "accept", "message": "ok", "gap": False}),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox(workspace))
    c.bind_session(persona, "/ws")
    res = run_session(persona, c, ScriptedHarness(), "task")
    assert res.end_reason == "accepted"
    assert res.issue_notes == ["docs are wrong about /status"]
    assert any(s.startswith("ISSUE_TOOL: report_issue") for s in res.signals)
    traces = [call for turn in res.turns for call in turn.persona_trace]
    judge_users = [call["user"] for call in traces if call.get("role") == "main_judge"]
    intent_users = [call["user"] for call in traces if call.get("role") == "main_intent"]
    act_users = [call["user"] for call in traces if call.get("role") == "main_act"]
    assert judge_users and intent_users and act_users
    assert all("<action_space>" not in user for user in judge_users)
    assert all("<action_space>" not in user for user in intent_users)
    assert all("<action_space>" in user for user in act_users)
