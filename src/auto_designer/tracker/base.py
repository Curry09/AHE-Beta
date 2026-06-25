"""IssueTracker 协议（spec-0001/T5）：issue 提交去向的抽象，用户侧不绑定具体后端。

测试用 FakeTracker（同目录 fake.py），运行时注入 GiteaTracker（spec-0002），二者对 run_session 等价。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from auto_designer.models import IssueDraft, IssueRef


@runtime_checkable
class IssueTracker(Protocol):
    """issue 后端契约（结构化子类型）。number 由后端单调发号，语义对齐 Gitea。"""

    def ensure_labels(self, names: list[str]) -> None:
        """确保给定标签均存在。幂等；空列表为 no-op。"""
        ...

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        """按 draft 建 issue，返回带号回执 IssueRef（初始 state="open"）。不去重。"""
        ...

    def add_comment(self, number: int, body: str) -> None:
        """向指定 issue 追加评论。number 不存在抛 KeyError。"""
        ...

    def set_state(self, number: int, state: str, reason: str) -> None:
        """改状态。state ∈ {open, closed}，非法抛 ValueError；number 不存在抛 KeyError。"""
        ...
