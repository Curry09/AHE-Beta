# Spec-0042/T5：Synthesize 在规范化 ProposalView 上形成结构提案。
"""Synthesize 驱动器。

该角色读取 ready queue、开放 ProposalView、体验趋势与运行时聚合，按需检索会话证据并只读检查
harness 现状。输出写入 proposal 平面并标记 from-synthesize。`covers` 仅表达 merge 建议；Owner
拥有准入和合并裁决权。Designer 类名及 RFC 相关机器标识保留用于兼容现有接口。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    FROM_SYNTHESIZE,
    PROPOSAL,
    READY,
    REPORT,
    RFC_LABEL,
    format_covers_line,
    plane,
    round_label,
)
from auto_designer.designer.proposal_view import format_proposal_list
from auto_designer.designer.role_contract import render_synthesis_artifact, validate_synthesis
from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# 向后兼容别名；现行业务术语为“结构提案”。
DESIGN_LABEL = RFC_LABEL
# 一次 propose_once 是多轮工具调用（读文件 + 综合 + 按需 timeline/beat/step 渐进下钻）；给足墙钟防挂死。
_DESIGN_TIMEOUT = 3600

StatusFn = Callable[..., None]


@dataclass
class DesignOutcome:
    """一次 propose_once 的结果：产出的提案 issue 号列表。"""

    proposal_numbers: list[int] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


@dataclass(frozen=True)
class _Proposal:
    """解析后的结构提案：标题、规范化字段和 merge 建议。"""

    title: str
    artifact: dict
    covers: tuple[int, ...] = ()


def _parse_covers(raw: object) -> tuple[int, ...]:
    """提案的 covers 字段 → 去重正整数元组；非列表/非法元素静默丢弃（宽进严出）。"""
    if not isinstance(raw, list):
        return ()
    out: list[int] = []
    for x in raw:
        # bool 是 int 子类，需显式排除（True 会被当 #1）。
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            continue
        if x not in out:
            out.append(x)
    return tuple(out)


class Designer:
    """synthesize nexau agent 驱动器：综合全局 → 产结构提案（proposal 平面，待 Owner 准入）。"""

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
        self._store = store  # 体感曲线数据源（本地 SessionStore 索引）
        self._repo = Path(harness_repo)  # 只读 grounding：agent 看 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = (
            on_event  # 过程流回调 (kind, text)：assistant 发言/工具调用/结果，看板时间线用
        )
        self._round_provider = round_provider

    def propose_once(self) -> DesignOutcome:
        backlog = self._tracker.list_open_issues()
        # Spec-0029/T4：输入 = ready 工作队列 + 待准入提案索引（编排保证跑在本轮 triage 之后，
        # 索引因此含本轮新升的 from-triage 提案）。提案索引兼作「勿重复提」参照。
        ready = [i for i in backlog if plane(i.labels) == READY]
        proposals_open = [i for i in backlog if plane(i.labels) == PROPOSAL]
        trend = self._feeling_trend()
        # 任务无关机制层数字：扫已落盘 steps/reply + 仓内预算钮（delivery 轨信号，divergent 不吃）。
        runtime = format_runtime_agg(aggregate_runtime(store=self._store, harness_repo=self._repo))
        self._emit(
            running=True,
            status=f"综合中…（ready={len(ready)} · 待准入提案={len(proposals_open)}）",
        )

        result_text = self._run_agent(
            ready=ready, proposals=proposals_open, trend=trend, runtime=runtime
        )
        parsed = self._proposals_from_submit(result_text)

        # covers 只是建议：过滤到当前 open 的 report/proposal 票号（合并裁决在 Owner 准入时）。
        coverable = {i.number for i in backlog if plane(i.labels) in (REPORT, PROPOSAL)}
        visible_proposals = {i.number for i in [*ready, *proposals_open]}
        numbers: list[int] = []
        round_no = self._round_provider() if self._round_provider is not None else None
        round_name = round_label(round_no) if type(round_no) is int and round_no > 0 else None
        if parsed:
            self._tracker.ensure_labels(
                [PROPOSAL, FROM_SYNTHESIZE] + ([round_name] if round_name else [])
            )
        for prop in parsed:
            if validate_synthesis(prop.artifact, visible_proposals=visible_proposals):
                continue
            covers = tuple(n for n in prop.covers if n in coverable)
            body = render_synthesis_artifact(prop.artifact)
            covers_line = format_covers_line(list(covers))
            if covers_line:
                # 机器行 = 覆盖建议的单一真源（消费方：Owner 准入级联、web 徽标）。创建后不改写。
                body = f"{body}\n\n{covers_line}"
            labels = [PROPOSAL, FROM_SYNTHESIZE] + ([round_name] if round_name else [])
            ref = self._tracker.create_issue(
                IssueDraft(title=str(prop.title), body=body, labels=labels)
            )
            numbers.append(ref.number)

        self._emit(
            running=False,
            status=(f"提了 {len(numbers)} 条结构提案（待准入）" if numbers else "本轮无结构提案"),
            proposals=numbers,
            detail=(result_text or None),  # 最终报告全文（详情面板展示，不截断）
        )
        return DesignOutcome(proposal_numbers=numbers, artifacts=[dict(prop.artifact) for prop in parsed])

    def _run_agent(
        self,
        *,
        ready: list,
        proposals: list,
        trend: list[tuple[str, int, str, str]],
        runtime: str,
    ) -> str:
        msg = (
            "你是 Synthesize。以下是 ready queue 与开放 ProposalView。只分析已有提案之间的结构关系、"
            "共同张力和可复用机制；每条输出必须明确引用至少两个可见提案。体验趋势与运行时聚合仅作"
            "背景证据，不能替代跨提案关系。\n"
            "结构提案不规定数据结构、协议或实施步骤。`covers` 仅用于"
            "向 Owner 提供 merge 建议，不会修改任何票的状态。\n\n"
            f"## ready 工作队列（{len(ready)} 条）\n{self._format_backlog(ready)}\n\n"
            f"## 开放 ProposalView（{len(proposals)} 条）\n{self._format_backlog(proposals)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            f"## 运行时行为聚合（任务无关，只给数字）\n{runtime}\n\n"
            "调查完成后调用 `submit_rfcs` 一次：`proposals` 为本轮 0..n 条结构 proposal（无则空数组）；"
            "每条含 title、source_proposals、relationship、common_tension、structural_direction、"
            "expected_leverage、solution_level、abstraction_rationale + 可选 covers。"
            "字段契约由工具 input_schema 强校验，不必也不要在正文里手抄 schema。"
        )
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="designer",
            timeout=_DESIGN_TIMEOUT,
            on_event=self._on_event,
        )

    def _feeling_trend(self) -> list[tuple[str, int, str, str]]:
        """体感随时间：[(created_at, score, reason, session_id)]，按时间升序。

        reason = 用户末态那句「为什么」。session_id 供 get_session_timeline 按体感点取用。
        """
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
    def _format_backlog(backlog: list) -> str:
        return format_proposal_list(backlog)

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

    @staticmethod
    def _proposals_from_submit(text: str) -> list[_Proposal]:
        """从 submit_rfcs 的返回（= agent.run 的返回值）解析出 _Proposal 列表。

        submit_rfcs 是 stop tool，binding 返回 `{"proposals":[...]}`——nexau 已在工具层强校验
        （title/fields 必填、fields 键锁定、covers 为 int 数组、无自创字段）。未调 submit /
        解析失败 → 空列表（本轮 no-op），不抛错拖垮闭环。covers 仍走 _parse_covers 宽进严出。
        """
        raw = read_submit(text, "proposals")
        if not raw:
            return []
        proposals: list[_Proposal] = []
        for item in raw:
            if not item.get("title"):
                continue
            proposals.append(
                _Proposal(
                    title=str(item["title"]),
                    artifact=item,
                    covers=_parse_covers(item.get("covers")),
                )
            )
        return proposals

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
