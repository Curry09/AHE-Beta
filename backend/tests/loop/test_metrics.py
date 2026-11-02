"""spec-0003/T6：Metrics 观测曲线单测（从本地 SessionStore 索引派生）。"""

from __future__ import annotations

from datetime import datetime

from ahe_beta.loop.metrics import Metrics
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore


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


class _ObserveTracker(FakeTracker):
    """FakeTracker + Gitea 全状态读能力（list_issues 带 labels/时间戳），测 backlog 曲线口径。"""

    def __init__(self, issues: list[dict]) -> None:
        super().__init__()
        self._all = issues

    def list_issues(self, *, state: str = "all", limit: int = 100):
        assert state == "all"
        return list(self._all)


def _issue(number: int, labels: list[str], created: str, closed: str | None) -> dict:
    return {
        "number": number,
        "labels": labels,
        "state": "closed" if closed else "open",
        "created_at": created,
        "closed_at": closed,
    }


def test_issue_curve_executable_backlog(tmp_path) -> None:
    # 只数可执行 backlog（triaged/RFC，排除 needs-triage/rejected/superseded），按开/关事件累计。
    tracker = _ObserveTracker(
        [
            _issue(1, ["bug", "triaged"], "2026-06-01", None),  # +1 D1，一直挂着（积压）
            _issue(2, ["feature", "triaged"], "2026-06-02", "2026-06-04"),  # +1 D2、-1 D4
            _issue(3, ["RFC"], "2026-06-03", None),  # +1 D3（RFC 也是可执行 backlog）
            _issue(4, ["bug", "needs-triage"], "2026-06-01", None),  # 排除：未 triage
            _issue(5, ["bug", "rejected"], "2026-06-01", "2026-06-02"),  # 排除：已驳回
            _issue(6, ["bug", "triaged", "superseded"], "2026-06-01", "2026-06-02"),  # 排除：被取代
        ]
    )
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.issue_curve() == [
        ("2026-06-01", 1, 1),
        ("2026-06-02", 1, 2),
        ("2026-06-03", 1, 3),
        ("2026-06-04", -1, 2),  # 积压不降回 0：#1、#3 仍挂着（退化信号）
    ]


def test_issue_curve_no_list_issues_capability(tmp_path) -> None:
    # 无 Gitea 全状态读能力（Fake）→ 空序列（本地不含标签/关闭时间，给不出 backlog 口径）。
    m = Metrics(FakeTracker(), _store(tmp_path, [_session(3, 2, 1)]))
    assert m.issue_curve() == []


def test_empty_store(tmp_path) -> None:
    m = Metrics(FakeTracker(), SessionStore(tmp_path))
    assert m.feeling_trend() == []
    assert m.issue_curve() == []


def test_funnel_counts_by_plane(tmp_path) -> None:
    """Spec-0029/T9：三平面漏斗——open 票按 plane 计数（新旧标签统一经 plane 投影）。"""
    from ahe_beta.demand import issue_schema as sc

    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="r1", body="x", labels=[sc.REPORT]))
    tracker.create_issue(IssueDraft(title="r2-old", body="x", labels=[sc.NEEDS_TRIAGE]))  # 旧映射
    tracker.create_issue(IssueDraft(title="p1", body="x", labels=[sc.PROPOSAL, sc.FROM_TRIAGE]))
    tracker.create_issue(IssueDraft(title="w1", body="x", labels=[sc.READY]))
    closed = tracker.create_issue(IssueDraft(title="w2", body="x", labels=[sc.READY])).number
    tracker.set_state(closed, "closed", "done")  # 已关不计
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.funnel() == {"report": 2, "proposal": 1, "ready": 1}


def test_open_issue_count(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="a", body="b"))
    tracker.create_issue(IssueDraft(title="c", body="d"))
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.open_issue_count() == 2
