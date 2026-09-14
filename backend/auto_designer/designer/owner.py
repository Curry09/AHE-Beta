# Owner 是需求面到 OpenAgents 的交接路由器，不是方案审核者。
"""Owner 驱动器：把 proposal 无损打包并交接给 OpenAgents。

生成器（triage/synthesize/divergent）负责问题诊断、产品发现和结构设计；Owner 不重新判断根因、
不选择 prompt/runtime 等实现层，也不以交付风险为由压缩目标。模型协调 PM/结构路线的交付重叠，
补充 handoff 摘要、需保留的能力和独立验收分组。未被模型列出的提案默认直接交接，避免遗漏成为隐性否决。

路由动作：
- admit → 加 `openagents` 交付面交接令牌；
- merge → 仅限标题与规范化正文完全相同的重复项；非精确重复会被保留为独立交接；
- hold  → 仅限缺少形成开发任务所必需的信息，并须明确缺口。

Designer 的 `covers` 已在结构提案创建阶段执行来源合并；Owner 不再次消费该关系。Owner
仅处理当前仍开放 proposal 的交接，保留标题与规范化正文完全相同项的历史兼容合并路径。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    MERGED,
    NEEDS_TRIAGE,
    OPENAGENTS,
    PRIORITIES,
    PROPOSAL,
    READY,
    REPORT,
    TRIAGED,
    format_merged_into,
    plane,
)
from auto_designer.designer.proposal_view import format_proposal_list, normalized_proposal_body
from auto_designer.designer.role_contract import validate_owner
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_ADMIT_TIMEOUT = 1800
StatusFn = Callable[..., None]


@dataclass
class AdmitOutcome:
    """一次 admit_once 的结果：各裁决命中的票号。"""

    admitted: list[int] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)
    declined: list[int] = field(default_factory=list)
    held: list[int] = field(default_factory=list)
    # 向后兼容旧 API；全量模型审核后该字段恒为空。
    mechanical: list[int] = field(default_factory=list)
    invalid: dict[int, str] = field(default_factory=dict)
    failed: dict[int, str] = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)


def _ready_labels(current: list[str], priority: str | None) -> list[str]:
    """admit：去平面/旧工作流标签，加 `openagents` 交接令牌；priority 合法时替换旧 P*（终优先级）。

    Spec-0032/T3：Owner 准入不再直接打 ready——`openagents` 是交付面（vigil）的发现标签，vigil
    `_intake` 发现后自己盖 ready 并触发 curator 依赖排序；Owner 直打 ready 会让 vigil 跳过该票、
    curator 永不运行（准入语义不变：plane() 把两标签同视为 READY 平面）。
    """
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED}
    keep = [x for x in current if x not in drop]
    if priority in PRIORITIES:
        keep = [x for x in keep if x not in PRIORITIES]
        keep.append(priority)
    return list(dict.fromkeys([*keep, OPENAGENTS]))


def _terminal_labels(current: list[str], terminal: str) -> list[str]:
    """merge/decline：去平面标签（含交付面令牌），加终态标签。"""
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED, READY, OPENAGENTS}
    keep = [x for x in current if x not in drop]
    return list(dict.fromkeys([*keep, terminal]))


class Owner:
    """交接路由器：模型整理 handoff，driver 保障独立能力不被压缩。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        review: bool = True,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        # review=False = 纯机械交接：不调用模型，全部 proposal 直接交给 OpenAgents。
        self._review = review

    def admit_once(self) -> AdmitOutcome:
        from auto_designer.observations.delivery_gaps import ingest_delivery_gaps

        ingest_delivery_gaps(store=self._store, tracker=self._tracker)
        backlog = self._tracker.list_open_issues()
        proposals = [i for i in backlog if plane(i.labels) == PROPOSAL]
        if not proposals:
            self._emit(running=False, status="无待准入提案")
            return AdmitOutcome()
        ready = [i for i in backlog if plane(i.labels) == READY]
        self._emit(running=True, status=f"交接打包中…（{len(proposals)} 条提案）")

        outcome = AdmitOutcome()
        by_number = {i.number: i for i in backlog}

        # Cross-route overlap is a coordination relation, never an absorption instruction.
        review_needed = proposals
        decisions: list[dict] = []
        if review_needed and self._review:
            result_text = self._run_agent(
                proposals=review_needed, ready=ready, trend=self._feeling_trend()
            )
            decisions = read_submit(result_text, "decisions") or []
        # review=False 或 agent 未列出某项：该项在 pass 2 默认直接交接。

        reviewable = {i.number for i in review_needed}
        visible_routing = reviewable | {i.number for i in ready}
        explicit: dict[int, dict] = {}
        for d in decisions:
            try:
                num = int(d.get("issue"))
            except (TypeError, ValueError):
                continue
            outcome.artifacts.append(dict(d))
            violations = validate_owner(d, review_batch=reviewable)
            if violations:
                if num in reviewable:
                    outcome.invalid[num] = ",".join(v.code for v in violations)
                    # An explicitly malformed decision is not the same as an
                    # omitted decision.  Preserve the proposal as hold so the
                    # default-handoff pass cannot accidentally admit it.
                    if num not in outcome.held:
                        outcome.held.append(num)
                continue
            if num not in explicit:  # 只裁本批评审集合；重复决策先者得
                routing = dict(d)
                overlaps = d.get("delivery_overlaps", [])
                visible = visible_routing - {num}
                if not isinstance(overlaps, list):
                    overlaps = []
                    outcome.invalid[num] = "delivery_overlaps 必须为可见票号数组；已保留交接"
                valid = [n for n in overlaps if type(n) is int and n in visible]
                if len(valid) != len(overlaps):
                    outcome.invalid[num] = "delivery_overlaps 含不可见或自身票号；已过滤并保留交接"
                routing["delivery_overlaps"] = list(dict.fromkeys(valid))
                explicit[num] = routing

        # merge target 必须是既有 ready item，或本批显式 admit 的 proposal；driver 还会验证
        # 两者是精确重复，不能以“相同价值方向”为由吞掉独立能力。
        existing_ready = {i.number for i in ready}
        valid_merge_targets = existing_ready | {
            num
            for num, decision in explicit.items()
            if str(decision.get("decision", "")).strip() == "admit"
        }

        # pass 1：显式决策
        decision_order = {"admit": 0, "merge": 1, "decline": 2, "hold": 3}
        for num, d in sorted(
            explicit.items(),
            key=lambda item: decision_order.get(str(item[1].get("decision", "")).strip(), 4),
        ):
            issue = by_number[num]
            decision = str(d.get("decision", "")).strip()
            try:
                if decision == "admit":
                    prio = str(d.get("priority", "")).strip().upper() or None
                    self._admit(issue, priority=prio, note="admission: admit")
                    self._safe_comment(num, self._decision_note(d))
                    outcome.admitted.append(num)
                elif decision == "merge":
                    into = d.get("into")
                    target = by_number.get(into) if isinstance(into, int) else None
                    if (
                        target is None
                        or target.number == num
                        or target.number not in valid_merge_targets
                        or target.number not in existing_ready | set(outcome.admitted)
                    ):
                        self._admit(issue, priority=None, note="handoff: invalid merge preserved")
                        outcome.invalid[num] = "merge target 必须是既有 ready item 或本批 admit 提案"
                        outcome.admitted.append(num)
                        continue
                    if self._dedupe_signature(issue) != self._dedupe_signature(target):
                        self._admit(issue, priority=None, note="handoff: non-duplicate merge preserved")
                        self._safe_comment(num, self._decision_note(d))
                        outcome.invalid[num] = "仅标题与规范化正文完全相同的提案可 merge；已独立交接"
                        outcome.admitted.append(num)
                        continue
                    self._merge(issue, into=target.number)
                    self._safe_comment(num, self._decision_note(d))
                    outcome.merged.append(num)
                else:  # hold 或未知；schema 已移除 decline
                    outcome.held.append(num)
            except Exception as exc:  # noqa: BLE001  单条失败隔离，但必须进入结构化结果
                outcome.failed[num] = f"{type(exc).__name__}: {exc}"
                if num not in outcome.held:
                    outcome.held.append(num)

        # pass 2：其余 proposal 默认直接交接。Designer 的 covers 已在创建阶段处理。
        decided = set(explicit)
        for i in review_needed:
            if i.number not in decided and i.number not in {
                *outcome.admitted,
                *outcome.merged,
                *outcome.declined,
                *outcome.held,
            }:
                try:
                    self._admit(i, priority=None, note="handoff: default preserve")
                    outcome.admitted.append(i.number)
                except Exception as exc:  # noqa: BLE001
                    outcome.failed[i.number] = f"{type(exc).__name__}: {exc}"
                    outcome.held.append(i.number)

        self._emit(
            running=False,
            status=(
                f"交接：admit {len(outcome.admitted)} · "
                f"merge {len(outcome.merged)} · decline {len(outcome.declined)} · "
                f"hold {len(outcome.held)} · failed {len(outcome.failed)}"
            ),
            proposals=outcome.admitted,
        )
        return outcome

    def _admit(self, issue, *, priority: str | None, note: str) -> None:
        from auto_designer.designer.delivery_evidence import publish_delivery_evidence

        publish_delivery_evidence(tracker=self._tracker, store=self._store, issue=issue)
        self._tracker.set_labels(issue.number, _ready_labels(list(issue.labels), priority))
        self._safe_comment(issue.number, note)

    def _merge(self, issue, *, into: int) -> None:
        from auto_designer.designer.delivery_evidence import publish_delivery_evidence
        from auto_designer.observations.grants import authorized_sessions, grant, is_pm_source

        sessions = authorized_sessions(store=self._store, issue=into)
        sessions |= authorized_sessions(store=self._store, issue=issue.number)
        grant(store=self._store, issue=into, sessions=sessions,
              pm_origin=is_pm_source(store=self._store, issue=into) or
              is_pm_source(store=self._store, issue=issue.number))
        target = next(i for i in self._tracker.list_open_issues() if i.number == into)
        publish_delivery_evidence(tracker=self._tracker, store=self._store, issue=target)
        self._tracker.transition_issue(
            issue.number, state="closed", labels=_terminal_labels(list(issue.labels), MERGED)
        )
        self._safe_comment(issue.number, format_merged_into(into))

    def _run_agent(
        self, *, proposals: list, ready: list, trend: list[tuple[str, int, str, str]]
    ) -> str:
        msg = self._review_message(proposals=proposals, ready=ready, trend=trend)
        from auto_designer.usage import current_usage_context  # noqa: PLC0415

        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="owner",
            tracker=self._tracker,
            source_issue_ids={i.number for i in [*ready, *proposals]},
            timeout=_ADMIT_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "round", "id": str(current_usage_context().round_no or "")},
            evidence={
                "default_level": "role_artifacts",
                "allowed_levels": [],
                "proposal_count": len(proposals),
                "ready_count": len(ready),
            },
        )

    def _review_message(
        self, *, proposals: list, ready: list, trend: list[tuple[str, int, str, str]]
    ) -> str:
        goal_summary = self._goal_summary_index(trend)
        return (
            "你是需求面到 OpenAgents 的 Delivery Router。以下是本批开放 ProposalView、既有 ready item"
            "和体验趋势。你的工作是逐条无损打包交接，不审核上游方案，不选择实现层，也不因低风险或易交付"
            "而缩小问题。默认 admit；merge 只用于标题和规范化正文完全相同的重复项；hold 只用于缺少形成开发"
            "任务所必需的信息。Designer 已在结构提案创建阶段处理 `covers` 来源；你不要据此再次"
            "关闭或合并来源。\n"
            "每个不同的用户问题、产品能力或结构机制都必须保留为独立 handoff 或独立 acceptance group。\n\n"
            "PM 独立到 Owner；Designer 只吸收非 PM 来源。你负责识别双轨交付重叠：用可选 "
            "delivery_overlaps 列出本批或 ready 中关联票号，并在 handoff_summary 解释共享工作与独立验收边界。"
            "重叠不代表重复，双方仍分别 admit；此字段不是 merge、依赖或自动合并实现的指令。\n\n"
            f"## 待评审提案（{len(proposals)} 条）\n{self._format_index(proposals)}\n\n"
            f"## 已在 ready 的工作项（{len(ready)} 条，判重参照）\n{self._format_index(ready)}\n\n"
            f"## 体感曲线\n{self._format_trend(trend)}\n\n"
            "## 目标证据摘要（仅审计元数据，不是客观验收）\n"
            f"{goal_summary}\n\n"
            "只依据 ProposalView 整理交接内容，不回到原始会话重新诊断。\n\n"
            "完成后调用 `submit_admission` 一次：每条 proposal 一项，填写 handoff_summary、"
            "preserved_capabilities 与 acceptance_groups。未列出的 proposal 仍会由 driver 默认直接交接。"
        )

    def _goal_summary_index(self, trend: list[tuple[str, int, str, str]]) -> str:
        """Owner sees compact index metadata, never raw session traces."""
        import json

        wanted = {sid for _ts, _score, _reason, sid in trend if sid}
        rows = []
        for row in self._store.index(include_invalid=True):
            sid = str(row.get("session_id") or "")
            if sid not in wanted:
                continue
            rows.append(
                {
                    "session_id": sid,
                    "goal_audit_status": row.get("goal_audit_status") or "unavailable",
                    "baseline_revision_count": row.get("baseline_revision_count", 0),
                    "unresolved_goal_ids": list(row.get("unresolved_goal_ids") or [])[:12],
                    "accept_validity": row.get("accept_validity", "not_applicable"),
                    "objective_passed": row.get("objective_passed"),
                    "provenance": {"kind": "session_index", "session_id": sid},
                }
            )
        if not rows:
            return "（暂无可用目标元数据）"
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
    def _format_index(issues: list) -> str:
        """准入索引使用所有下游角色共享的 canonical ProposalView。"""
        return format_proposal_list(issues)

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

    def _safe_comment(self, number: int, body: str) -> None:
        try:
            # Cross-system provenance contract: OpenAgents treats comments with
            # this machine identity as automation output, so Owner decisions do
            # not enter its human-reply queue.  Apply it to every Owner comment,
            # rather than matching individual decision text downstream.
            marker = "<!-- openagents:agent=auto-designer -->"
            signed = body if marker in body else f"{body}\n\n{marker}"
            self._tracker.add_comment(number, signed)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _decision_note(decision: dict) -> str:
        return "\n".join(
            [
                "## OpenAgents 交接包",
                f"- 摘要：{decision.get('handoff_summary', '')}",
                "- 保留能力：" + "；".join(decision.get("preserved_capabilities", [])),
                "- 验收分组：" + "；".join(decision.get("acceptance_groups", [])),
                "- 交付重叠（关联，不合并）：" + (
                    ", ".join(f"#{n}" for n in decision.get("delivery_overlaps", [])) or "无"
                ),
            ]
        )

    @staticmethod
    def _dedupe_signature(issue) -> tuple[str, str]:
        title = " ".join(str(issue.title).casefold().split())
        body = " ".join(normalized_proposal_body(str(issue.body)).casefold().split())
        return title, body

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
