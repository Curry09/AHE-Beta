"""spec-0001/T1：用户侧数据模型的序列化与不变量单测。"""

from __future__ import annotations

from datetime import datetime

import pytest

from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
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
    ],
)
def test_round_trip_simple(obj) -> None:
    """每个 dataclass to_dict→from_dict 后字段级一致。"""
    assert type(obj).from_dict(obj.to_dict()) == obj


def test_session_round_trip_nested() -> None:
    """嵌套 Session（含 transcript/feeling/issue_refs）round-trip 一致，datetime 可逆。"""
    s = _session()
    d = s.to_dict()
    assert isinstance(d["created_at"], str)
    datetime.fromisoformat(d["created_at"])  # ISO-8601 可解析
    assert Session.from_dict(d) == s


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
