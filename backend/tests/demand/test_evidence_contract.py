"""Spec-0055 deterministic evidence projection and role visibility tests."""

from __future__ import annotations

from pathlib import Path

from auto_designer.demand import issue_schema as sc
from auto_designer.demand.divergent import Divergent
from auto_designer.demand.evidence_contract import (
    EvidenceLevel,
    build_evidence_envelope,
    build_l1_summary,
    project_for_role,
    validate_envelope,
    validate_role_access,
)
from auto_designer.demand.owner import Owner
from auto_designer.demand.session_timeline import (
    bind_session_store,
    get_harness_beat,
    get_session_timeline,
)
from auto_designer.demand.triage import Triager
from auto_designer.models import (
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
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore


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
    synth = project_for_role(envelope, "synthesizer")
    owner = project_for_role(envelope, "owner")
    assert triage["source_report"]["issue_id"] == 7
    assert "goal_summary" in triage["user_evidence"]
    assert triage["objective_evidence"]["status"] == "failed"
    assert "source_report" not in pm and "user_evidence" in pm
    assert set(synth) <= {"level", "session_id", "evidence_refs"}
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
    assert validate_role_access(role="synthesizer", level="L4")[0] is False
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

    monkeypatch.setattr("auto_designer.demand.triage.run_agent_def", fake_run)
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
