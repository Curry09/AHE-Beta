"""spec-0001/T1：用户侧数据模型的序列化与不变量单测。"""

from __future__ import annotations

from datetime import datetime

import pytest

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
    Turn,
)


def _persona() -> Persona:
    return Persona(
        identity="后端工程师",
        level="资深",
        domain="分布式系统",
        goal="排查一个偶发超时",
        speaking_style="简短、技术化",
    )


def _session() -> Session:
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="帮我定位偶发 504"),
        transcript=Transcript(
            turns=[Turn("user", "504 偶发"), Turn("harness", "看下上游超时配置")]
        ),
        feeling=FeelingScore(score=3, reason="有帮助但绕了一圈"),
        issue_refs=[IssueRef(number=1, url="fake://issues/1", state="open")],
        sim_trace=SimTrace(
            persona_id="P-1",
            end_reason="issue_filed",
            turns=[
                SimTurn(
                    turn=0,
                    phase="active",
                    action_space=["send_message"],
                    perceive="还是偶发",
                    verdict="failed_blame_harness",
                    action="file_issue",
                    message="帮我定位偶发 504",
                    executor="harness",
                    channel="emit",
                    patience=2,
                    trust="skeptical",
                    harness_output="看下上游超时配置",
                )
            ],
            signals=["WAIT_GAP: intent=peek action=keep_waiting"],
            feeling_derived=FeelingScore(score=2, reason="框架派生"),
        ),
    )


@pytest.mark.parametrize(
    "obj",
    [
        _persona(),
        SeedScenario(description="x"),
        Turn("user", "hi"),
        Transcript(turns=[Turn("user", "a"), Turn("harness", "b")]),
        FeelingScore(score=4, reason="很顺"),
        IssueDraft(title="t", body="b", labels=["bug"]),
        IssueRef(number=7, url="fake://issues/7", state="closed"),
        SimTurn(
            turn=1,
            phase="waiting",
            action_space=["keep_waiting"],
            perceive="[stuck|peek→keep_waiting] 还在转",
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
    """每个 dataclass to_dict→from_dict 后字段级一致。"""
    assert type(obj).from_dict(obj.to_dict()) == obj


def test_session_round_trip_nested() -> None:
    """嵌套 Session（含 transcript/feeling/issue_refs/sim_trace）round-trip 一致，datetime 可逆。"""
    s = _session()
    d = s.to_dict()
    assert isinstance(d["created_at"], str)
    datetime.fromisoformat(d["created_at"])  # ISO-8601 可解析
    assert "sim_trace" in d
    assert d["sim_trace"]["turns"][0]["perceive"] == "还是偶发"
    assert Session.from_dict(d) == s


def test_session_round_trip_objective_audit_fields() -> None:
    session = _session()
    session.accept_validity = "valid_accept"
    session.audit_events = [
        {"seq": 1, "event": "container_started", "at": "2026-09-02T00:00:00+00:00"}
    ]
    assert Session.from_dict(session.to_dict()) == session


def test_session_without_sim_trace_omits_key_and_loads_none() -> None:
    """旧 JSON 无 sim_trace → from_dict 得 None；新 Session 无 trace 时 to_dict 不落该键。"""
    s = Session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=2, reason="一般"),
    )
    assert "sim_trace" not in s.to_dict()
    loaded = Session.from_dict(
        {
            "session_id": "abc",
            "created_at": datetime.now().isoformat(),
            "persona": _persona().to_dict(),
            "scenario": {"description": "x"},
            "transcript": {"turns": []},
            "feeling": {"score": 2, "reason": "一般"},
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
    """体感分越界（0/5）构造期断言失败。"""
    for bad in (0, 5):
        with pytest.raises(AssertionError):
            FeelingScore(score=bad, reason="x")


def test_transcript_role_rejected() -> None:
    """Transcript role ∉ {user, harness} 被拒（构造期）。"""
    with pytest.raises(AssertionError):
        Turn(role="system", content="x")


def test_defaults_empty_lists() -> None:
    """IssueDraft.labels 与 Session.issue_refs 缺省空列表。"""
    assert IssueDraft(title="t", body="b").labels == []
    s = Session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=2, reason="一般"),
    )
    assert s.issue_refs == []


def test_from_dict_ignores_unknown_keys() -> None:
    """from_dict 遇未知键忽略不报错（前向兼容）。"""
    d = FeelingScore(score=3, reason="ok").to_dict()
    d["__future_field__"] = 123
    assert FeelingScore.from_dict(d) == FeelingScore(score=3, reason="ok")
