# Spec-0029/T5：divergent PM = discovery 轨生成器——从原始会话行为挖没被提为 issue 的能力缺口。
"""Divergent PM 驱动器：与 synthesize **不同料**的另一轨（Spec-0029 双轨分工）。

synthesize（delivery 轨）吃规范化 backlog 找结构根因；divergent（discovery 轨）**直吃会话第一手
证据**——体感曲线（分+理由+session 句柄）作索引、get_session_timeline/beat/step 按需下钻原始会话
行为，找「用户没提为 issue、却用对话行为反复补出来的工作方式」（自拟规程、绕路、反复手动交接）。
不吃 triaged backlog / runtime_agg（那是 delivery 轨信号）；开放提案/ready 紧凑索引仅作「勿重复」
参照。产出落 proposal 平面 + from-divergent（不可领；进 ready 由 Owner 准入裁决），每轮硬顶 3 条。
不依赖 triage 产出 → 编排上与 triage 同拍并行（Spec-0029/T8 第一拍）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import norm_label, read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    FROM_DIVERGENT,
    PROPOSAL,
    READY,
    plane,
    round_label,
)
from auto_designer.designer.issue_schema import fields_of as _schema_fields_of
from auto_designer.designer.issue_schema import render as _schema_render
from auto_designer.designer.issue_schema import validate as _schema_validate
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_DIVERGENT_TIMEOUT = 3600
# 每轮硬顶，防灌单（跨轮去重/合并由 Owner 准入做）。
_MAX_CANDIDATES = 3

StatusFn = Callable[..., None]


@dataclass
class DivergentOutcome:
    """一次 propose_once：新落的候选票号。"""

    proposal_numbers: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


def _rfc_fields_by_label(fields: dict) -> dict:
    label_to_key = {norm_label(f.label): f.key for f in _schema_fields_of(kind="rfc")}
    return {label_to_key.get(norm_label(k), str(k)): v for k, v in fields.items()}


class Divergent:
    """发散 PM：从会话行为产能力候选（proposal 平面），不碰 git、不改 harness 文件。"""

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
        # 「勿重复」参照：当前 open 的提案 + ready 项（紧凑索引，不喂正文细节）。
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
        for item in parsed:
            if not item.get("title"):
                continue
            fields = _rfc_fields_by_label(
                item.get("fields") if isinstance(item.get("fields"), dict) else {}
            )
            if _schema_validate(kind="rfc", fields=fields, section="triage"):
                continue  # 字段没填全 → 跳过（不落半成品候选）
            body = _schema_render(kind="rfc", fields=fields)
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
        return DivergentOutcome(proposal_numbers=numbers)

    def _run_agent(self, *, trend: list[tuple[str, int, str, str]], reference: list) -> str:
        rfc_labels = "/".join(f.label for f in _schema_fields_of(kind="rfc"))
        msg = (
            "你是 divergent PM（discovery 轨）：**从原始会话行为里**挖用户可感知的产品能力机会——"
            "尤其是用户没提为 issue、却用对话行为反复补出来的工作方式（自拟规程、绕路、手动交接）。\n"
            "**你的第一手证据是会话本身**：下面的体感曲线是索引（分+理由+session 句柄），对可疑的局"
            "调 `get_session_timeline(session_id=…)` 看使用事件时间线（用户追问/纠正/自拟流程都在这），"
            "某拍看不清再 `get_harness_beat(turn=…)`、必要时 `get_harness_step(turn=…, step_i=…)`；"
            "可只读 harness 仓对照「现状能力 vs 用户契约」。勿直接读 sessions/ 文件。\n"
            f"本轮最多提 {_MAX_CANDIDATES} 条**增量**候选；下面的参照列表是已有提案/工作项，"
            "**勿换皮重复其施力点**。禁止无信号空想：每条候选必须能指回具体 session 的行为证据。\n\n"
            f"## 体感曲线（索引：时间, 1-4 分, 理由, session 句柄）\n{self._format_trend(trend)}\n\n"
            f"## 已有提案/工作项（勿重复参照，{len(reference)} 条）\n{self._format_issues(reference)}\n\n"
            "调查完毕后**调 `submit_divergent` 一次**收尾：`proposals` 为 0..n 条候选（无则空数组），"
            f"每条含 `title` + `fields`（{rfc_labels}）。字段契约由工具 input_schema 强校验。"
        )
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="divergent",
            timeout=_DIVERGENT_TIMEOUT,
            on_event=self._on_event,
        )

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
        if not issues:
            return "（空）"
        # 紧凑索引：只给号/标签/标题（正文不喂——参照用，防上下文膨胀）。
        return "\n".join(f"- #{i.number} [{','.join(i.labels)}] {i.title}" for i in issues)

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
