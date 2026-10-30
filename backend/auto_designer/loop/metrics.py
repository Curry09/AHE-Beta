"""metrics（spec-0003/T6，曲线口径 spec-0025/T7）：统计体感与 issue backlog 随时间的曲线。

只读、不自建存储（避免与权威源双写漂移）。feeling_trend 取每局体感分与时间（本地 SessionStore）；
issue_curve 取**可执行 backlog** 随时间（Gitea 全状态 issue 的开/关事件）。benchmark 不进入任何
run_round 决策，仅作旁路观测，不在此投票。

issue_curve 口径（Spec-0025/T7）：只数「可执行 backlog」= 未关闭的 triaged issue + RFC，排除
needs-triage（未处理）与 rejected / needs-info（已否）与 superseded（被 RFC 取代）。曲线的
「积压不降」正是 CLAUDE.md 要看的退化信号（issue 长期不下降 = harness 在退化）。需 tracker 的全状态
读能力（list_issues，带 created_at/closed_at/labels）；无则回退空序列（本地 SessionStore 不含标签/
关闭时间，给不出 backlog 口径）。
"""

from __future__ import annotations

from auto_designer.demand.issue_schema import (
    PROPOSAL,
    READY,
    REPORT,
    is_backlog_by_labels,
    plane,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore


class Metrics:
    """从 Gitea 与本地 session 统计观测曲线（MVP 仅消费本地 SessionStore 索引）。"""

    def __init__(self, tracker: IssueTracker, store: SessionStore) -> None:
        self._tracker = tracker
        self._store = store

    def feeling_trend(self) -> list[tuple[str, int]]:
        """体感随时间：[(created_at, score)]，按时间升序。空数据源返回空序列。"""
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
        """可执行 backlog ~ 时间：[(timestamp, delta, backlog)]，backlog 为该时刻累计未关闭的
        triaged + RFC 数（含跨轮积压）。口径见模块 docstring（Spec-0025/T7）。

        从 tracker 全状态 issue 的开/关事件累计：每条可执行 backlog issue 在 created_at 计 +1、
        （若已关）在 closed_at 计 -1，按时间排序后滚动求和。用「当前/最终标签」判定它是否属可执行
        backlog（MVP 近似：不重建历史标签轨迹）。tracker 无 list_issues 能力（Fake / 无 Gitea）或
        读取失败 → 空序列（不抛）。
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
        """当前 open issue 数（从 tracker 读路径取一个即时点，供观测）。"""
        return len(self._tracker.list_open_issues())

    def funnel(self) -> dict[str, int]:
        """三平面漏斗当前量（Spec-0029/T9）：open 票按 plane 计数 report/proposal/ready。

        proposal 深度对应「准入太严或生成太滥」、ready 深度对应「dev 消化不动=退化信号」——
        与 run.py 背压告警同口径。tracker 读失败返回全 0（观测降级不抛）。
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
