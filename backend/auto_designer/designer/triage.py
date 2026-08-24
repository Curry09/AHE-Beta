# Spec-0029/T3：triage = 纯规范化生成器——逐条调查 report，就地升为 proposal 或 decline。
"""Triager：issue triage / maintainer = 带只读工具的 nexau agent。

用户提的是 report（自由文本、用户视角症状）。triage agent 逐条处理 report 平面的票，用**三管齐下
的 grounding**（用户报告 + 只读 harness 代码 + get_session_timeline/beat/step 渐进下钻）给每条一个
disposition（三值）：

- accept     → 确认 kind + 填规范化字段（根因区域/边界/验收，经 issue_schema 校验）+ 建议优先级
               → **就地升 proposal**（去 report、加 proposal+from-triage+kind+P*）；字段渲染挂 comment。
               提案不可领——进 ready 与否由 Owner 准入裁决（Spec-0029/T6）。
- reject     → 超范围/无效 → declined + 原因 + 关闭。
- needs_info → 信息太少、读码+轨迹也定位不出 → declined + 原因 + 关闭。

**不判重**（Spec-0029：判重全权归 Owner——triage 回归单条视野，不再喂「已 triaged 判重参照」，
生成侧因此可自由分片并行，重复提案由 Owner 在准入时合并）。agent 出草稿（submit_triage 原生结构化，
nexau 工具层强校验）、driver 落库——与 synthesize/divergent/Owner 同构、解耦。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import norm_label, read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    DECLINED,
    FROM_DIVERGENT,
    FROM_SYNTHESIZE,
    FROM_TRIAGE,
    GATE_DROPPED,
    MERGED,
    NEEDS_INFO,
    NEEDS_TRIAGE,
    PRIORITIES,
    PROPOSAL,
    READY,
    REPORT,
    RFC_LABEL,
    SUPERSEDED,
    TRIAGED,
    USER_KINDS,
    plane,
)
from auto_designer.designer.issue_schema import (
    fields_of as schema_fields_of,
)
from auto_designer.designer.issue_schema import (
    render as schema_render,
)
from auto_designer.designer.issue_schema import (
    validate as schema_validate,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_TRIAGE_TIMEOUT = 900
# 工作流标签（平面/终态/provenance/旧工作流/优先级）——重打标签时一并剔除，只保留 round-* 等属性。
_WORKFLOW_LABELS = frozenset(
    {
        REPORT,
        PROPOSAL,
        READY,
        DECLINED,
        MERGED,
        FROM_TRIAGE,
        FROM_SYNTHESIZE,
        FROM_DIVERGENT,
        NEEDS_TRIAGE,
        TRIAGED,
        RFC_LABEL,
        SUPERSEDED,
        GATE_DROPPED,
        NEEDS_INFO,
        *PRIORITIES,
    }
)

StatusFn = Callable[..., None]


@dataclass
class TriageOutcome:
    """一次 triage_once 的结果：各 disposition 命中的 issue 号。"""

    accepted: list[int] = field(default_factory=list)
    rejected: list[int] = field(default_factory=list)
    needs_info: list[int] = field(default_factory=list)

    @property
    def handled(self) -> int:
        return len(self.accepted) + len(self.rejected) + len(self.needs_info)


def _proposal_labels(current: list[str], kind: str, priority: str | None) -> list[str]:
    """accept：保留 round-* 等属性标签，去旧 type/全部工作流标签，加确认 kind + proposal +
    from-triage + 建议优先级（合法时；Owner 准入时可改）。"""
    keep = [x for x in current if x not in USER_KINDS and x not in _WORKFLOW_LABELS]
    out = [*keep, kind, PROPOSAL, FROM_TRIAGE]
    if priority in PRIORITIES:
        out.append(priority)
    return list(dict.fromkeys(out))


def _declined_labels(current: list[str]) -> list[str]:
    """reject/needs_info：保留 type + round-* 等，去平面标签，加 declined 终态。"""
    keep = [x for x in current if x not in (REPORT, NEEDS_TRIAGE, PROPOSAL, TRIAGED)]
    return list(dict.fromkeys([*keep, DECLINED]))


def _fields_by_label_to_key(kind: str, fields: dict) -> dict:
    """agent 用中文 label 填字段 → 转成 schema key（root_cause/boundary/acceptance）。
    按归一后的 label 匹配（去空白），容忍 LLM 的空格差异。"""
    label_to_key = {norm_label(f.label): f.key for f in schema_fields_of(kind=kind)}
    out: dict[str, str] = {}
    for k, v in fields.items():
        key = label_to_key.get(norm_label(k), str(k))  # 已是 key 则原样
        out[key] = v
    return out


class Triager:
    """triage nexau agent 驱动器：逐条调查 report → 升 proposal / decline。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)  # 只读 grounding：agent 读 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event

    def triage_once(
        self, pending: list | None = None, shard: tuple[int, int] | None = None
    ) -> TriageOutcome:
        """处理一批 report。pending=None 时自取全部 report 平面的票（含旧 needs-triage 数据）；
        shard=(k, n) 时只取按票号排序后的 pending[k::n]（Spec-0029/T8 编排层分片并行——判重已移
        Owner、产出为非约束提案，分片自由、各片不相交）。也可直接传 pending 子集。"""
        if pending is None:
            backlog = self._tracker.list_open_issues()
            pending = sorted(
                (i for i in backlog if plane(i.labels) == REPORT), key=lambda i: i.number
            )
            if shard is not None:
                k, n = shard
                pending = pending[k :: max(1, n)]
        if not pending:
            self._emit(running=False, status="无待分诊 report")
            return TriageOutcome()
        self._emit(running=True, status=f"分诊中…（{len(pending)} 条 report）")

        result_text = self._run_agent(pending=pending)
        # submit_triage（stop tool）原生结构化：nexau 已按 input_schema 强校验（三值 enum、fields 键
        # 锁定、无自创字段），binding 回显成为 agent.run 的返回。未调 submit → None → 本轮 no-op 兜底。
        dispositions = read_submit(result_text, "dispositions")
        if dispositions is None:
            self._emit(
                running=False,
                status="本轮未收到有效 submit_triage（no-op）",
                detail=result_text or None,
            )
            return TriageOutcome()

        by_number = {i.number: i for i in pending}
        outcome = TriageOutcome()
        for d in dispositions:
            try:
                self._apply(d, by_number=by_number, outcome=outcome)
            except Exception:  # noqa: BLE001  单条落库失败（set_labels 等）不拖垮其余 disposition
                pass

        self._emit(
            running=False,
            status=(
                f"分诊 {outcome.handled} 条：升提案 {len(outcome.accepted)}、"
                f"驳回 {len(outcome.rejected)}、待补 {len(outcome.needs_info)}"
            ),
            detail=result_text or None,
        )
        return outcome

    def _apply(self, d: dict, *, by_number: dict, outcome: TriageOutcome) -> None:
        # d 已由 nexau input_schema 校验（issue/disposition 必填、三值 enum、fields 键锁定）。
        try:
            num = int(d.get("issue"))
        except (TypeError, ValueError):
            return
        issue = by_number.get(num)
        if issue is None:  # 不在本批集合里 → 跳过（防越界改动）
            return
        disp = str(d.get("disposition", "")).strip()

        if disp == "accept":
            kind = str(d.get("kind", "")).strip().lower()
            if kind not in USER_KINDS:  # 非法 kind → 当信息不足处理（下一轮重来）
                self._decline(
                    issue, "信息不足", f"triage 给了非法 kind {kind!r}", outcome.needs_info
                )
                return
            fields = _fields_by_label_to_key(kind, d.get("fields") or {})
            errs = schema_validate(kind=kind, fields=fields, section="triage")
            if errs:  # 规范化字段没填全 → 降级 needs_info（保证升上去的提案定位完整）
                self._decline(
                    issue, "信息不足", f"triage 定位不全：{'；'.join(errs)}", outcome.needs_info
                )
                return
            priority = str(d.get("priority", "")).strip().upper()  # 建议值；Owner 准入时可改
            self._tracker.set_labels(num, _proposal_labels(list(issue.labels), kind, priority))
            body = schema_render(kind=kind, fields=fields, section="triage")
            self._safe_comment(num, f"## Triage 定位\n\n{body}")
            outcome.accepted.append(num)

        elif disp == "reject":
            self._decline(issue, "驳回", str(d.get("reason", "")).strip(), outcome.rejected)
        elif disp == "needs_info":
            self._decline(issue, "信息不足", str(d.get("reason", "")).strip(), outcome.needs_info)
        # 未知 disposition：忽略（票仍在 report 平面，下轮再分诊）

    def _decline(self, issue, head: str, reason: str, bucket: list[int]) -> None:
        """declined 终态 + 写原因 + 关闭。"""
        self._tracker.set_labels(issue.number, _declined_labels(list(issue.labels)))
        self._safe_comment(issue.number, f"{head}：{reason or '（未给原因）'}")
        self._safe_close(issue.number, f"{head}：{reason}")
        bucket.append(issue.number)

    def _safe_comment(self, number: int, body: str) -> None:
        try:
            self._tracker.add_comment(number, body)
        except Exception:  # noqa: BLE001  单条挂链失败不拖垮其余
            pass

    def _safe_close(self, number: int, reason: str) -> None:
        try:
            self._tracker.set_state(number, "closed", reason)
        except Exception:  # noqa: BLE001
            pass

    def _run_agent(self, *, pending: list) -> str:
        # triage 只做「单条规范化」：只给它本批 report + 只读代码 + 按需拉的单局轨迹（含那局体感分，
        # 供建议优先级）。不喂判重参照/聚合 runtime_agg/全局体感曲线——判重归 Owner、全局归 synthesize。
        msg = (
            "逐条**规范化**下面的 raw 用户 report：确认 kind、读 harness 源码 + 按 issue 号调 "
            "get_session_timeline 拉该局真实轨迹（含那局体感分）定位、给建议优先级，或驳回/needs_info。\n"
            "**先 read_file/search_file_content 读懂相关 harness 机制再下结论**；对存疑 report 先调 "
            "get_session_timeline(issue_number=<号>) 看那局使用事件时间线，某拍归不出因再 "
            "get_harness_beat(turn=…)、某步 truncated 且确需正文再 get_harness_step(turn=…, step_i=…)"
            "逐层下钻——别一次拉整包。**不用判重**（重复由准入评审合并），每条独立下结论。\n\n"
            f"## 待分诊 report（{len(pending)} 条）\n{self._format_issues(pending)}\n\n"
            "调查完后调 submit_triage 提交 dispositions（每条 report 恰好一项）——它是唯一收尾方式。"
        )
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="triager",
            timeout=_TRIAGE_TIMEOUT,
            on_event=self._on_event,
        )

    @staticmethod
    def _format_issues(issues: list) -> str:
        if not issues:
            return "（无）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in issues
        )

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
