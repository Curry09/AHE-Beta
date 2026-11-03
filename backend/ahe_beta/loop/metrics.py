"""Observe user experience and issue backlog over time (spec-0003/T6; definitions in spec-0025/T7).

This module is read-only and creates no storage, avoiding duplicate writes that could diverge
from authoritative data. feeling_trend reads session experience scores and timestamps from
local SessionStore. issue_curve derives **executable backlog** from open/close events across
all Gitea issue states. Benchmark results are observational only and never influence run_round.

Spec-0025/T7 defines executable backlog as unclosed triaged issues + RFCs. It excludes
needs-triage (pending), rejected / needs-info (declined), and superseded (replaced by an RFC).
CLAUDE.md treats a persistently non-decreasing backlog as a harness degradation signal.
This requires list_issues with created_at/closed_at/labels for all issue states. If the tracker
cannot supply them, return an empty sequence: local SessionStore lacks labels and closure
timestamps, so it cannot calculate this backlog measure.
"""

from __future__ import annotations

from ahe_beta.demand.issue_schema import (
    PROPOSAL,
    READY,
    REPORT,
    is_backlog_by_labels,
    plane,
)
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.user.session_store import SessionStore


class Metrics:
    """Compute observation curves from Gitea and local sessions (MVP only consumes local SessionStore index)."""

    def __init__(self, tracker: IssueTracker, store: SessionStore) -> None:
        self._tracker = tracker
        self._store = store

    def feeling_trend(self) -> list[tuple[str, int]]:
        """Subjective experience over time: [(created_at, score)], sorted in ascending order by time. Returns empty sequence for empty data sources."""
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        return [(e["created_at"], e["score"]) for e in rows if type(e.get("score")) is int]

    def feedback_counts(self) -> dict[str, dict[str, int]]:
        """Spec-0084/T1: retain denominator and missing observations by input condition."""
        groups: dict[str, dict[str, int]] = {}
        for row in self._store.index(include_invalid=True):
            group = groups.setdefault(
                row.get("followup_input", "unknown"),
                {"rated": 0, "missing": 0, "invalid": 0, "unavailable": 0},
            )
            status = row.get(
                "experience_status", "rated" if type(row.get("score")) is int else "missing"
            )
            group[status] = group.get(status, 0) + 1
        return groups

    def issue_curve(self) -> list[tuple[str, int, int]]:
        """Executable backlog over time: [(timestamp, delta, backlog)], where backlog is the cumulative count of unclosed
        triaged + RFC items at that moment (including cross-round carry-over). See specification in module docstring (Spec-0025/T7).

        Accumulated from open/close events across all tracker issue states: each executable backlog issue counts +1 at created_at,
        and -1 at closed_at (if closed), then sorted by time and rolled-up. Uses current/final labels to determine if it belongs to
        executable backlog (MVP approximation: does not reconstruct historical label trajectories). If tracker lacks list_issues capability
        (Fake / no Gitea) or read fails → returns empty sequence (does not raise).
        """
        fetch_all = getattr(self._tracker, "list_issues", None)
        if not callable(fetch_all):
            return []
        try:
            issues = fetch_all(state="all")
        except Exception:
            return []
        events: list[tuple[str, int]] = []
        for it in issues:
            if not is_backlog_by_labels(it.get("labels") or []):
                continue
            created = it.get("created_at") or ""
            if created:
                events.append((created, 1))
            closed = it.get("closed_at")
            if closed:
                events.append((closed, -1))
        events.sort(key=lambda e: e[0])
        curve: list[tuple[str, int, int]] = []
        backlog = 0
        for ts, delta in events:
            backlog += delta
            curve.append((ts, delta, backlog))
        return curve

    def open_issue_count(self) -> int:
        """Current open issue count (read from tracker at a single point in time for observability)."""
        return len(self._tracker.list_open_issues())

    def funnel(self) -> dict[str, int]:
        """Count open issues in each plane: report/proposal/ready (Spec-0029/T9).

        A deep proposal queue suggests overly strict admission or excessive generation; a deep ready
        queue suggests developers cannot keep up, a degradation signal. These definitions match the
        backpressure alerts in run.py. Return all zeros if tracker reads fail; observation failure
        does not raise.
        """
        counts = {"report": 0, "proposal": 0, "ready": 0}
        try:
            open_issues = self._tracker.list_open_issues()
        except Exception:  # noqa: BLE001
            return counts
        keymap = {REPORT: "report", PROPOSAL: "proposal", READY: "ready"}
        for i in open_issues:
            key = keymap.get(plane(i.labels))
            if key is not None:
                counts[key] += 1
        return counts
