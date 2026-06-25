"""spec-0003/T6：Metrics 观测曲线单测（从本地 SessionStore 索引派生）。"""

from __future__ import annotations

from datetime import datetime

from auto_designer.loop.metrics import Metrics
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


def _session(score: int, n_issues: int, day: int) -> Session:
    return Session(
        persona=Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s"),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=score, reason="r"),
        issue_refs=[IssueRef(number=i + 1, url=f"u{i}", state="open") for i in range(n_issues)],
        created_at=datetime(2026, 6, day, 12, 0, 0),
    )


def _store(tmp_path, sessions) -> SessionStore:
    store = SessionStore(tmp_path)
    for s in sessions:
        store.save(s)
    return store


def test_feeling_trend_sorted(tmp_path) -> None:
    store = _store(tmp_path, [_session(2, 1, 3), _session(4, 0, 1)])
    m = Metrics(FakeTracker(), store)
    trend = m.feeling_trend()
    assert [score for _, score in trend] == [4, 2]  # 按时间升序（day1=4, day3=2）


def test_issue_curve_cumulative(tmp_path) -> None:
    store = _store(tmp_path, [_session(3, 2, 1), _session(3, 1, 2), _session(3, 0, 3)])
    m = Metrics(FakeTracker(), store)
    curve = m.issue_curve()
    assert [(opened, net) for _, opened, net in curve] == [(2, 2), (1, 3), (0, 3)]


def test_empty_store(tmp_path) -> None:
    m = Metrics(FakeTracker(), SessionStore(tmp_path))
    assert m.feeling_trend() == []
    assert m.issue_curve() == []


def test_open_issue_count(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="a", body="b"))
    tracker.create_issue(IssueDraft(title="c", body="d"))
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.open_issue_count() == 2
