# Spec-0042/T5：Synthesize 在规范化 ProposalView 上形成结构提案。
"""Synthesizer 驱动器。

该角色读取 ready queue、开放 ProposalView、体验趋势，按需检索会话/制品观测证据并只读检查
harness 现状。输出写入 proposal 平面并标记 from-synthesize。`covers` 是 Synthesizer 对来源提案
的吸收决定。PM 路线不进入本角色的提案、ready 输入或证据授权，直接交给 Owner。
Owner 协调双轨交接并保留独立验收。RFC 标签和 submit_rfcs 工具属于提案协议。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.demand.agent_runtime import read_submit, run_agent_def
from auto_designer.demand.issue_schema import (
    DIVERGENT,
    FROM_DIVERGENT,
    FROM_SYNTHESIZE,
    MERGED,
    NEEDS_TRIAGE,
    OBSERVATION_GAP,
    OPENAGENTS,
    PROPOSAL,
    READY,
    REPORT,
    RFC_LABEL,
    TRIAGED,
    filter_synthesizer_round,
    format_covers_line,
    plane,
    round_label,
)
from auto_designer.demand.proposal_view import evidence_session_ids, format_proposal_list
from auto_designer.demand.role_contract import render_synthesis_artifact, validate_synthesis
from auto_designer.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from auto_designer.models import IssueDraft, OpenIssue
from auto_designer.tracker.base import IssueTracker
from auto_designer.usage import current_usage_context
from auto_designer.user.session_store import SessionStore

# 一次 propose_once 是多轮工具调用（读文件 + 综合 + 按需 timeline/beat/step 渐进下钻）；给足墙钟防挂死。
_SYNTHESIS_TIMEOUT = 3600

StatusFn = Callable[..., None]


@dataclass
class SynthesisOutcome:
    """一次 propose_once 的结果：产出的结构提案与被吸收来源。"""

    proposal_numbers: list[int] = field(default_factory=list)
    merged_numbers: list[int] = field(default_factory=list)
    failed_merges: dict[int, str] = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    rejected_proposals: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


@dataclass(frozen=True)
class _Proposal:
    """解析后的结构提案：标题、规范化字段和 Synthesizer 的吸收决定。"""

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


class Synthesizer:
    """synthesize 驱动器：综合全局、创建结构提案并吸收其 covers 来源。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        round_provider: Callable[[], int | None] | None = None,
        recovery: RecoveryStore | None = None,
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
        # Spec-0055/T4: set only for a single protocol-recovery call when the model
        # returns without invoking submit_rfcs; keep the normal prompt stable.
        self._force_submit_prompt = False
        self._recovery = recovery

    def bind_recovery(self, recovery: RecoveryStore) -> None:
        """Attach the experiment ledger after role construction."""
        self._recovery = recovery

    def propose_once(self) -> SynthesisOutcome:
        round_no = self._round_provider() if self._round_provider is not None else None
        recovery_key = self._recovery_key()
        recovery_unit = (
            self._recovery.unit(
                round_no=self._recovery_round_no(), stage="synthesizer", key=recovery_key
            )
            if self._recovery is not None
            else None
        )
        if recovery_unit is not None:
            frozen = recovery_unit["input"]
            backlog = [OpenIssue.from_dict(item) for item in frozen["backlog"]]
            trend = [tuple(item) for item in frozen["trend"]]
        else:
            if not getattr(self._tracker, "synthesizer_batch_scope", False):
                from auto_designer.observations.delivery_gaps import ingest_delivery_gaps

                ingest_delivery_gaps(store=self._store, tracker=self._tracker)
            # PM products stay on their independent route.  A PM-origin diagnostic
            # gap is still a design input, despite carrying FROM_DIVERGENT.
            backlog = filter_synthesizer_round(
                (
                    i
                    for i in self._tracker.list_open_issues()
                    if OBSERVATION_GAP in i.labels
                    or not {FROM_DIVERGENT, DIVERGENT}.intersection(i.labels)
                ),
                round_no=round_no,
            )
            trend = self._feeling_trend()
        if self._recovery is not None:
            recovery_unit = self._recovery.begin_unit(
                round_no=self._recovery_round_no(),
                stage="synthesizer",
                key=recovery_key,
                input_value={
                    "backlog": [item.to_dict() for item in backlog],
                    "trend": [list(item) for item in trend],
                },
                expected_postconditions={"completed": True},
                dependencies=("triage",),
            )
            if recovery_unit.get("status") == "completed":
                observed = recovery_unit.get("observed_postconditions") or {}
                return SynthesisOutcome(
                    proposal_numbers=[int(n) for n in observed.get("proposal_numbers") or []],
                    merged_numbers=[int(n) for n in observed.get("merged_numbers") or []],
                    failed_merges={
                        int(k): str(v) for k, v in (observed.get("failed_merges") or {}).items()
                    },
                    artifacts=[dict(item) for item in observed.get("artifacts") or []],
                    rejected_proposals=[
                        dict(item) for item in observed.get("rejected_proposals") or []
                    ],
                )
        # Spec-0029/T4：输入 = ready 工作队列 + 待准入提案索引（编排保证跑在本轮 triage 之后，
        # 索引因此含本轮新升的 from-triage 提案）。提案索引兼作「勿重复提」参照。
        ready = [i for i in backlog if plane(i.labels) == READY]
        proposals_open = [i for i in backlog if plane(i.labels) == PROPOSAL]
        self._emit(
            running=True,
            status=f"综合中…（ready={len(ready)} · 待准入提案={len(proposals_open)}）",
        )

        if recovery_unit is not None and recovery_unit.get("output_digest"):
            saved = self._recovery.read_output(
                round_no=self._recovery_round_no(), stage="synthesizer", key=recovery_key
            )
            parsed = [
                _Proposal(
                    title=str(item["title"]),
                    artifact=dict(item["artifact"]),
                    covers=tuple(int(n) for n in item.get("covers") or []),
                )
                for item in saved.get("parsed") or []
            ]
            result_text = "[replayed saved synthesizer output]"
        else:
            result_text = self._run_agent(
                ready=ready, proposals=proposals_open, trend=trend, runtime=""
            )
            parsed = self._proposals_from_submit(result_text)
            if read_submit(result_text, "proposals") is None:
                # A prose answer is not a design result.  Give the model exactly one
                # constrained recovery turn; the driver remains the authority and
                # will persist an empty result if this also fails.
                self._force_submit_prompt = True
                try:
                    retry_text = self._run_agent(
                        ready=ready, proposals=proposals_open, trend=trend, runtime=""
                    )
                finally:
                    self._force_submit_prompt = False
                parsed = self._proposals_from_submit(retry_text)
            if self._recovery is not None:
                self._recovery.save_output(
                    round_no=self._recovery_round_no(),
                    stage="synthesizer",
                    key=recovery_key,
                    output={
                        "parsed": [
                            {
                                "title": proposal.title,
                                "artifact": proposal.artifact,
                                "covers": list(proposal.covers),
                            }
                            for proposal in parsed
                        ]
                    },
                )

        # The same filtered backlog also bounds state transitions.
        coverable = {i.number: i for i in backlog if plane(i.labels) in (REPORT, PROPOSAL)}
        visible_proposals = {i.number for i in [*ready, *proposals_open]}
        numbers: list[int] = []
        merged_numbers: list[int] = []
        failed_merges: dict[int, str] = {}
        merged_sources: set[int] = set()
        rejected_proposals: list[dict] = []
        round_name = round_label(round_no) if type(round_no) is int and round_no > 0 else None
        if parsed:
            self._tracker.ensure_labels(
                [PROPOSAL, FROM_SYNTHESIZE] + ([round_name] if round_name else [])
            )
        for proposal_index, prop in enumerate(parsed):
            violations = validate_synthesis(prop.artifact, visible_proposals=visible_proposals)
            if violations:
                rejected_proposals.append(
                    {"title": prop.title, "reasons": [v.code for v in violations]}
                )
                continue
            source_ids = set(prop.artifact["source_proposals"])
            covers = tuple(n for n in prop.covers if n in coverable and n not in merged_sources)
            body = render_synthesis_artifact(prop.artifact)
            source_sessions = evidence_session_ids(
                [item for item in [*ready, *proposals_open] if item.number in source_ids]
            )
            if source_sessions:
                body += "\n\n## 证据引用\n\n" + "\n".join(
                    f"- session_id: {sid}" for sid in sorted(source_sessions)
                )
            covers_line = format_covers_line(list(covers))
            if covers_line:
                # 机器行 = Synthesizer 吸收决定的单一真源（消费方：状态迁移、web 展示）。创建后不改写。
                body = f"{body}\n\n{covers_line}"
            labels = [PROPOSAL, FROM_SYNTHESIZE] + ([round_name] if round_name else [])
            draft = IssueDraft(title=str(prop.title), body=body, labels=labels)
            proposal_key = operation_key(recovery_key, "proposal", proposal_index)
            if self._recovery is not None:
                ref = self._tracker.create_issue_once(draft, operation_key=proposal_key)
            else:
                ref = self._tracker.create_issue(draft)
            from auto_designer.observations.grants import authorized_sessions, grant

            trusted_sessions = set().union(
                *(authorized_sessions(store=self._store, issue=n) for n in source_ids)
            )
            grant(store=self._store, issue=ref.number, sessions=trusted_sessions)
            numbers.append(ref.number)
            for source_number in covers:
                source = coverable[source_number]
                try:
                    self._merge_covered(
                        source,
                        into=ref.number,
                        operation_prefix=(
                            operation_key(proposal_key, "source", source_number)
                            if self._recovery is not None
                            else None
                        ),
                    )
                except Exception as exc:  # noqa: BLE001  单条来源失败不废目标提案
                    failed_merges[source_number] = f"{type(exc).__name__}: {exc}"
                else:
                    failed_merges.pop(source_number, None)
                    merged_sources.add(source_number)
                    merged_numbers.append(source_number)

        self._emit(
            running=False,
            status=(
                f"提了 {len(numbers)} 条结构提案，吸收 {len(merged_numbers)} 条来源（待准入）"
                if numbers
                else "本轮无结构提案"
            ),
            proposals=numbers,
            detail=(result_text or None),  # 最终报告全文（详情面板展示，不截断）
        )
        result = SynthesisOutcome(
            proposal_numbers=numbers,
            merged_numbers=merged_numbers,
            failed_merges=failed_merges,
            artifacts=[dict(prop.artifact) for prop in parsed],
            rejected_proposals=rejected_proposals,
        )
        if self._recovery is not None:
            if failed_merges:
                self._recovery.fail_unit(
                    round_no=self._recovery_round_no(),
                    stage="synthesizer",
                    key=recovery_key,
                    error=f"source merges incomplete: {sorted(failed_merges)}",
                )
                raise RecoveryConflictError(
                    f"synthesizer source merges remain incomplete: {sorted(failed_merges)}"
                )
            self._recovery.complete_unit(
                round_no=self._recovery_round_no(),
                stage="synthesizer",
                key=recovery_key,
                observed_postconditions={
                    "completed": True,
                    "proposal_numbers": numbers,
                    "merged_numbers": merged_numbers,
                    "failed_merges": {},
                    "artifacts": [dict(prop.artifact) for prop in parsed],
                    "rejected_proposals": rejected_proposals,
                },
            )
        return result

    def _merge_covered(self, issue, *, into: int, operation_prefix: str | None = None) -> None:
        """按 Synthesizer 的 covers 决定整体吸收一个仍开放的来源。"""
        drop = {
            PROPOSAL,
            REPORT,
            READY,
            OPENAGENTS,
            NEEDS_TRIAGE,
            TRIAGED,
            RFC_LABEL,
            DIVERGENT,
        }
        labels = [label for label in issue.labels if label not in drop]
        labels.append(MERGED)
        self._tracker.transition_issue(
            issue.number, state="closed", labels=list(dict.fromkeys(labels))
        )
        self._safe_comment(
            issue.number,
            f"merged-into: #{int(into)}",
            operation_key=(
                operation_key(operation_prefix, "merge-comment") if operation_prefix else None
            ),
        )

    def _recovery_round_no(self) -> int:
        value = current_usage_context().round_no
        if value is None and self._round_provider is not None:
            value = self._round_provider()
        if type(value) is not int or value <= 0:
            raise RecoveryConflictError("synthesizer recovery requires a bound round number")
        return value

    def _recovery_key(self) -> str:
        context = current_usage_context()
        return operation_key(context.operation or "synthesizer", "model-output")

    def _run_agent(
        self,
        *,
        ready: list,
        proposals: list,
        trend: list[tuple[str, int, str, str]],
        runtime: str,
    ) -> str:
        # Keep the legacy driver/replay signature, but don't inject aggregates
        # inferred from an earlier artifact's fields or source constants.
        del runtime
        msg = (
            "你是 Synthesize。以下是 ready queue 与开放 ProposalView。只分析已有提案之间的结构关系、"
            "共同张力和可复用机制；每条输出必须引用至少两个可见提案。体验趋势仅作"
            "背景证据，不能替代跨提案关系。\n"
            "若可见 ProposalView 已携带会话证据引用，可按需查阅观测文件、时间线、beat、step "
            "验证关系；不得用这些工具脱离 proposal 重新发现单票需求。\n"
            "结构提案不规定数据结构、协议或实施步骤。`covers` 是你对来源提案的吸收决定；"
            "结构提案创建成功后，driver 会合并关闭其中仍开放的 report/proposal 来源。未放入"
            "covers 的来源继续独立交付。\n\n"
            f"## ready 工作队列（{len(ready)} 条）\n{self._format_backlog(ready)}\n\n"
            f"## 开放 ProposalView（{len(proposals)} 条）\n{self._format_backlog(proposals)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            "调查完成后调用 `submit_rfcs` 一次：`proposals` 为本轮 0..n 条结构 proposal（无则空数组）；"
            "每条含 title、source_proposals、relationship、common_tension、structural_direction、"
            "expected_leverage、solution_level、abstraction_rationale + 可选 covers（整体吸收来源）。"
            "字段契约由工具 input_schema 强校验，不必也不要在正文里手抄 schema。"
        )
        if self._force_submit_prompt:
            msg += (
                "\n\n【协议收尾】你刚才没有调用 submit_rfcs。现在停止读取文件和继续调查，"
                "只调用一次 submit_rfcs 提交 0..n 条结果；没有可提交内容就提交空数组，"
                "不要用解释文字代替工具调用。"
            )
        from auto_designer.observations.grants import sessions_for_issues
        from auto_designer.usage import current_usage_context  # noqa: PLC0415

        authorized = sessions_for_issues(store=self._store, issues=[*ready, *proposals])

        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="synthesizer",
            tracker=self._tracker,
            source_issue_ids={i.number for i in [*ready, *proposals]},
            timeout=_SYNTHESIS_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "round", "id": str(current_usage_context().round_no or "")},
            evidence={
                "default_level": "proposal_view",
                "allowed_levels": ["L2", "L3", "L4"],
                "source_proposals": [int(item.number) for item in [*ready, *proposals]],
                "session_ids": sorted(authorized),
            },
            allowed_session_ids=authorized,
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

    def _safe_comment(self, number: int, body: str, *, operation_key: str | None = None) -> None:
        """合并审计评论 best effort；状态迁移已成功时评论失败不回滚。"""
        try:
            marker = "<!-- openagents:agent=auto-designer -->"
            signed = body if marker in body else f"{body}\n\n{marker}"
            if operation_key is not None:
                self._tracker.add_comment_once(number, signed, operation_key=operation_key)
            else:
                self._tracker.add_comment(number, signed)
        except Exception:  # noqa: BLE001
            pass

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
