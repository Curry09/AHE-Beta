"""Spec-0055 deterministic evidence projection and role visibility tests."""

from __future__ import annotations

from pathlib import Path

from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.divergent import Divergent
from ahe_beta.demand.evidence_contract import (
    EvidenceLevel,
    build_evidence_envelope,
    build_l1_summary,
    project_for_role,
    validate_envelope,
    validate_role_access,
)
from ahe_beta.demand.owner import Owner
from ahe_beta.demand.session_timeline import (
    bind_session_store,
    get_harness_beat,
    get_session_timeline,
)
from ahe_beta.demand.triage import Triager
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    PersonaCallTrace,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore


def _session(tmp_path: Path | None = None) -> Session:
    turn = SimTurn(
        turn=1,
        phase="active",
        action_space=["send_message", "accept"],
        perceive="I want to inspect /root/src/secret/project.py",
        verdict="unsure",
        action="send_message",
        message="Please fix /mnt/c/Users/user/project.py",
        executor="harness",
        channel="emit",
        patience=2,
        trust="skeptical",
        harness_output="RAW_STDOUT_SENTINEL " * 100,
        harness_steps=[{"kind": "tool_result", "text": "RAW_STEP_SENTINEL " * 100}],
        persona_trace=[
            PersonaCallTrace(
                role="main_act",
                raw="RAW_RAW_SENTINEL",
                parsed={"intent": "make the command work", "action": "send_message"},
                system="RAW_SYSTEM_SENTINEL",
                user="RAW_USER_SENTINEL",
            )
        ],
        target_goal_ids=["B0"],
        expected_progress="command handles empty input",
        goal_effect={"kind": "advance", "goal_ids": ["B0"]},
    )
    trace = SimTrace(
        persona_id="persona-secret",
        end_reason="issue_filed",
        turns=[turn],
        goal_ledger={
            "baseline_id": "B0",
            "focus_goal_id": "B0",
            "goals": [
                {
                    "goal_id": "B0",
                    "text": "make /root/src/secret/project.py work",
                    "initial_text": "make /root/src/secret/project.py work",
                    "done_if": "empty input works",
                    "status": "open",
                    "version": 1,
                }
            ],
            "events": [],
        },
        goal_acceptance={"status": "accepted", "goal_ids": ["B0"]},
    )
    return Session(
        persona=Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s"),
        scenario=SeedScenario(description="s"),
        transcript=Transcript(turns=[]),
        feeling=FeelingScore(score=2, reason="RAW_REASON_SENTINEL"),
        sim_trace=trace,
        user_outcome={"end_reason": "issue_filed", "terminal_note": "user report"},
        accept_validity="invalid",
        objective_evaluation={"status": "failed", "passed": False, "stdout": "do not expose"},
    )


def test_l1_is_deterministic_bounded_and_redacts_common_leaks() -> None:
    summary = build_l1_summary(_session())
    blob = str(summary)
    assert summary["level"] == EvidenceLevel.COMPACT.value
    assert summary["provenance"]["deterministic"] is True
    assert "RAW_SYSTEM_SENTINEL" not in blob
    assert "RAW_USER_SENTINEL" not in blob
    assert "RAW_STDOUT_SENTINEL" not in blob
    assert "RAW_STEP_SENTINEL" not in blob
    assert "/mnt/c/" not in blob and "/root/src/" not in blob
    assert summary["goal_summary"]["initial"]["text"] == "make <path> work"
    assert summary["goal_summary"]["current"]["text"] == "make <path> work"
    assert summary["key_events"][0]["target_goal_ids"] == ["B0"]
    assert summary["objective_evidence"]["status"] == "failed"
    assert summary["objective_evidence"]["passed"] is False
    assert summary["accept_validity"] == "invalid"


def test_envelope_separates_user_and_objective_lanes() -> None:
    envelope = build_evidence_envelope(
        _session(),
        report={"issue_id": 7, "title": "raw title", "labels": ["report"]},
    )
    assert validate_envelope(envelope) == []
    triage = project_for_role(envelope, "triager")
    pm = project_for_role(envelope, "divergent")
    architect = project_for_role(envelope, "architect")
    owner = project_for_role(envelope, "owner")
    assert triage["source_report"]["issue_id"] == 7
    assert "goal_summary" in triage["user_evidence"]
    assert triage["objective_evidence"]["status"] == "failed"
    assert "source_report" not in pm and "user_evidence" in pm
    assert set(architect) <= {"level", "session_id", "evidence_refs"}
    assert set(owner) <= {"level", "session_id", "evidence_refs"}


