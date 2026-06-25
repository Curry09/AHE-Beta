"""metrics（spec-0003/T6）：从本地 SessionStore 统计 issue 数量与体感随时间的曲线。

只读、不自建存储（避免与权威源双写漂移）。feeling_trend 取每局体感分与时间；issue_curve 取每局
新产 issue 数与累计净值。benchmark 不进入任何 run_round 决策，仅作旁路观测，不在此投票。

MVP 说明：本地 SessionStore 只记录每局「新产 issue 数」（n_issues），不记录 issue 关闭时间戳，
故 issue_curve 给出 (created_at, opened, net_open=累计 opened)；带 closed 的完整开/关曲线需 Gitea
带时间戳的 issue 列表，待 IssueTracker 扩读路径后补（held-out 观测不受影响）。
"""

from __future__ import annotations

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
        return [(e["created_at"], e["score"]) for e in rows]

    def issue_curve(self) -> list[tuple[str, int, int]]:
        """issue 数~时间：[(created_at, opened, net_open)]，net_open 为累计 opened。空则空序列。"""
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        curve: list[tuple[str, int, int]] = []
        net = 0
        for e in rows:
            opened = e["n_issues"]
            net += opened
            curve.append((e["created_at"], opened, net))
        return curve

    def open_issue_count(self) -> int:
        """当前 open issue 数（从 tracker 读路径取一个即时点，供观测）。"""
        return len(self._tracker.list_open_issues())
