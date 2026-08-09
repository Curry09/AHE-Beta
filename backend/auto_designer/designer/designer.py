# Spec-0029/T4：synthesize 纯生成器——在规范化 backlog 上跨条找结构根因，产结构提案（待准入）。
"""Designer = synthesize agent：综合全局的 nexau agent（delivery 轨；对偶于 triage 的逐条规范化、
divergent 的会话侧发现、开发者的局部落地）。

它读**ready 工作队列 + 待准入提案索引（含本轮 triage 新升的 from-triage 提案）+ 体感曲线 + 运行时
行为聚合**，只读查看 harness 现状、按需拉 god-view 轨迹，跳出单条找跨 issue 的结构性根因，产 0..n 条
**结构提案**（落 proposal 平面 + from-synthesize，covers 机器行声明它建议覆盖哪些提案/报告——仅是
**建议**，合并裁决权在 Owner 准入时，Spec-0029/T6）。提案不可领；进 ready 与否由 Owner 裁决。
designer 不碰 git、不改文件、不关别人的票——只提方向。gate/晋升评审已移交 Owner（gate_once 退役）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import norm_label, read_submit, run_agent_def
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
from auto_designer.designer.issue_schema import fields_of as _schema_fields_of
from auto_designer.designer.issue_schema import render as _schema_render
from auto_designer.designer.issue_schema import validate as _schema_validate
from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# 向后兼容别名（旧测/引用）；语义为「结构提案」的口语名 RFC。
DESIGN_LABEL = RFC_LABEL
# 一次 propose_once 是多轮工具调用（读文件 + 综合 + 按需 timeline/beat/step 渐进下钻）；给足墙钟防挂死。
_DESIGN_TIMEOUT = 3600

StatusFn = Callable[..., None]


@dataclass
class DesignOutcome:
    """一次 propose_once 的结果：产出的提案 issue 号列表。"""

    proposal_numbers: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


@dataclass(frozen=True)
class _Proposal:
    """一条解析后的结构提案：标题 + RFC 字段(中文 label 键) + 建议覆盖的票号。"""

    title: str
    fields: dict
    covers: tuple[int, ...] = ()


def _rfc_fields_by_label(fields: dict) -> dict:
    """agent 用中文 label 填的 RFC 字段 → schema key（问题→problem 等）；未知 label 原样保留。
    按归一后的 label 匹配（忽略空白差异）。"""
    label_to_key = {norm_label(f.label): f.key for f in _schema_fields_of(kind="rfc")}
    return {label_to_key.get(norm_label(k), str(k)): v for k, v in fields.items()}


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
        numbers: list[int] = []
        round_no = self._round_provider() if self._round_provider is not None else None
        round_name = round_label(round_no) if type(round_no) is int and round_no > 0 else None
        if parsed:
            self._tracker.ensure_labels(
                [PROPOSAL, FROM_SYNTHESIZE] + ([round_name] if round_name else [])
            )
        for prop in parsed:
            fields = _rfc_fields_by_label(prop.fields)
            if _schema_validate(kind="rfc", fields=fields, section="triage"):
                continue  # RFC 字段没填全 → 跳过（不产半成品结构提案）
            covers = tuple(n for n in prop.covers if n in coverable)
            body = _schema_render(kind="rfc", fields=fields)
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
        return DesignOutcome(proposal_numbers=numbers)

    def _run_agent(
        self,
        *,
        ready: list,
        proposals: list,
        trend: list[tuple[str, int, str, str]],
        runtime: str,
    ) -> str:
        rfc_labels = "/".join(f.label for f in _schema_fields_of(kind="rfc"))
        msg = (
            "下面是**ready 工作队列**（dev 正在消化的）+ **待准入提案索引**（含本轮 triage 刚规范化的）"
            "+ 体感曲线 + 运行时行为聚合。逐条的分类/定位已由 triage 做完；你的活是**跳出单条，找跨 "
            "issue 的结构性根因**，产 0..n 条**结构提案**（宁缺毋滥，无跨条主题就交空——大多数轮可能"
            "没有，别硬凑；也别重复已有提案/ready 项的施力点）。\n"
            "**先 read_file 读懂 harness 源码**（`agents/main.md` + `entry.py` + `agent.yaml`，看清超时/"
            "重试/迭代上限/交付方式这些一级钮）再提；没读机制源码别断言机制根因。\n"
            "**你只给「问题 + 根因 + 方向」，不写实现**：绝不写 manifest/checkpoint/gate、schema、分步"
            "协议这类施工细节（照抄就能敲键盘=越权）。\n"
            "**结构提案综合多条提案/报告时，用 covers 声明**：若你的根因涵盖若干条待准入提案（修好它"
            '这些就该让位），在该项加 `"covers": [票号,…]`——这只是**建议**，是否合并由准入评审裁决；'
            "不确定就别填。\n\n"
            f"## ready 工作队列（{len(ready)} 条）\n{self._format_backlog(ready)}\n\n"
            f"## 待准入提案（{len(proposals)} 条，勿重复其施力点）\n{self._format_backlog(proposals)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            f"## 运行时行为聚合（任务无关，只给数字）\n{runtime}\n\n"
            "对某条票或某个体感点有疑惑时，先调 `get_session_timeline`"
            "（issue_number=… 或 session_id=…）看该局使用事件时间线；"
            "若某拍超时/活动条不够归因，再对该拍 `t` 调 `get_harness_beat(turn=…)`；"
            "某步 truncated 且确需正文再 `get_harness_step(turn=…, step_i=…)`；"
            "不要尝试直接读 sessions/ 原始文件。\n\n"
            "调查完毕后**调 `submit_rfcs` 一次**收尾：`proposals` 为本轮 0..n 条结构提案（无则空数组）；"
            f"每条含 `title` + `fields`（{rfc_labels}，中文 label 键）+ 可选 `covers`。"
            "字段契约由工具 input_schema 强校验，不必也不要在正文里手抄 schema。"
        )
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
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
        if not backlog:
            return "（空）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in backlog
        )

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
            fields = item.get("fields")
            proposals.append(
                _Proposal(
                    title=str(item["title"]),
                    fields=fields if isinstance(fields, dict) else {},
                    covers=_parse_covers(item.get("covers")),
                )
            )
        return proposals

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
