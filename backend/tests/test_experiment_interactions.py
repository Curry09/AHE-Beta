"""Execute frozen AABB plans and both interaction modes without models or cloud resources."""

from __future__ import annotations

import pytest

from ahe_beta.experiment.controllers import runtime
from ahe_beta.models import IssueDraft, Persona, SeedScenario, WorkspaceSpec
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.run_live import expert
from test_experiment_materials import aabb_inputs as aabb_inputs
from test_experiment_materials import prepared_inputs as prepared_inputs


class RecordingHarness(ScriptedHarness):
    def __init__(self):
        super().__init__()
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return super().send(message)


class RecordingClient(ScriptedPersonaClient):
    def __init__(self, calls):
        self.calls = calls

    def respond(self, system, user):
        if "<direct_review>" in user:
            self.calls.append("review")
            return {
                "verdict": "file_issue",
                "feedback": "The response has no verified artifact.",
                "issue": "The claimed pytz API is invalid.",
                "score": 2,
                "reason": "Unverified implementation.",
            }
        self.calls.append("simulated")
        return super().respond(system, user)


@pytest.mark.parametrize("mode", ["direct", "simulated_user", None])
def test_controller_factory_executes_interaction_and_persists_feedback(tmp_path, mode):
    sp = expert()
    persona = Persona(sp.persona_id, "expert", "python", "fix task", "precise")
    calls = []
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    factory = runtime
    run = factory._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(calls),
        tracker=tracker,
        store=store,
        sim_personas={sp.persona_id: sp},
    )
    scenario = SeedScenario(
        "Fix timeutils and run the DST checks",
        WorkspaceSpec(
            kind="empty",
            params={"task_key": "simple-task", **({"interaction": mode} if mode else {})},
        ),
    )
    harness = RecordingHarness()
    session = run(persona, scenario, harness)
    persisted = store.load(session.session_id)
    assert persisted.issue_refs
    assert tracker.list_open_issues()
    assert run.load_completed_session(session.session_id) == persisted
    if mode == "direct":
        assert calls == ["review"]
        assert harness.messages == [scenario.description]
        assert persisted.user_outcome["interaction_mode"] == "direct"
        assert persisted.sim_trace is None
    else:
        assert "review" not in calls
        assert len(calls) > 1
        assert len(harness.messages) > 1
        assert persisted.sim_trace is not None
        assert persisted.sim_trace.turns


@pytest.mark.parametrize("extra", [None, "proposal", "ready", "openagents"])
def test_backpressure_counts_open_queues_and_warns_only_above_threshold(monkeypatch, capsys, extra):
    tracker = FakeTracker()
    monkeypatch.setenv("PROPOSAL_DEPTH_ALARM", "2")
    monkeypatch.setenv("READY_DEPTH_ALARM", "2")
    for label in ("proposal", "proposal", "ready", "openagents"):
        tracker.create_issue(IssueDraft(label, "pending", [label]))
    for label in ("proposal", "ready"):
        closed = tracker.create_issue(IssueDraft("closed", "completed", [label]))
        tracker.set_state(closed.number, "closed", "done")
    tracker.create_issue(IssueDraft("raw feedback", "untriaged", ["report"]))
    if extra is not None:
        tracker.create_issue(IssueDraft("extra pending", "over threshold", [extra]))
    runtime._check_backpressure(tracker=tracker, round_no=9)
    warnings = capsys.readouterr().out
    if extra is None:
        assert warnings == ""
    else:
        plane = "proposal" if extra == "proposal" else "ready"
        assert f"End of round 9: {plane} depth 3 > 2" in warnings
        assert warnings.count("[backpressure warning]") == 1


def test_backpressure_read_failure_does_not_block_the_completed_round(monkeypatch, capsys):
    tracker = FakeTracker()

    def failed_read():
        raise RuntimeError("tracker unavailable")

    monkeypatch.setattr(tracker, "list_open_issues", failed_read)
    runtime._check_backpressure(tracker=tracker, round_no=1)
    assert capsys.readouterr().out == ""
