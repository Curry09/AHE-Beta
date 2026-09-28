from __future__ import annotations

from pathlib import Path

from auto_designer.loop.sim_user import make_direct_run_session_fn, make_mixed_run_session_fn
from auto_designer.models import Persona, SeedScenario, WorkspaceSpec
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class _Harness:
    request_outcomes: list[dict] = []
    observation_source = None

    def __init__(self) -> None:
        self.messages: list[str] = []

    def reset(self) -> None:
        pass

    def send(self, message: str) -> str:
        self.messages.append(message)
        return "completed"

    def close(self) -> None:
        pass


class _BrokenHarness(_Harness):
    def send(self, message: str) -> str:
        self.messages.append(message)
        raise RuntimeError("gateway unavailable")


class _ReviewClient:
    model = "fake-review-model"

    def respond(self, system: str, user: str) -> dict:
        return {
            "verdict": "file_issue",
            "feedback": "The terminal result needs triage.",
            "issue": "The harness did not provide a verifiable artifact.",
            "score": 2,
            "reason": "The result is not verifiable.",
        }


def test_direct_mode_sends_one_harness_message_then_one_terminal_review(tmp_path: Path) -> None:
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    run = make_direct_run_session_fn(
        client_factory=_ReviewClient,
        tracker=tracker,
        store=store,
        sim_personas={},
    )
    harness = _Harness()
    scenario = SeedScenario(
        "run the frozen task",
        WorkspaceSpec(
            kind="prebuilt",
            params={
                "task_key": "O09",
                "task_id": "production-planning",
                "benchmark": "Terminal-Bench",
                "interaction": "direct",
            },
        ),
    )

    session = run(
        Persona("mechanical-direct", "n/a", "benchmark", "deliver", "one-shot"),
        scenario,
        harness,
    )

    assert harness.messages == ["run the frozen task"]
    assert session.user_outcome == {
        "interaction_mode": "direct",
        "user_model": "fake-review-model",
        "user_turns": 1,
        "harness_messages": 1,
        "review_calls": 1,
        "followups": 0,
        "heartbeat": False,
        "review_status": "completed",
        "review_verdict": "file_issue",
        "review_feedback": "The terminal result needs triage.",
        "status": "completed",
        "harness_reply": "completed",
    }
    assert [turn.role for turn in session.transcript.turns] == ["user", "harness", "user"]
    assert len(session.issue_refs) == 1
    assert store.load(session.session_id).session_id == session.session_id


def test_mixed_direct_branch_does_not_send_review_to_harness(tmp_path: Path) -> None:
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    run = make_mixed_run_session_fn(
        client_factory=_ReviewClient,
        tracker=tracker,
        store=store,
        sim_personas={},
    )
    harness = _Harness()
    scenario = SeedScenario(
        "one shot",
        WorkspaceSpec(kind="prebuilt", params={"task_key": "tinydb", "interaction": "direct"}),
    )
    session = run(Persona("direct", "n/a", "benchmark", "deliver", "one-shot"), scenario, harness)
    assert harness.messages == ["one shot"]
    assert session.user_outcome["user_model"] == "fake-review-model"


def test_direct_harness_failure_is_persisted_as_infrastructure_failure(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    run = make_direct_run_session_fn(
        client_factory=_ReviewClient,
        tracker=FakeTracker(),
        store=store,
        sim_personas={},
    )
    session = run(
        Persona("direct", "n/a", "benchmark", "deliver", "one-shot"),
        SeedScenario("one shot", WorkspaceSpec(kind="prebuilt", params={"task_key": "broken"})),
        _BrokenHarness(),
    )
    assert session.user_outcome["status"] == "infrastructure_failure"
    assert "gateway unavailable" in session.user_outcome["error"]
    assert session.issue_refs
