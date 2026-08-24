# Spec-0029/T6：Owner = 唯一准入——每轮一次批量裁决 proposal → ready/merged/declined/hold。
"""Owner 驱动器：三平面模型的唯一准入口（backlog grooming / Definition of Ready 的执行者）。

生成器（triage/synthesize/divergent）产的提案一律不可领；进 ready 与否、重复合并、覆盖裁决、
终优先级——全部集中在此（生成侧因此解耦、可自由并行）。每轮一次 `admit_once()`，全部提案
统一进入一次批量 Owner 模型评审，并以 `submit_admission` 收尾（nexau 工具层强校验）。来源标签
只表示证据来源，不构成准入资格；尤其 `from-triage` 不得绕过全局产品边界和结构判重。

决策落库（裁决优先级 = **显式决策 > covers 默认 merge > 全局默认 hold**）：
- admit   → 去 proposal 加 `openagents` 交付面交接令牌（+终优先级，可覆盖 triage 建议值）；
  vigil 发现后自己盖 ready 并排依赖边（Spec-0032/T3，plane 读侧两标签同属 READY 平面）。
- merge   → 关闭 + `merged-into: #主票` 机器行（重复归并的唯一落点）。
- decline → declined + 原因 + 关闭。
- hold    → 保持 proposal，下轮再审（未列出的提案默认 hold）。
- **covers 级联的唯一落点**：显式决策应用完后，对每条已 admit 的提案（按票号序确定性处理），
  将其 covers 里仍 open、未被本批显式裁决的 report/proposal 票默认 merge 到它；结构案被 hold/
  decline 则 covers 不触发任何级联。dev 完成时不再级联（_close_covered 已退役）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.agent_runtime import read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    DECLINED,
    MERGED,
    NEEDS_TRIAGE,
    OPENAGENTS,
    PRIORITIES,
    PROPOSAL,
    READY,
    REPORT,
    TRIAGED,
    format_merged_into,
    parse_covers_line,
    plane,
)
from auto_designer.designer.proposal_view import format_proposal_list
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
    """准入评审驱动器：全量模型批量裁决。恒 1 实例（全局视野的单点）。"""

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
        # review=False = 禁用准入：不调用模型，所有提案 hold。不存在机械放行旁路。
        self._review = review

    def admit_once(self) -> AdmitOutcome:
        backlog = self._tracker.list_open_issues()
        proposals = [i for i in backlog if plane(i.labels) == PROPOSAL]
        if not proposals:
            self._emit(running=False, status="无待准入提案")
            return AdmitOutcome()
        ready = [i for i in backlog if plane(i.labels) == READY]
        self._emit(running=True, status=f"准入评审中…（{len(proposals)} 条提案）")

        outcome = AdmitOutcome()
        by_number = {i.number: i for i in backlog}

        # 全部来源统一进入一次批量模型评审；from-triage 也不例外。
        review_needed = proposals
        decisions: list[dict] = []
        if review_needed and self._review:
            result_text = self._run_agent(
                proposals=review_needed, ready=ready, trend=self._feeling_trend()
            )
            decisions = read_submit(result_text, "decisions") or []
        # review=False 或 agent 未 submit：全部默认 hold（提案留存下轮再审）。

        reviewable = {i.number for i in review_needed}
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
                continue
            if num not in explicit:  # 只裁本批评审集合；重复决策先者得
                explicit[num] = d

        # merge target 必须是既有 ready item，或本批显式 admit 的 proposal。
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
                        outcome.held.append(num)
                        outcome.invalid[num] = "merge target 必须是既有 ready item 或本批 admit 提案"
                        continue
                    self._merge(issue, into=target.number)
                    self._safe_comment(num, self._decision_note(d))
                    outcome.merged.append(num)
                elif decision == "decline":
                    self._decline(issue, reason=str(d.get("reason", "")).strip())
                    self._safe_comment(num, self._decision_note(d))
                    outcome.declined.append(num)
                else:  # hold 或未知
                    outcome.held.append(num)
            except Exception as exc:  # noqa: BLE001  单条失败隔离，但必须进入结构化结果
                outcome.failed[num] = f"{type(exc).__name__}: {exc}"
                if num not in outcome.held:
                    outcome.held.append(num)

        # pass 2：covers 默认级联（唯一落点）——对每条已 admit 的提案按票号序确定性处理。
        decided = set(explicit)
        for num in sorted(outcome.admitted):
            admitted_issue = by_number.get(num)
            if admitted_issue is None:
                continue
            for n in parse_covers_line(admitted_issue.body):
                t = by_number.get(n)
                if t is None or t.number == num or t.number in decided:
                    continue
                if plane(t.labels) not in (REPORT, PROPOSAL):
                    continue  # ready/终态不动
                try:
                    self._merge(t, into=num)
                    outcome.merged.append(t.number)
                    decided.add(t.number)
                except Exception as exc:  # noqa: BLE001
                    outcome.failed[t.number] = f"{type(exc).__name__}: {exc}"

        # pass 3：其余评审集合默认 hold（不落库动作，只计数）
        for i in review_needed:
            if i.number not in decided and i.number not in {
                *outcome.admitted,
                *outcome.merged,
                *outcome.declined,
                *outcome.held,
            }:
                outcome.held.append(i.number)

        self._emit(
            running=False,
            status=(
                f"准入：admit {len(outcome.admitted)} · "
                f"merge {len(outcome.merged)} · decline {len(outcome.declined)} · "
                f"hold {len(outcome.held)} · failed {len(outcome.failed)}"
            ),
            proposals=outcome.admitted,
        )
        return outcome

    def _admit(self, issue, *, priority: str | None, note: str) -> None:
        self._tracker.set_labels(issue.number, _ready_labels(list(issue.labels), priority))
        self._safe_comment(issue.number, note)

    def _merge(self, issue, *, into: int) -> None:
        self._tracker.transition_issue(
            issue.number, state="closed", labels=_terminal_labels(list(issue.labels), MERGED)
        )
        self._safe_comment(issue.number, format_merged_into(into))

    def _decline(self, issue, *, reason: str) -> None:
        self._tracker.transition_issue(
            issue.number, state="closed", labels=_terminal_labels(list(issue.labels), DECLINED)
        )
        self._safe_comment(issue.number, f"decline：{reason or '（未给原因）'}")

    def _run_agent(
        self, *, proposals: list, ready: list, trend: list[tuple[str, int, str, str]]
    ) -> str:
        msg = self._review_message(proposals=proposals, ready=ready, trend=trend)
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="owner",
            timeout=_ADMIT_TIMEOUT,
            on_event=self._on_event,
        )

    def _review_message(
        self, *, proposals: list, ready: list, trend: list[tuple[str, int, str, str]]
    ) -> str:
        return (
            "你是投资与组合治理 Owner。以下是本批开放 ProposalView、既有 ready item 和体验趋势。"
            "逐条作出 admit、merge、decline 或 hold 决策，并校准优先级与产品边界。相同价值方向应合并到信息"
            "更完整的合法目标；`covers`"
            "仅是 merge 建议，显式 decision 优先。\n"
            "从价值、证据、范围、重叠、交付风险五个维度留下判断。不重新执行 Triage 的报告诊断、PM 的"
            "产品发现或 Synthesize 的结构设计，也不根据来源自动准入。\n\n"
            f"## 待评审提案（{len(proposals)} 条）\n{self._format_index(proposals)}\n\n"
            f"## 已在 ready 的工作项（{len(ready)} 条，判重参照）\n{self._format_index(ready)}\n\n"
            f"## 体感曲线\n{self._format_trend(trend)}\n\n"
            "评审只依据 ProposalView 与组合上下文；证据不足就 hold，不回到原始会话重新诊断。\n\n"
            "评审完成后调用 `submit_admission` 一次：`decisions` 每条待评审提案一项，并填写五维评估"
            "，同时填写 product_boundary 与 abstraction_quality（未列出的默认 "
            "hold）。字段/枚举由工具 input_schema 强校验。"
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
                "## Owner 组合评审",
                f"- 价值：{decision.get('value_assessment', '')}",
                f"- 证据：{decision.get('evidence_assessment', '')}",
                f"- 范围：{decision.get('scope_assessment', '')}",
                f"- 重叠：{decision.get('overlap_assessment', '')}",
                f"- 交付风险：{decision.get('delivery_risk', '')}",
            ]
        )

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
