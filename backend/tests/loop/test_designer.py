# 创新者侧：Designer 综合全局产结构性提案单测（stub nexau agent + FakeTracker + 临时 SessionStore）。
"""验证 designer 驱动器：

- agent 产出的 JSON 提案被落成带 `design` 标签的 open issue（供开发者领取）；
- 提案 result 含代码块/前后散文时仍能鲁棒解析；空/非法 result 退化为「本轮无提案」不抛错；
- backlog + 体感曲线确实喂进了 agent 的任务消息。
"""

from __future__ import annotations

from pathlib import Path

from auto_designer.designer.designer import DESIGN_LABEL, Designer, DesignOutcome
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class _StubDesigner(Designer):
    """覆盖 _run_agent：不跑真 nexau，回放一段固定 result，并记录喂进的 backlog/trend。"""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_backlog: list = []
        self.seen_trend: list = []

    def _run_agent(self, *, backlog: list, trend: list) -> str:
        self.seen_backlog = backlog
        self.seen_trend = trend
        return self._canned


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _seed_session(store: SessionStore, *, score: int, reason: str = "r") -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason=reason),
        )
    )


def _designer(tmp_path: Path, tracker: FakeTracker, canned: str) -> _StubDesigner:
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store, score=2, reason="等太久")
    _seed_session(store, score=1, reason="超时两次颗粒无收")  # 体感偏低，构成一条曲线
    return _StubDesigner(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        canned=canned,
    )


def test_proposals_become_design_labeled_issues(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="慢", body="ORM 慢", labels=["bug"]))  # 已有 backlog
    canned = (
        "分析后给出提案：\n```json\n"
        '[{"title": "统一错误处理契约", "body": "多条 issue 指向缺乏统一兜底", "labels": ["design"]},'
        '{"title": "澄清前置追问策略", "body": "体感偏低源于不追问", "labels": []}]\n'
        "```\n以上。"
    )
    designer = _designer(tmp_path, tracker, canned)

    outcome = designer.propose_once()

    assert isinstance(outcome, DesignOutcome)
    assert outcome.count == 2
    # 两条提案都落成 open issue，且都带 design 标签（第二条原本没 labels 也被补上）。
    opened = {i.number: i for i in tracker.list_open_issues()}
    for number in outcome.proposal_numbers:
        assert DESIGN_LABEL in opened[number].labels
    titles = {i.title for i in opened.values()}
    assert {"统一错误处理契约", "澄清前置追问策略"} <= titles
    # backlog + 体感曲线确实喂进了 agent（曲线现在带上体感 reason 那句「为什么」）。
    assert [i.title for i in designer.seen_backlog] == ["慢"]
    assert [s for _, s, _ in designer.seen_trend] == [2, 1]
    assert [reason for _, _, reason in designer.seen_trend] == ["等太久", "超时两次颗粒无收"]


def test_empty_or_invalid_result_yields_no_proposals(tmp_path) -> None:
    tracker = FakeTracker()
    for canned in ["[]", "没有值得提的结构性方向。", ""]:
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0
    assert tracker.list_open_issues() == []  # 全程未建任何 issue
