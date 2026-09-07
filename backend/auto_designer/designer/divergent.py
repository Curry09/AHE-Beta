# Spec-0042/T5：Divergent 从会话行为证据识别产品能力缺口。
"""Divergent（能力发现）驱动器。

体验趋势提供检索索引，会话 timeline/beat/step 提供按需证据。开放 proposal 与 ready item 只作为
重复方向参照。输出写入 proposal 平面并标记 from-divergent；Designer 负责跨提案吸收，Owner
负责最终交接。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import read_submit, run_agent_def
from auto_designer.designer.evidence_contract import build_evidence_envelope, project_for_role
from auto_designer.designer.issue_schema import (
    FROM_DIVERGENT,
    PROPOSAL,
    READY,
    plane,
    round_label,
)
from auto_designer.designer.proposal_view import format_proposal_reference_list
from auto_designer.designer.role_contract import render_pm_artifact, validate_pm
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_DIVERGENT_TIMEOUT = 3600
# 单轮候选上限；跨提案的语义吸收由 Designer 执行。
_MAX_CANDIDATES = 3

StatusFn = Callable[..., None]


@dataclass
class DivergentOutcome:
    """一次 propose_once：新落的候选票号。"""

    proposal_numbers: list[int] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


class Divergent:
    """从会话行为形成能力 proposal，不修改代码或工作流状态。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        round_provider: Callable[[], int | None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        self._round_provider = round_provider

    def propose_once(self) -> DivergentOutcome:
        # 全量参照用于理解产品现状；PM 不因相邻价值方向停止生成，跨提案吸收由 Designer 判断。
        backlog = self._tracker.list_open_issues()
        reference = [i for i in backlog if plane(i.labels) in (PROPOSAL, READY)]
        trend = self._feeling_trend()
        self._emit(
            running=True,
            status=f"发散中…（会话={len(trend)} 局 · 参照={len(reference)} 条）",
        )

        result_text = self._run_agent(trend=trend, reference=reference)
        raw = read_submit(result_text, "proposals") or []
        parsed = raw[:_MAX_CANDIDATES]

        numbers: list[int] = []
        if parsed:
            self._tracker.ensure_labels([PROPOSAL, FROM_DIVERGENT])
        round_no = self._round_provider() if self._round_provider is not None else None
        known_sessions = {sid for _, _, _, sid in trend if sid}
        for item in parsed:
            if not item.get("title"):
                continue
            if validate_pm(item, known_sessions=known_sessions):
                continue
            body = render_pm_artifact(item)
            labels = [PROPOSAL, FROM_DIVERGENT]
            if isinstance(round_no, int) and round_no > 0:
                labels.append(round_label(round_no))
            ref = self._tracker.create_issue(
                IssueDraft(title=str(item["title"]), body=body, labels=labels)
            )
            numbers.append(ref.number)

        self._emit(
            running=False,
            status=(f"落了 {len(numbers)} 条能力候选（待准入）" if numbers else "本轮无产品候选"),
            proposals=numbers,
            detail=(result_text or None),
        )
        return DivergentOutcome(proposal_numbers=numbers, artifacts=[dict(item) for item in parsed])

    def _run_agent(self, *, trend: list[tuple[str, int, str, str]], reference: list) -> str:
        # The global PM view is an index of compact, deterministic projections.
        # It deliberately does not concatenate raw timeline/step output.
        known_sessions = {sid for _, _, _, sid in trend if sid}
        goal_index = self._goal_index(trend)
        msg = (
            "你是产品 PM。以下是全部可见的用户体验索引以及开放 proposal、ready item。先理解用户"
            "试图完成什么、行为反映了什么体验矛盾，再提出产品机会。已有提案是产品现状上下文，"
            "重叠不构成生成失败，合并取舍由后续 Designer 负责。"
            "再以 session 标识调用 get_session_timeline 核实；仅在必要时继续调用 beat 和 step。"
            "不得直接读取 sessions 文件。\n"
            f"本轮最多提交 {_MAX_CANDIDATES} 条产品洞察。每条必须能追溯到具体会话证据。\n\n"
            f"## 体感曲线（索引：时间, 1-4 分, 理由, session 句柄）\n{self._format_trend(trend)}\n\n"
            "## 目标感知体验摘要（确定性 L1；只保留目标、关键动作和反馈）\n"
            f"{self._format_goal_index(goal_index)}\n\n"
            f"## 已有 proposal / ready item（{len(reference)} 条）\n{self._format_issues(reference)}\n\n"
            "调查完成后调用 `submit_divergent` 一次：`proposals` 为 0..n 条（无则空数组），"
            "每条分别说明 user_goal、observed_behaviors、experience_tension、product_opportunity、"
            "desired_outcome、evidence_sessions、solution_level、abstraction_rationale，可选"
            " related_proposals。字段契约由工具强校验。"
        )
        from auto_designer.usage import current_usage_context  # noqa: PLC0415

        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="divergent",
            timeout=_DIVERGENT_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "round", "id": str(current_usage_context().round_no or "")},
            evidence={
                "default_level": "L1",
                "allowed_levels": ["L2", "L3"],
                "session_count": len(goal_index),
                "session_ids": [
                    str(row.get("session_id")) for row in goal_index if row.get("session_id")
                ],
            },
            allowed_session_ids=known_sessions,
        )

    def _goal_index(self, trend: list[tuple[str, int, str, str]]) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for _ts, _score, _reason, session_id in trend:
            if not session_id:
                continue
            if session_id in seen:
                continue
            seen.add(session_id)
            try:
                session = self._store.load(session_id)
            except FileNotFoundError:
                continue
            try:
                envelope = self._store.load_user_feedback_envelope(session_id)
            except FileNotFoundError:
                envelope = build_evidence_envelope(session).to_dict()
            rows.append(project_for_role(envelope, "pm"))
        return rows

    @staticmethod
    def _format_goal_index(rows: list[dict]) -> str:
        import json

        if not rows:
            return "（暂无目标证据；旧 session 或缺失 session 明确不补猜）"
        return json.dumps(rows, ensure_ascii=False, indent=2)

    def _feeling_trend(self) -> list[tuple[str, int, str, str]]:
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        return [
            (
                e["created_at"],
                e["score"],
                str(e.get("reason", "")),
                str(e.get("session_id", "")),
            )
            for e in rows
        ]

    @staticmethod
    def _format_issues(issues: list) -> str:
        return format_proposal_reference_list(issues)

    @staticmethod
    def _format_trend(trend: list[tuple[str, int, str, str]]) -> str:
        if not trend:
            return "（暂无体感数据）"
        lines = []
        for ts, score, reason, sid in trend:
            why = f" — {reason}" if reason else ""
            sid_bit = f" [session={sid}]" if sid else ""
            lines.append(f"- {ts}{sid_bit}: {score}{why}")
        return "\n".join(lines)

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
