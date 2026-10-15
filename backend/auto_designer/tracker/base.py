"""IssueTracker 协议（spec-0001/T5）：issue 提交去向的抽象，用户侧不绑定具体后端。

测试用 FakeTracker（同目录 fake.py），运行时注入 GiteaTracker（spec-0002），二者对 run_session 等价。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol, runtime_checkable

from auto_designer.models import IssueDraft, IssueRef, OpenIssue

_OPERATION_MARKER_RE = re.compile(r"<!-- auto-designer-operation:([0-9a-f]{32}):([0-9a-f]{64}) -->")


class IdempotencyConflictError(RuntimeError):
    """A stable operation key already exists with a different payload."""


def operation_marker(*, operation_key: str, payload_digest: str) -> str:
    """Return a hidden marker without exposing the original operation key."""
    key_digest = hashlib.sha256(operation_key.encode()).hexdigest()[:32]
    return f"<!-- auto-designer-operation:{key_digest}:{payload_digest} -->"


def operation_marker_digest(*, text: str, operation_key: str) -> str | None:
    """Return the payload digest recorded for an operation, when present."""
    key_digest = hashlib.sha256(operation_key.encode()).hexdigest()[:32]
    return next(
        (
            payload_digest
            for marker_key, payload_digest in _OPERATION_MARKER_RE.findall(text)
            if marker_key == key_digest
        ),
        None,
    )


def issue_payload_digest(draft: IssueDraft) -> str:
    """Return the digest used to detect operation-key payload conflicts."""
    body = json.dumps(draft.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


@runtime_checkable
class IssueTracker(Protocol):
    """issue 后端契约（结构化子类型）。number 由后端单调发号，语义对齐 Gitea。"""

    def ensure_labels(self, names: list[str]) -> None:
        """确保给定标签均存在。幂等；空列表为 no-op。"""
        ...

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        """按 draft 建 issue，返回带号回执 IssueRef（初始 state="open"）。不去重。"""
        ...

    def create_issue_once(self, draft: IssueDraft, *, operation_key: str) -> IssueRef:
        """Create once by stable operation key; reconcile an existing matching issue."""
        ...

    def list_open_issues(self) -> list[OpenIssue]:
        """读路径：列出当前 open 的 issue（供开发者侧 spec-0003/T3 领取）。无则空列表。"""
        ...

    def get_issue(self, *, number: int) -> dict[str, Any]:
        """Read current title, body, state and label names, including closed issues."""
        ...

    def add_comment(self, number: int, body: str) -> None:
        """向指定 issue 追加评论。number 不存在抛 KeyError。"""
        ...

    def add_comment_once(self, number: int, body: str, *, operation_key: str) -> None:
        """Append a comment once by stable operation key."""
        ...

    def set_state(self, number: int, state: str, reason: str) -> None:
        """改状态。state ∈ {open, closed}，非法抛 ValueError；number 不存在抛 KeyError。"""
        ...

    def set_labels(self, number: int, labels: list[str]) -> None:
        """整组替换某 issue 的标签为 labels（Spec-0025/T3a：triage 去 needs-triage 加 triaged 用）。

        替换语义（非增量）——调用方自己算好目标标签集。未知标签先 ensure 存在。number 不存在抛 KeyError。
        """
        ...

    def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
        """以一个可重试语义操作替换标题、正文和标签；后端分步实现必须失败回滚。"""
        ...

    def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
        """以一个可重试语义操作替换状态与标签；后端分步实现必须失败回滚。"""
        ...
