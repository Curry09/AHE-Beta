# Spec-0042/T3：Triage 将单条 report 规范化为 proposal 或终态结论。
"""Triage（报告规范化）驱动器。

输入由原始 report、只读 harness 源码和渐进式会话证据组成。accept 将同一票原子更新为任务无关的
proposal，并把原始报告保存在审计评论中；reject 与 needs_info 转入 declined 终态。跨提案判重和
准入分别由 Owner 执行。
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
from auto_designer.designer.role_contract import validate_triage
from auto_designer.tracker.base import IssueTracker
from auto_designer.usage import bind_usage_context
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
    failed: dict[int, str] = field(default_factory=dict)
    warnings: dict[int, list[str]] = field(default_factory=dict)
    artifacts: dict[int, dict] = field(default_factory=dict)

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


def _proposal_body(*, normalized: str) -> str:
    """proposal 默认上下文只含规范化结论；具体案例从评论/timeline 渐进取证。"""
    return f"## Triage 规范化提案（实施对象：harness）\n\n{normalized.strip()}"


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

        outcome = TriageOutcome()
        details: list[str] = []
        # 每个 report 拥有独立模型上下文；相邻报告不能污染问题定义或证据判断。
        for issue in pending:
            session_id = self._session_id_for_issue(issue.number)
            with bind_usage_context(
                session_id=session_id or "unavailable",
                interaction_id=session_id or f"report-{issue.number}",
                agent_id=f"triage-report-{issue.number}",
            ):
                result_text = self._run_agent(pending=[issue])
            details.append(result_text or "")
            dispositions = read_submit(result_text, "dispositions")
            if dispositions is None:
                outcome.failed[issue.number] = "missing-submit"
                continue
            for d in dispositions:
                violations = validate_triage(d, report_number=issue.number)
                if violations:
                    outcome.warnings.setdefault(issue.number, []).extend(v.code for v in violations)
                    outcome.failed[issue.number] = ",".join(v.code for v in violations)
                    continue
                try:
                    outcome.artifacts[issue.number] = dict(d)
                    self._apply(d, by_number={issue.number: issue}, outcome=outcome)
                except Exception as exc:  # noqa: BLE001
                    outcome.failed[issue.number] = f"{type(exc).__name__}: {exc}"

        self._emit(
            running=False,
            status=(
                f"分诊 {outcome.handled} 条：升提案 {len(outcome.accepted)}、"
                f"驳回 {len(outcome.rejected)}、待补 {len(outcome.needs_info)}、"
                f"失败 {len(outcome.failed)}"
            ),
            detail="\n".join(details) or None,
        )
        return outcome

    def _session_id_for_issue(self, issue_number: int) -> str | None:
        for entry in self._store.index():
            if issue_number in [int(number) for number in entry.get("issue_numbers", [])]:
                return str(entry.get("session_id") or "") or None
        return None

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
            proposal_title = str(d.get("proposal_title", "")).strip()
            if not proposal_title:
                self._decline(
                    issue, "信息不足", "triage 未给任务无关 proposal_title", outcome.needs_info
                )
                return
            errs = schema_validate(kind=kind, fields=fields, section="triage")
            if errs:  # 规范化字段没填全 → 降级 needs_info（保证升上去的提案定位完整）
                self._decline(
                    issue, "信息不足", f"triage 定位不全：{'；'.join(errs)}", outcome.needs_info
                )
                return
            priority = str(d.get("priority", "")).strip().upper()  # 建议值；Owner 准入时可改
            body = schema_render(kind=kind, fields=fields, section="triage")
            # 原始证据先归档；核心 title/body/labels 由 tracker 单次更新，避免半迁移 proposal。
            if not self._safe_comment(
                num,
                f"## 原始用户报告（案例证据，非实现对象）\n\n"
                f"**原始标题：** {issue.title}\n\n{issue.body or '（空）'}",
            ):
                outcome.warnings.setdefault(num, []).append("原始报告审计评论写入失败")
            self._tracker.update_issue(
                num,
                title=proposal_title,
                body=_proposal_body(normalized=body),
                labels=_proposal_labels(list(issue.labels), kind, priority),
            )
            outcome.accepted.append(num)

        elif disp == "reject":
            self._decline(issue, "驳回", str(d.get("reason", "")).strip(), outcome.rejected)
        elif disp == "needs_info":
            self._decline(issue, "信息不足", str(d.get("reason", "")).strip(), outcome.needs_info)
        # 未知 disposition：忽略（票仍在 report 平面，下轮再分诊）

    def _decline(self, issue, head: str, reason: str, bucket: list[int]) -> None:
        """declined 终态 + 写原因 + 关闭。"""
        self._tracker.transition_issue(
            issue.number,
            state="closed",
            labels=_declined_labels(list(issue.labels)),
        )
        self._safe_comment(issue.number, f"{head}：{reason or '（未给原因）'}")
        bucket.append(issue.number)

    def _safe_comment(self, number: int, body: str) -> bool:
        try:
            self._tracker.add_comment(number, body)
        except Exception:  # noqa: BLE001  单条挂链失败不拖垮其余
            return False
        return True

    def _run_agent(self, *, pending: list) -> str:
        # triage 只做「单条规范化」：只给它本批 report + 只读代码 + 按需拉的单局轨迹（含那局体感分，
        # 供建议优先级）。不喂判重参照/聚合 runtime_agg/全局体感曲线——判重归 Owner、全局归 synthesize。
        msg = (
            "以下是本批待处理的原始报告。逐条确认 kind，按需读取 harness 源码，并以 issue 号检索"
            "对应会话证据。证据不足时依次使用 timeline、beat、step，不直接读取 sessions 文件。\n"
            "accept 必须提供任务无关的 proposal_title 和完整规范化字段；reject 或 needs_info 必须说明"
            "理由。每条报告独立处理，跨提案判重由 Owner 负责。\n\n"
            f"## 待分诊 report（{len(pending)} 条）\n{self._format_issues(pending)}\n\n"
            "完成调查后调用 submit_triage 一次，dispositions 只能包含当前这一条 report。"
        )
        report_id = str(pending[0].number) if pending else ""
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="triager",
            timeout=_TRIAGE_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "report", "id": report_id},
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