def test_legacy_session_is_explicitly_unavailable() -> None:
    session = _session()
    session.sim_trace = None
    session.objective_evaluation = None
    envelope = build_evidence_envelope(session)
    assert envelope.user_evidence["goal_summary"]["status"] == "unavailable"
    assert envelope.objective_evidence["status"] == "unavailable"
    assert "legacy session" in envelope.user_evidence["goal_summary"]["initial"]["reason"]


def test_role_access_fails_closed_for_forbidden_levels() -> None:
    assert validate_role_access(role="owner", level="L3")[0] is False
    assert validate_role_access(role="architect", level="L4")[0] is False
    assert validate_role_access(role="pm", level="L3")[0] is True
    assert (
        validate_role_access(role="triager", level="L2", session_id="s2", source_session_id="s1")[0]
        is False
    )
    assert validate_role_access(role="random", level="L1")[0] is False


def test_session_store_persists_and_triage_consumes_handoff(tmp_path, monkeypatch) -> None:
    session = _session()
    store = SessionStore(tmp_path / "sessions")
    # This is what the real session runner does at close; exercising the store
    # separately makes the handoff contract useful for offline closed-loop replay.
    session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
    store.save(session)
    assert store.load_user_feedback_envelope(session.session_id)["level"] == "L1"

    tracker = FakeTracker()
    issue = tracker.create_issue(
        IssueDraft(title="raw user report", body="raw report body", labels=[sc.REPORT])
    )
    session.issue_refs = [IssueRef(number=issue.number, url="", state="open")]
    # Re-save now that the issue↔session link is present.
    session.user_feedback_envelope = build_evidence_envelope(session).to_dict()
    store.save(session)
    captured: list[str] = []

    def fake_run(*args, **kwargs):
        captured.append(kwargs.get("message") or (args[1] if len(args) > 1 else ""))
        return '{"dispositions": []}'

    monkeypatch.setattr("ahe_beta.demand.triage.run_agent_def", fake_run)
    triager = Triager(tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"))
    triager.triage_once()
    assert captured and "目标感知用户证据" in captured[0]
    assert "RAW_SYSTEM_SENTINEL" not in captured[0]
    assert "RAW_STDOUT_SENTINEL" not in captured[0]


def test_pm_and_owner_receive_only_their_goal_projection(tmp_path) -> None:
    session = _session()
    store = SessionStore(tmp_path / "sessions")
    store.save(session)
    trend = [("now", 2, "slow", session.session_id)]
    pm = Divergent(FakeTracker(), store, str(tmp_path), str(tmp_path / "pm"))
    pm_rows = pm._goal_index(trend)
    assert pm_rows and "user_evidence" in pm_rows[0]
    assert "objective_evidence" not in pm_rows[0]
    owner = Owner(FakeTracker(), store, str(tmp_path), str(tmp_path / "owner"))
    owner_text = owner._goal_summary_index(trend)
    assert session.session_id in owner_text
    assert "RAW_STDOUT_SENTINEL" not in owner_text


def test_timeline_tools_enforce_role_visibility_and_audit_reason(tmp_path, monkeypatch) -> None:
    session = _session()
    store = SessionStore(tmp_path / "sessions")
    store.save(session)
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path / "role-runs"))
    with bind_session_store(store), bind_usage_context(role="owner"):
        denied = get_session_timeline(session_id=session.session_id, reason="should not be visible")
    assert denied["ok"] is False
    with bind_session_store(store), bind_usage_context(role="divergent"):
        allowed = get_session_timeline(
            session_id=session.session_id, reason="explain the user wait"
        )
        beat = get_harness_beat(
            turn=1, session_id=session.session_id, reason="attribute the harness reply"
        )
    assert allowed["ok"] and allowed["evidence_access"]["level"] == "L2"
    assert beat["ok"] and beat["evidence_access"]["level"] == "L3"
    audit = (tmp_path / "role-runs" / "evidence_access.jsonl").read_text(encoding="utf-8")
    assert "should not be visible" in audit
    assert "explain the user wait" in audit


