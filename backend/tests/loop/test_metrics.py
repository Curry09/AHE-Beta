"""spec-0003/T6: Metrics observation curve unit test (derived from local SessionStore index)."""

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
    assert [score for _, score in trend] == [4, 2]  # Sorted by time ascending (day1=4, day3=2)


class _ObserveTracker(FakeTracker):
    """FakeTracker + Gitea full state read capability (list_issues with labels/timestamps), test backlog curve definition."""

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
    # Count only actionable backlog (triaged/RFC, excluding needs-triage/rejected/superseded), accumulated by open/close events.
    tracker = _ObserveTracker(
        [
            # +1 on D1, remains open (backlog accumulation)
            _issue(1, ["bug", "triaged"], "2026-06-01", None),
            _issue(2, ["feature", "triaged"], "2026-06-02", "2026-06-04"),  # +1 D2、-1 D4
            _issue(3, ["RFC"], "2026-06-03", None),  # +1 on D3 (RFC is also actionable backlog)
            _issue(4, ["bug", "needs-triage"], "2026-06-01", None),  # Exclude: untriaged
            _issue(5, ["bug", "rejected"], "2026-06-01", "2026-06-02"),  # Exclude: rejected
            # Exclude: superseded
            _issue(6, ["bug", "triaged", "superseded"], "2026-06-01", "2026-06-02"),
        ]
    )
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.issue_curve() == [
        ("2026-06-01", 1, 1),
        ("2026-06-02", 1, 2),
        ("2026-06-03", 1, 3),
        # Backlog does not drop to zero: #1, #3 remain open (signal of degradation)
        ("2026-06-04", -1, 2),
    ]


def test_issue_curve_no_list_issues_capability(tmp_path) -> None:
    # No Gitea full state read capability (Fake) → empty sequence (local store lacks labels/close times, cannot provide backlog definition).
    m = Metrics(FakeTracker(), _store(tmp_path, [_session(3, 2, 1)]))
    assert m.issue_curve() == []


def test_empty_store(tmp_path) -> None:
    m = Metrics(FakeTracker(), SessionStore(tmp_path))
    assert m.feeling_trend() == []
    assert m.issue_curve() == []


def test_funnel_counts_by_plane(tmp_path) -> None:
    """Spec-0029/T9: Three-plane funnel—count open issues by plane (old and new labels unified through plane projection)."""
    from ahe_beta.demand import issue_schema as sc

    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="r1", body="x", labels=[sc.REPORT]))
    # Old mapping
    tracker.create_issue(IssueDraft(title="r2-old", body="x", labels=[sc.NEEDS_TRIAGE]))
    tracker.create_issue(IssueDraft(title="p1", body="x", labels=[sc.PROPOSAL, sc.FROM_TRIAGE]))
    tracker.create_issue(IssueDraft(title="w1", body="x", labels=[sc.READY]))
    closed = tracker.create_issue(IssueDraft(title="w2", body="x", labels=[sc.READY])).number
    tracker.set_state(closed, "closed", "done")  # Closed issues not counted
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.funnel() == {"report": 2, "proposal": 1, "ready": 1}


def test_open_issue_count(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="a", body="b"))
    tracker.create_issue(IssueDraft(title="c", body="d"))
    m = Metrics(tracker, SessionStore(tmp_path))
    assert m.open_issue_count() == 2
