"""spec-0001/T1: User-side data model serialization and invariant unit tests."""

from __future__ import annotations

from datetime import datetime

import pytest

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
    Turn,
)


def _persona() -> Persona:
    return Persona(
        identity="Backend engineer",
        level="Senior",
        domain="Distributed systems",
        goal="Investigate an intermittent timeout",
        speaking_style="Concise、Technical",
    )


def _session() -> Session:
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="Help me diagnose intermittent 504"),
        transcript=Transcript(
            turns=[
                Turn("user", "504 Intermittent"),
                Turn("harness", "Check the upstream timeout settings"),
            ]
        ),
        feeling=FeelingScore(score=3, reason="Helpful but took a detour"),
        issue_refs=[IssueRef(number=1, url="fake://issues/1", state="open")],
        sim_trace=SimTrace(
            persona_id="P-1",
            end_reason="issue_filed",
            turns=[
                SimTurn(
                    turn=0,
                    phase="active",
                    action_space=["send_message"],
                    perceive="Still intermittent",
                    verdict="failed_blame_harness",
                    action="file_issue",
                    message="Help me diagnose intermittent 504",
                    executor="harness",
                    channel="emit",
                    patience=2,
                    trust="skeptical",
                    harness_output="Check the upstream timeout settings",
                )
            ],
            signals=["WAIT_GAP: intent=peek action=keep_waiting"],
            feeling_derived=FeelingScore(score=2, reason="Derived from framework"),
        ),
    )


@pytest.mark.parametrize(
    "obj",
    [
        _persona(),
        SeedScenario(description="x"),
        Turn("user", "hi"),
        Transcript(turns=[Turn("user", "a"), Turn("harness", "b")]),
        FeelingScore(score=4, reason="Very smooth"),
        IssueDraft(title="t", body="b", labels=["bug"]),
        IssueRef(number=7, url="fake://issues/7", state="closed"),
        SimTurn(
            turn=1,
            phase="waiting",
            action_space=["keep_waiting"],
            perceive="[stuck|peek→keep_waiting] Still spinning",
            verdict="stuck",
            action="keep_waiting",
            message="",
            executor="local",
            channel="silent",
            patience=3,
            trust="ok",
            persona_trace=[
                PersonaCallTrace(
                    role="waiting_act",
                    system="SYS",
                    user="<waiting_act>",
                    raw='{"action":"keep_waiting"}',
                    parsed={"action": "keep_waiting"},
                )
            ],
        ),
        SimTrace(persona_id="P", end_reason="accepted", turns=[], signals=[]),
        PersonaCallTrace(
            role="decide",
            system="you are a user",
            user="<task>",
            raw="{}",
            parsed={},
            steps=[{"kind": "assistant", "text": "{}"}],
        ),
    ],
)
def test_round_trip_simple(obj) -> None:
    """Each dataclass to_dict→from_dict field-level consistency after round-trip."""
    assert type(obj).from_dict(obj.to_dict()) == obj


def test_sim_trace_keeps_interaction_status_separate_from_evaluator_status() -> None:
    trace = SimTrace(
        persona_id="P",
        end_reason="evaluator_invalid",
        turns=[],
        signals=["PROTOCOL_UNRECOVERABLE"],
        evaluation_status="invalid",
        evaluation_error={"stage": "main_act", "code": "unexpected_message"},
        interaction_status="protocol_unrecoverable",
    )
    restored = SimTrace.from_dict(trace.to_dict())
    assert restored.interaction_status == "protocol_unrecoverable"
    assert restored.evaluation_status == "invalid"
    assert restored.evaluation_error == trace.evaluation_error


def test_session_round_trip_nested() -> None:
    """Nested Session (including transcript/feeling/issue_refs/sim_trace) round-trip consistency, datetime reversible."""
    s = _session()
    d = s.to_dict()
    assert isinstance(d["created_at"], str)
    datetime.fromisoformat(d["created_at"])  # ISO-8601 parseable
    assert "sim_trace" in d
    assert d["sim_trace"]["turns"][0]["perceive"] == "Still intermittent"
    assert Session.from_dict(d) == s


def test_session_round_trip_objective_audit_fields() -> None:
    session = _session()
    session.accept_validity = "valid_accept"
    session.audit_events = [
        {"seq": 1, "event": "container_started", "at": "2026-09-02T00:00:00+00:00"}
    ]
    assert Session.from_dict(session.to_dict()) == session


def test_session_without_sim_trace_omits_key_and_loads_none() -> None:
    """Legacy JSON without sim_trace → from_dict yields None; new Session without trace does not include that key in to_dict."""
    s = Session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=2, reason="Average"),
    )
    assert "sim_trace" not in s.to_dict()
    loaded = Session.from_dict(
        {
            "session_id": "abc",
            "created_at": datetime.now().isoformat(),
            "persona": _persona().to_dict(),
            "scenario": {"description": "x"},
            "transcript": {"turns": []},
            "feeling": {"score": 2, "reason": "Average"},
            "issue_refs": [],
        }
    )
    assert loaded.sim_trace is None


def test_sim_trace_evaluator_status_round_trip_and_old_default() -> None:
    invalid = SimTrace(
        persona_id="P",
        end_reason="evaluator_invalid",
        evaluation_status="invalid",
        evaluation_error={"stage": "main_act", "code": "missing_action", "attempts": 2},
    )
    assert SimTrace.from_dict(invalid.to_dict()) == invalid

    legacy = SimTrace.from_dict({"persona_id": "P", "end_reason": "accepted", "turns": []})
    assert legacy.evaluation_status == "valid"
    assert legacy.evaluation_error is None


def test_feeling_score_out_of_range() -> None:
    """Experience score out of bounds (0/5) triggers assertion failure at construction."""
    for bad in (0, 5):
        with pytest.raises(AssertionError):
            FeelingScore(score=bad, reason="x")


def test_transcript_role_rejected() -> None:
    """Transcript role ∉ {user, harness} rejected (at construction)."""
    with pytest.raises(AssertionError):
        Turn(role="system", content="x")


def test_defaults_empty_lists() -> None:
    """IssueDraft.labels and Session.issue_refs default to empty list."""
    assert IssueDraft(title="t", body="b").labels == []
    s = Session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=2, reason="Average"),
    )
    assert s.issue_refs == []


def test_from_dict_ignores_unknown_keys() -> None:
    """from_dict ignores unknown keys without error (forward compatible)."""
    d = FeelingScore(score=3, reason="ok").to_dict()
    d["__future_field__"] = 123
    assert FeelingScore.from_dict(d) == FeelingScore(score=3, reason="ok")