def contract_session(*, sid="session-current", followup="unavailable"):
    """Current immutable public declaration with an ungraded/missing experience axis."""
    from ahe_beta.execution_contract import canonical_sha256, make_execution_contract

    scenario = SeedScenario(description="Complete the original public goal without extra input.")
    declaration = make_execution_contract(
        session_id=sid,
        task_id=f"task-{sid}",
        task_digest="a" * 64,
        followup_input=followup,
        task_budget_seconds=7200,
        budget_source="task_metadata",
        public_refs=[
            {
                "kind": "task",
                "path": f"{sid}/execution/task.json",
                "sha256": canonical_sha256(scenario.to_dict()),
            }
        ],
    )
    return Session(
        persona=Persona("i", "l", "d", "g", "s"),
        scenario=scenario,
        transcript=Transcript(),
        session_id=sid,
        execution_contract=declaration,
        feedback={
            "schema_version": 1,
            "task_assessment": {"status": "unfulfilled", "source": "reviewer", "evidence_refs": []},
            "experience": {
                "status": "missing",
                "score": None,
                "source": "reviewer",
                "reason": "no self-rating",
            },
            "attribution": {"status": "unknown", "claims": []},
            "opportunities": [],
        },
    )


def test_direct_goal_and_missing_rating_remain_distinct_from_execution_outcome():
    session = contract_session()
    l1 = build_l1_summary(session)
    assert l1["goal_summary"]["initial"]["text"] == session.scenario.description
    assert "baseline_id" not in l1["goal_summary"]
    assert l1["feedback_events"][0]["score"] is None
    assert l1["feedback_events"][0]["status"] == "missing"
    envelope = build_evidence_envelope(session)
    assert envelope.user_evidence["task_assessment"]["status"] == "unfulfilled"
    for role in ("triage", "pm", "architect", "owner"):
        projection = project_for_role(envelope, role)
        assert projection["execution_contracts"] == [session.execution_contract]
        if role == "pm":
            assert "objective_evidence" not in projection


def test_oversized_feedback_does_not_clip_fixed_execution_conditions():
    session = contract_session()
    session.feedback["experience"]["reason"] = "very long rating reason " * 10000
    l1 = build_l1_summary(session)
    assert l1["execution_contracts"][0] == session.execution_contract
    assert l1["execution_contracts"][0]["task_budget_seconds"] == 7200
    assert len(l1["feedback_events"][0]["reason"]) <= 1200


def test_missing_experience_remains_in_pm_discovery_index(tmp_path):
    session = contract_session()
    store = SessionStore(tmp_path / "sessions")
    store.save(session)
    pm = Divergent(FakeTracker(), store, str(tmp_path), str(tmp_path / "pm"))
    trend = pm._feeling_trend()
    assert trend[0][1] is None
    assert "unavailable" in pm._format_trend(trend)
    assert pm._goal_index(trend)[0]["execution_contracts"] == [session.execution_contract]


def test_actual_role_runtime_receives_granted_contracts_even_for_owner(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import nexau

    from ahe_beta.demand.agent_runtime import run_agent_def
    from ahe_beta.observations.grants import grant

    session = contract_session()
    store = SessionStore(tmp_path / "sessions")
    store.save(session)
    grant(store=store, issue=7, sessions={session.session_id})
    received = []

    class Config:
        @staticmethod
        def from_yaml(**kwargs):
            return SimpleNamespace(max_iterations=1, resolved_tracer=None)

    class Agent:
        def __init__(self, *, config):
            pass

        def run(self, *, message):
            received.append(message)
            return {"decisions": []}

    monkeypatch.setattr(nexau, "AgentConfig", Config)
    monkeypatch.setattr(nexau, "Agent", Agent)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("test")
    for role in ("owner", "architect", "divergent", "triager"):
        with bind_usage_context(session_id=session.session_id):
            run_agent_def(
                agent_dir,
                "proposal text " * 1000,
                store=store,
                repo=tmp_path,
                role=role,
                timeout=5,
                source_issue_ids={7},
                allowed_session_ids={session.session_id},
            )
    assert len(received) == 4
    assert all(session.execution_contract["contract_id"] in text for text in received)
    assert all('"followup_input": "unavailable"' in text for text in received)
