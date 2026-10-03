# Spec-0042/T3：Triage 将单条 report 规范化为 proposal 或终态结论。
"""Triage（报告规范化）驱动器。

输入由原始 report、只读 harness 源码和渐进式会话证据组成。accept 将同一票原子更新为任务无关的
proposal，并把原始报告保存在审计评论中；reject 与 needs_info 转入 declined 终态。跨提案判重和
准入分别由 Owner 执行。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import requests

from auto_designer.demand.agent_runtime import norm_label, read_submit, run_agent_def
from auto_designer.demand.evidence_contract import build_evidence_envelope, project_for_role
from auto_designer.demand.issue_schema import (
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
from auto_designer.demand.issue_schema import (
    fields_of as schema_fields_of,
)
from auto_designer.demand.issue_schema import (
    render as schema_render,
)
from auto_designer.demand.issue_schema import (
    validate as schema_validate,
)
from auto_designer.demand.role_contract import validate_triage
from auto_designer.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from auto_designer.tracker.base import IssueTracker
from auto_designer.tracker.gitea import GiteaError, IssueMigrationError
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.session_store import SessionStore

_TRIAGE_TIMEOUT = 900
# Leave room below the observed Gitea title boundary for UTF-8 and server
# normalization.  The full model title remains in the immutable triage receipt.
_PROPOSAL_TITLE_MAX_BYTES = 240
_TRACKER_APPLY_ATTEMPTS = 3
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


def _proposal_title(value: str) -> str:
    """Return a deterministic UTF-8-safe title that Gitea can round-trip."""
    title = value.strip()
    if len(title.encode("utf-8")) <= _PROPOSAL_TITLE_MAX_BYTES:
        return title
    limit = _PROPOSAL_TITLE_MAX_BYTES - len("…".encode())
    chars: list[str] = []
    size = 0
    for char in title:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            break
        chars.append(char)
        size += width
    return "".join(chars).rstrip() + "…"


def _declined_labels(current: list[str]) -> list[str]:
    """reject/needs_info：保留 type + round-* 等，去平面标签，加 declined 终态。"""
    keep = [x for x in current if x not in (REPORT, NEEDS_TRIAGE, PROPOSAL, TRIAGED)]
    return list(dict.fromkeys([*keep, DECLINED]))


def _retryable_tracker_error(exc: Exception) -> bool:
    """Only transient transport/server errors qualify for replay of a saved output."""
    if isinstance(exc, IssueMigrationError):
        return isinstance(exc.primary, Exception) and _retryable_tracker_error(exc.primary)
    return isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
        isinstance(exc, GiteaError) and exc.status in {408, 429, 500, 502, 503, 504}
    )


def _fields_by_label_to_key(kind: str, fields: dict) -> dict:
    """agent 用中文 label 填字段 → 转成 schema key（root_cause/boundary/acceptance）。
    按归一后的 label 匹配（去空白），容忍 LLM 的空格差异。"""
    label_to_key = {norm_label(f.label): f.key for f in schema_fields_of(kind=kind)}
    out: dict[str, str] = {}
    for k, v in fields.items():
        key = label_to_key.get(norm_label(k), str(k))  # 已是 key 则原样
        out[key] = v
    return out


def _proposal_body(*, normalized: str, evidence: dict | None = None) -> str:
    """proposal 默认上下文只含规范化结论；具体案例从评论/timeline 渐进取证。"""
    body = f"## Triage 规范化提案（实施对象：harness）\n\n{normalized.strip()}"
    # Keep only source references in the proposal.  The detailed user evidence
    # remains in SessionStore and is retrieved through the gated timeline tools.
    if evidence:
        refs = evidence.get("evidence_refs") or []
        session_id = str(evidence.get("session_id") or "")
        if session_id or refs:
            body += "\n\n## 证据引用（目标感知 L1）\n\n"
            if session_id:
                body += f"- session_id: {session_id}\n"
            for ref in refs[:24]:
                if isinstance(ref, dict):
                    kind = str(ref.get("kind") or "evidence")
                    locator = str(ref.get("locator") or "")
                    suffix = f" ({locator})" if locator else ""
                    body += f"- {kind}{suffix}\n"
    return body


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
        recovery: RecoveryStore | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)  # 只读 grounding：agent 读 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        self._recovery = recovery
        self._feedback_dependency = "users"

    def bind_recovery(self, recovery: RecoveryStore) -> None:
        """Attach the experiment ledger after role construction."""
        self._recovery = recovery

    def bind_feedback_dependency(self, prerequisite: str) -> None:
        """Spec-0079/T3: share the outer feedback stage prerequisite."""
        if prerequisite not in {"users", "feedback_imported"}:
            raise ValueError("unsupported feedback prerequisite")
        self._feedback_dependency = prerequisite

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
            recovery_key = self._recovery_key(issue.number)
            recovery_unit = self._begin_recovery_item(issue=issue, key=recovery_key)
            if recovery_unit is not None and recovery_unit.get("status") == "completed":
                self._restore_completed_item(
                    unit=recovery_unit, issue_number=issue.number, outcome=outcome
                )
                continue
            session_id = self._session_id_for_issue(issue.number)
            from auto_designer.observations.grants import grant

            grant(
                store=self._store,
                issue=issue.number,
                sessions={session_id} if session_id else set(),
            )
            if recovery_unit is not None and recovery_unit.get("output_digest"):
                saved = self._recovery.read_output(
                    round_no=self._round_no(),
                    stage="triage",
                    key=recovery_key,
                )
                dispositions = list(saved.get("dispositions") or [])
                details.append("[replayed saved triage output]")
            else:
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
                self._fail_recovery_item(
                    key=recovery_key,
                    error="triage model output did not contain dispositions",
                )
                continue
            valid_dispositions: list[dict] = []
            for d in dispositions:
                try:
                    target_number = int(d.get("issue"))
                except (TypeError, ValueError):
                    target_number = -1
                if target_number != issue.number:
                    continue
                violations = validate_triage(d, report_number=issue.number)
                if len(violations) == 1 and violations[0].code == "out-of-product-scope":
                    # A model can recognize a real user problem while being
                    # unable to establish that the fix belongs in this product.
                    # Preserve that finding without publishing a proposal or
                    # leaving the whole recovery stage failed forever.
                    target = d["artifact"].get("implementation_target")
                    d = dict(d)
                    d["disposition"] = "reject" if target == "outside_harness" else "needs_info"
                    boundary = (
                        "实施目标在 harness 范围外"
                        if target == "outside_harness"
                        else "尚不能确认实施目标属于 harness"
                    )
                    d["reason"] = (
                        f"{boundary}（原分诊为 accept，implementation_target={target!r}）。"
                        f"{str(d.get('reason') or '').strip()}"
                    )
                    outcome.warnings.setdefault(issue.number, []).append(
                        "out-of-product-scope-normalized"
                    )
                    violations = validate_triage(d, report_number=issue.number)
                if violations:
                    outcome.warnings.setdefault(issue.number, []).extend(v.code for v in violations)
                    outcome.failed[issue.number] = ",".join(v.code for v in violations)
                    continue
                valid_dispositions.append(dict(d))
            if not valid_dispositions and issue.number not in outcome.failed:
                outcome.failed[issue.number] = "missing-report-disposition"
            if outcome.failed.get(issue.number):
                self._fail_recovery_item(
                    key=recovery_key,
                    error=outcome.failed[issue.number],
                )
                continue
            if (
                self._recovery is not None
                and recovery_unit is not None
                and not recovery_unit.get("output_digest")
            ):
                self._recovery.save_output(
                    round_no=self._round_no(),
                    stage="triage",
                    key=recovery_key,
                    output={"dispositions": valid_dispositions},
                )
            for d in valid_dispositions:
                try:
                    outcome.artifacts[issue.number] = dict(d)
                    self._apply_with_retry(
                        d,
                        by_number={issue.number: issue},
                        outcome=outcome,
                        operation_prefix=recovery_key if self._recovery is not None else None,
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome.failed[issue.number] = f"{type(exc).__name__}: {exc}"
            if issue.number in outcome.failed:
                self._fail_recovery_item(key=recovery_key, error=outcome.failed[issue.number])
                continue
            self._complete_recovery_item(
                key=recovery_key,
                issue_number=issue.number,
                outcome=outcome,
            )

        self._emit(
            running=False,
            status=(
                f"分诊 {outcome.handled} 条：升提案 {len(outcome.accepted)}、"
                f"驳回 {len(outcome.rejected)}、待补 {len(outcome.needs_info)}、"
                f"失败 {len(outcome.failed)}"
            ),
            detail="\n".join(details) or None,
        )
        if self._recovery is not None and outcome.failed:
            raise RecoveryConflictError(f"triage items remain incomplete: {sorted(outcome.failed)}")
        return outcome

    def _apply_with_retry(
        self,
        d: dict,
        *,
        by_number: dict,
        outcome: TriageOutcome,
        operation_prefix: str | None,
    ) -> None:
        # The output receipt is durable before this point.  Do not retry a
        # write without one: its model decision and intended post-state would
        # otherwise be unavailable after a process crash.
        attempts = _TRACKER_APPLY_ATTEMPTS if operation_prefix is not None else 1
        for attempt in range(attempts):
            try:
                self._apply(
                    d,
                    by_number=by_number,
                    outcome=outcome,
                    operation_prefix=operation_prefix,
                )
                if attempt:
                    outcome.warnings.setdefault(int(d["issue"]), []).append("tracker-write-retried")
                return
            except Exception as exc:
                if attempt + 1 == attempts or not _retryable_tracker_error(exc):
                    raise
                # _apply checks live state before its next mutation.  A lost
                # response can mean the write succeeded; the next attempt must
                # reconcile rather than blindly repeat it.
                time.sleep(0.5 * (2**attempt))

    def _round_no(self) -> int:
        round_no = current_usage_context().round_no
        if round_no is None:
            raise RecoveryConflictError("triage recovery requires a bound round number")
        return round_no

    def _recovery_key(self, issue_number: int) -> str:
        scope = current_usage_context().operation or "triage"
        return operation_key(scope, "report", issue_number)

    def _begin_recovery_item(self, *, issue, key: str) -> dict | None:
        if self._recovery is None:
            return None
        return self._recovery.begin_unit(
            round_no=self._round_no(),
            stage="triage",
            key=key,
            input_value={"report": issue.to_dict()},
            expected_postconditions={"completed": True},
            dependencies=(self._feedback_dependency,),
        )

    def _fail_recovery_item(self, *, key: str, error: str) -> None:
        if self._recovery is not None:
            self._recovery.fail_unit(
                round_no=self._round_no(),
                stage="triage",
                key=key,
                error=error,
            )

    def _complete_recovery_item(
        self, *, key: str, issue_number: int, outcome: TriageOutcome
    ) -> None:
        if self._recovery is None:
            return
        bucket = next(
            (
                name
                for name, values in (
                    ("accepted", outcome.accepted),
                    ("rejected", outcome.rejected),
                    ("needs_info", outcome.needs_info),
                )
                if issue_number in values
            ),
            "handled",
        )
        self._recovery.complete_unit(
            round_no=self._round_no(),
            stage="triage",
            key=key,
            observed_postconditions={
                "completed": True,
                "issue": issue_number,
                "bucket": bucket,
                "warnings": list(outcome.warnings.get(issue_number) or []),
            },
        )

    def _restore_completed_item(
        self, *, unit: dict, issue_number: int, outcome: TriageOutcome
    ) -> None:
        observed = unit.get("observed_postconditions") or {}
        bucket = str(observed.get("bucket") or "")
        values = getattr(outcome, bucket, None)
        if isinstance(values, list):
            values.append(issue_number)
        warnings = list(observed.get("warnings") or [])
        if warnings:
            outcome.warnings[issue_number] = warnings
        if unit.get("output_digest") and self._recovery is not None:
            saved = self._recovery.read_output(
                round_no=self._round_no(),
                stage="triage",
                key=self._recovery_key(issue_number),
            )
            dispositions = list(saved.get("dispositions") or [])
            if dispositions:
                outcome.artifacts[issue_number] = dict(dispositions[0])

    def snapshot_pending(self) -> list:
        """Return one stable, sorted report snapshot for orchestrator sharding.

        The orchestrator takes this snapshot once before starting parallel
        triagers.  Each worker then receives an explicit issue subset instead
        of re-reading and re-slicing a tracker that other workers are mutating.
        """
        backlog = self._tracker.list_open_issues()
        return sorted((i for i in backlog if plane(i.labels) == REPORT), key=lambda i: i.number)

    def _session_id_for_issue(self, issue_number: int) -> str | None:
        # User reports remain auditable even when the persona protocol was
        # invalid; do not hide the linked session from factual triage.
        return self._store.find_session_id_by_issue(issue_number)

    def _apply(
        self,
        d: dict,
        *,
        by_number: dict,
        outcome: TriageOutcome,
        operation_prefix: str | None = None,
    ) -> None:
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
                    issue,
                    "信息不足",
                    f"triage 给了非法 kind {kind!r}",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            fields = _fields_by_label_to_key(kind, d.get("fields") or {})
            model_title = str(d.get("proposal_title", "")).strip()
            proposal_title = _proposal_title(model_title)
            if not proposal_title:
                self._decline(
                    issue,
                    "信息不足",
                    "triage 未给任务无关 proposal_title",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            errs = schema_validate(kind=kind, fields=fields, section="triage")
            if errs:  # 规范化字段没填全 → 降级 needs_info（保证升上去的提案定位完整）
                self._decline(
                    issue,
                    "信息不足",
                    f"triage 定位不全：{'；'.join(errs)}",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            priority = str(d.get("priority", "")).strip().upper()  # 建议值；Owner 准入时可改
            body = schema_render(kind=kind, fields=fields, section="triage")
            evidence = self._evidence_for_issue(issue)
            proposal_body = _proposal_body(normalized=body, evidence=evidence)
            proposal_labels = _proposal_labels(list(issue.labels), kind, priority)
            already_applied = False
            if operation_prefix is not None:
                already_applied = self._check_recovery_issue(
                    issue=issue,
                    model_title=model_title,
                    proposal_title=proposal_title,
                    proposal_body=proposal_body,
                    proposal_labels=proposal_labels,
                )
            if proposal_title != model_title:
                outcome.warnings.setdefault(num, []).append("proposal-title-shortened")
            # 原始证据先归档；核心 title/body/labels 由 tracker 单次更新，避免半迁移 proposal。
            if not self._safe_comment(
                num,
                f"## 原始用户报告（案例证据，非实现对象）\n\n"
                f"**原始标题：** {issue.title}\n\n{issue.body or '（空）'}",
                operation_key=(
                    operation_key(operation_prefix, "original-report") if operation_prefix else None
                ),
            ):
                outcome.warnings.setdefault(num, []).append("原始报告审计评论写入失败")
            if not already_applied:
                self._tracker.update_issue(
                    num,
                    title=proposal_title,
                    body=proposal_body,
                    labels=proposal_labels,
                )
            outcome.accepted.append(num)

        elif disp == "reject":
            self._decline(
                issue,
                "驳回",
                str(d.get("reason", "")).strip(),
                outcome.rejected,
                operation_prefix=operation_prefix,
            )
        elif disp == "needs_info":
            self._decline(
                issue,
                "信息不足",
                str(d.get("reason", "")).strip(),
                outcome.needs_info,
                operation_prefix=operation_prefix,
            )
        # 未知 disposition：忽略（票仍在 report 平面，下轮再分诊）

    def _check_recovery_issue(
        self,
        *,
        issue,
        model_title: str,
        proposal_title: str,
        proposal_body: str,
        proposal_labels: list[str],
    ) -> bool:
        """Return whether this output is already applied; reject unrelated edits."""
        read = getattr(self._tracker, "get_issue", None)
        if not callable(read):
            return False
        live = read(number=issue.number)
        if live.get("state") != "open":
            raise RecoveryConflictError(f"triage issue #{issue.number} state changed")
        labels = set(live.get("labels") or [])
        original = (
            live.get("title") == issue.title
            and live.get("body") == issue.body
            and labels == set(issue.labels)
        )
        partial_title = str(live.get("title") or "")
        title_from_this_output = partial_title in {model_title, proposal_title} or (
            partial_title.endswith("…") and model_title.startswith(partial_title[:-1])
        )
        partial = (
            live.get("body") == proposal_body
            and labels in (set(issue.labels), set(proposal_labels))
            and title_from_this_output
        )
        applied = (
            partial_title == proposal_title
            and live.get("body") == proposal_body
            and labels == set(proposal_labels)
        )
        if not (original or partial):
            raise RecoveryConflictError(
                f"triage issue #{issue.number} changed outside this migration"
            )
        return applied

    def _decline(
        self,
        issue,
        head: str,
        reason: str,
        bucket: list[int],
        *,
        operation_prefix: str | None = None,
    ) -> None:
        """declined 终态 + 写原因 + 关闭。"""
        labels = _declined_labels(list(issue.labels))
        already_applied = False
        if operation_prefix is not None:
            already_applied = self._check_recovery_decline(issue=issue, labels=labels)
        if not already_applied:
            self._tracker.transition_issue(issue.number, state="closed", labels=labels)
        self._safe_comment(
            issue.number,
            f"{head}：{reason or '（未给原因）'}",
            operation_key=(
                operation_key(operation_prefix, "decision-comment") if operation_prefix else None
            ),
        )
        bucket.append(issue.number)

    def _check_recovery_decline(self, *, issue, labels: list[str]) -> bool:
        """Accept only the frozen report or this disposition's partial/final state."""
        read = getattr(self._tracker, "get_issue", None)
        if not callable(read):
            return False
        live = read(number=issue.number)
        if live.get("title") != issue.title or live.get("body") != issue.body:
            raise RecoveryConflictError(
                f"triage issue #{issue.number} changed outside this migration"
            )
        live_labels = set(live.get("labels") or [])
        desired = set(labels)
        if live.get("state") == "closed" and live_labels == desired:
            return True
        if live.get("state") == "open" and live_labels in (set(issue.labels), desired):
            return False
        raise RecoveryConflictError(f"triage issue #{issue.number} changed outside this migration")

    def _safe_comment(self, number: int, body: str, *, operation_key: str | None = None) -> bool:
        try:
            if operation_key is not None:
                self._tracker.add_comment_once(number, body, operation_key=operation_key)
            else:
                self._tracker.add_comment(number, body)
        except Exception:  # noqa: BLE001  单条挂链失败不拖垮其余
            return False
        return True

    def _session_for_issue(self, issue_number: int):
        """Load the one session linked to this report for deterministic L1 handoff."""
        session_id = self._session_id_for_issue(issue_number)
        if not session_id:
            return None
        try:
            return self._store.load(session_id)
        except FileNotFoundError:
            return None

    def _evidence_for_issue(self, issue) -> dict:
        """Read the persisted handoff, with deterministic legacy reconstruction."""
        sid = self._session_id_for_issue(int(issue.number))
        report = {"issue_id": issue.number, "title": issue.title, "labels": list(issue.labels)}
        if sid:
            try:
                envelope = self._store.load_user_feedback_envelope(sid)
                envelope["source_report"] = report
                return project_for_role(envelope, "triage")
            except FileNotFoundError:
                pass
        return project_for_role(build_evidence_envelope(None, report=report), "triage")

    def _run_agent(self, *, pending: list) -> str:
        # triage 只做「单条规范化」：只给它本批 report + 只读代码 + 按需拉的单局轨迹（含那局体感分，
        # 供建议优先级）。不喂判重参照/聚合 runtime_agg/全局体感曲线——跨提案吸收归 Synthesizer、全局归 synthesize。
        issue = pending[0] if pending else None
        triage_evidence = (
            self._evidence_for_issue(issue)
            if issue is not None
            else project_for_role(build_evidence_envelope(None), "triage")
        )
        msg = (
            "以下是本批待处理的原始报告。逐条确认 kind，按需读取 harness 源码，并以 issue 号检索"
            "对应会话证据。证据不足时依次使用 timeline、beat、step，不直接读取 sessions 文件。\n"
            "accept 必须提供任务无关的 proposal_title 和完整规范化字段；reject 或 needs_info 必须说明"
            "理由。每条报告独立处理，跨提案判重由 Owner 负责。\n\n"
            f"## 待分诊 report（{len(pending)} 条）\n{self._format_issues(pending)}\n\n"
            "## 当前 report 的目标感知用户证据（确定性 L1；缺失字段明确为 unavailable）\n"
            f"{self._format_evidence(triage_evidence)}\n\n"
            "完成调查后调用 submit_triage 一次，dispositions 只能包含当前这一条 report。"
        )
        report_id = str(pending[0].number) if pending else ""
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="triager",
            tracker=self._tracker,
            source_issue_ids={i.number for i in pending},
            timeout=_TRIAGE_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "report", "id": report_id},
            evidence={
                "default_level": "L1",
                "session_id": triage_evidence.get("session_id", "unavailable"),
                "allowed_levels": ["L2", "L3", "L4"],
                "evidence_refs": list(triage_evidence.get("evidence_refs") or [])[:24],
            },
        )

    @staticmethod
    def _format_evidence(evidence: dict) -> str:
        import json

        return json.dumps(evidence, ensure_ascii=False, indent=2)

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
