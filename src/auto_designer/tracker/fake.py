"""FakeTracker（spec-0001/T5）：IssueTracker 的内存实现，供单测与无 Gitea 环境端到端跑通。

发号自 1 起单调递增（每实例独立计数，对齐 Gitea 实例内自增）；语义对齐 Gitea 但无网络/持久化。
"""

from __future__ import annotations

from typing import Any

from auto_designer.models import ISSUE_STATES, IssueDraft, IssueRef

# FakeTracker 合成 url 的占位前缀。
_URL_PREFIX = "fake://issues/"


class FakeTracker:
    """IssueTracker 的内存实现。"""

    def __init__(self) -> None:
        self._counter = 0
        self._issues: dict[int, dict[str, Any]] = {}
        self._labels: set[str] = set()

    def ensure_labels(self, names: list[str]) -> None:
        self._labels.update(names)  # 幂等：set 去重；空列表 no-op

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        self._counter += 1
        number = self._counter
        self._issues[number] = {
            "title": draft.title,
            "body": draft.body,
            "labels": list(draft.labels),
            "state": "open",
            "reason": "",
            "comments": [],
        }
        return IssueRef(number=number, url=f"{_URL_PREFIX}{number}", state="open")

    def add_comment(self, number: int, body: str) -> None:
        self._require(number)["comments"].append(body)

    def set_state(self, number: int, state: str, reason: str) -> None:
        if state not in ISSUE_STATES:
            raise ValueError(f"非法 state：{state!r}（须属 {ISSUE_STATES}）")
        issue = self._require(number)
        issue["state"] = state
        issue["reason"] = reason

    def issue(self, number: int) -> dict[str, Any]:
        """只读：返回该 issue 的快照副本，供单测断言 comment/state 生效。"""
        snapshot = self._require(number)
        return {**snapshot, "labels": list(snapshot["labels"]), "comments": list(snapshot["comments"])}

    def labels(self) -> set[str]:
        """只读：当前标签集副本。"""
        return set(self._labels)

    def _require(self, number: int) -> dict[str, Any]:
        if number not in self._issues:
            raise KeyError(f"issue 不存在：#{number}")
        return self._issues[number]
