"""Spec-0057/T2: voluntary feedback accompanies, never replaces, the main action."""

from dataclasses import replace

import pytest

from auto_designer.loop.sim_user import make_sim_run_session_fn
from auto_designer.models import Persona, SeedScenario
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.dimensions import D1Eval
from auto_designer.user.sim.loop import run_session
from auto_designer.user.sim.persona_client import ScriptedPersonaClient, _validate_stage_output
from auto_designer.user.sim.run_live import expert

NOTE = "The result now works, but I had to repeat my request before the tool followed it."


class FeedbackClient(ScriptedPersonaClient):
    def __init__(self, report=None, *, report_on="accept", repeat=False):
        self.report = report
        self.report_on = report_on
        self.repeat = repeat
        self.acts = 0
        self.prompts = []

    def _respond_body(self, system, user):
        self.prompts.append(user)
        if "<main_judge>" in user:
            return {"perceive": "I read the visible reply.", "verdict": "unsure"}
        if "<main_intent>" in user:
            return {"intent": "Finish this task.", "needs_final_check": False}
        if "<main_act>" in user:
            self.acts += 1
            action = "send_message" if self.acts <= 2 else "accept"
            result = {
                "action": action,
                "message": "Please finish the task." if action == "send_message" else "",
                "goal_effect": {
                    "kind": "close" if action == "accept" else "advance",
                    "goal_ids": ["B0"],
                },
            }
            if action == self.report_on or self.repeat:
                result["report_issue"] = self.report
            return result
        if "<rate_experience>" in user:
            return {"score": 2, "reason": "It worked, but the process was frustrating."}
        return super()._respond_body(system, user)


class Harness:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return "Requested change delivered; the requested check passed."

    def reset(self):
        self.messages.clear()

    def close(self):
        pass


@pytest.mark.parametrize("ability", [D1Eval.BLIND, D1Eval.EXPERT])
@pytest.mark.parametrize("report_on", ["send_message", "accept"])
def test_report_preserves_main_action_and_reaches_tracker(tmp_path, ability, report_on):
    persona = replace(expert(), d1=ability)
    model_persona = Persona(
        identity=persona.persona_id,
        level=ability.value,
        domain="python",
        goal="finish task",
        speaking_style="direct",
    )
    client = FeedbackClient({"body": NOTE}, report_on=report_on)
    harness = Harness()
    tracker = FakeTracker()
    store = SessionStore(tmp_path)
    run = make_sim_run_session_fn(
        client_factory=lambda: client,
        tracker=tracker,
        store=store,
        sim_personas={persona.persona_id: persona},
    )
    session = run(model_persona, SeedScenario(description="Deliver the requested change."), harness)
    loaded = store.load(session.session_id)
    assert loaded.user_outcome["end_reason"] == "accepted"
    assert len(harness.messages) == 2
    assert all(NOTE not in message for message in harness.messages)
    assert len(loaded.issue_refs) == 1
    issue = tracker.list_open_issues()[0]
    assert issue.body == NOTE
    assert "needs-triage" in issue.labels
    assert loaded.issue_refs[0].number == issue.number
    assert loaded.sim_trace.goal_ledger["unresolved"] == []
    assert any(
        call.parsed.get("report_issue") == {"body": NOTE}
        for turn in loaded.sim_trace.turns
        for call in turn.persona_trace
    )
    if report_on == "send_message":
        assert any("feedback recorded for tool developers" in p for p in client.prompts)
    assert client.acts == 3  # No extra model episode to compose feedback.


@pytest.mark.parametrize("report", [None, {}, "complaint", {"body": 12}, {"body": " "}])
def test_optional_bad_report_does_not_block_accept_or_invent_feedback(report):
    client = FeedbackClient(report)
    result = run_session(expert(), client, Harness(), "Deliver the requested change.")
    assert result.end_reason == "accepted"
    assert result.feeling.score == 2
    assert result.issue_notes == []  # Low experience rating never generates a report.
    warnings = [e for e in result.protocol_events if e.get("code") == "invalid_report_issue"]
    assert bool(warnings) == (report is not None)
    # Parsing must accept the main action even if optional feedback is malformed.
    assert (
        _validate_stage_output(
            "waiting_act", {"action": "keep_waiting", "report_issue": report}, ""
        )
        is None
    )


def test_repeated_explicit_report_is_recorded_once():
    client = FeedbackClient({"body": NOTE}, repeat=True)
    result = run_session(expert(), client, Harness(), "Deliver the requested change.")
    assert result.issue_notes == [NOTE]
    assert result.end_reason == "accepted"
    assert len([s for s in result.signals if s.startswith("ISSUE_TOOL:")]) == 1


class ReplayHarness:
    """Small deterministic replay of the two failure shapes seen in hard traces."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return self.outputs.pop(0) if self.outputs else ""

    def reset(self):
        self.messages.clear()

    def close(self):
        pass


class ReplayClient(ScriptedPersonaClient):
    def __init__(self, actions, *, report=None):
        self.actions = iter(actions)
        self.report = report

    def _respond_body(self, system, user):
        if "<main_judge>" in user:
            return {"perceive": "I read the visible harness reply.", "verdict": "unsure"}
        if "<main_intent>" in user:
            return {"intent": "follow the requested reproduction", "needs_final_check": False}
        if "<main_act>" in user:
            action = next(self.actions)
            body = {
                "action": action,
                "message": "Run the exact reproduction and show stdout."
                if action == "send_message"
                else "",
                "goal_effect": {
                    "kind": "advance" if action == "send_message" else "abandon",
                    "goal_ids": ["B0"],
                },
            }
            if self.report is not None and action in {"send_message", "accept"}:
                body["report_issue"] = {"body": self.report}
            return body
        if "<file_issue>" in user:
            return {
                "issue": "The harness kept ignoring the exact reproduction and claimed success."
            }
        if "<rate_experience>" in user:
            return {"score": 1, "reason": "The harness did not follow the exact reproduction."}
        return super()._respond_body(system, user)


def test_trace_replay_visible_success_accepts_and_can_report() -> None:
    """A visible exact reproduction can be accepted while recording separate feedback."""
    report = "The fix worked, but the harness made me repeat the exact reproduction."
    client = ReplayClient(["send_message", "accept"], report=report)
    result = run_session(
        expert(),
        client,
        ReplayHarness(
            [
                "The exact reproduction is now prepared; please verify it.",
                "Exact reproduction output: expected result; return code 0.",
            ]
        ),
        "Run the exact reproduction and make the reported behavior work.",
    )
    assert result.end_reason == "accepted"
    assert result.issue_notes == [report]
    assert result.feeling.score == 1


def test_trace_replay_repeated_wrong_output_gives_up_and_reports_at_terminal() -> None:
    """A repeated contradiction leads to correction attempts, then a terminal report."""
    client = ReplayClient(["send_message", "send_message", "give_up"])
    result = run_session(
        expert(),
        client,
        ReplayHarness(
            [
                "I explored unrelated internals; no reproduction output yet.",
                "The fix is correct, but the exact reproduction still returns the wrong result.",
            ]
        ),
        "Run the exact reproduction and make the reported behavior work.",
    )
    assert result.end_reason == "abandoned"
    assert result.issue_artifact is not None
    assert "ignoring the exact reproduction" in result.issue_artifact
