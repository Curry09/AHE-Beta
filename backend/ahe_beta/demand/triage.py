# Spec-0042/T3: Triage normalizes a single report into a proposal or terminal conclusion.
"""Triage (report normalization) driver.

Input consists of raw report, read-only harness source code, and progressive session evidence. accept atomically updates the same ticket to a task-agnostic
proposal and saves the raw report in audit comments; reject and needs_info transition to declined terminal state. Cross-proposal deduplication and
admission are performed separately by Owner.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import requests
from jsonschema import Draft202012Validator

from ahe_beta.demand.agent_contract import dispositions_input_schema
from ahe_beta.demand.agent_runtime import read_submit, run_agent_def
from ahe_beta.demand.evidence_contract import build_evidence_envelope, project_for_role
from ahe_beta.demand.issue_schema import (
    DECLINED,
    FROM_ARCHITECT,
    FROM_DIVERGENT,
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
from ahe_beta.demand.issue_schema import (
    render as schema_render,
)
from ahe_beta.demand.issue_schema import (
    validate as schema_validate,
)
from ahe_beta.demand.role_contract import validate_triage
from ahe_beta.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.tracker.gitea import GiteaError, IssueMigrationError
from ahe_beta.usage import bind_usage_context, current_usage_context
from ahe_beta.user.session_store import SessionStore

_TRIAGE_TIMEOUT = 900
# Leave room below the observed Gitea title boundary for UTF-8 and server
# normalization.  The full model title remains in the immutable triage receipt.
_PROPOSAL_TITLE_MAX_BYTES = 240
_TRACKER_APPLY_ATTEMPTS = 3
# Workflow labels (plane/terminal/provenance/legacy workflow/priority)—remove all when retagging, preserve only attributes like round-*.
_WORKFLOW_LABELS = frozenset(
    {
        REPORT,
        PROPOSAL,
        READY,
        DECLINED,
        MERGED,
        FROM_TRIAGE,
        FROM_ARCHITECT,
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
    """Result of one triage_once: issue numbers matched by each disposition."""

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
    """accept: Retain round-* and similar attribute labels, remove old type and all workflow labels, add confirmed kind + proposal + from-triage + suggested priority (when valid; Owner may change during approval)."""
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
    """reject/needs_info: Retain type + round-* etc., remove flat labels, add declined terminal state."""
    keep = [x for x in current if x not in (REPORT, NEEDS_TRIAGE, PROPOSAL, TRIAGED)]
    return list(dict.fromkeys([*keep, DECLINED]))


def _retryable_tracker_error(exc: Exception) -> bool:
    """Only transient transport/server errors qualify for replay of a saved output."""
    if isinstance(exc, IssueMigrationError):
        return isinstance(exc.primary, Exception) and _retryable_tracker_error(exc.primary)
    return isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
        isinstance(exc, GiteaError) and exc.status in {408, 429, 500, 502, 503, 504}
    )


def _proposal_body(*, normalized: str, evidence: dict | None = None) -> str:
    """proposal default context contains only normalized conclusions; specific cases progressively sourced from comments/timeline."""
    body = f"## Triage normalized proposal (implementation target: harness)\n\n{normalized.strip()}"
    # Keep only source references in the proposal.  The detailed user evidence
    # remains in SessionStore and is retrieved through the gated timeline tools.
    if evidence:
        refs = evidence.get("evidence_refs") or []
        session_id = str(evidence.get("session_id") or "")
        if session_id or refs:
            body += "\n\n## Evidence references (goal-aware L1)\n\n"
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
    """Triage nexau agent driver: investigate each report in sequence → elevate to proposal / decline."""

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
        self._repo = Path(harness_repo)  # Read-only grounding: agent observes harness current state
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        self._recovery = recovery
        self._feedback_dependency = "users"

    def bind_recovery(self, recovery: RecoveryStore) -> None:
        """Attach the experiment ledger after role construction."""
        self._recovery = recovery

    def bind_feedback_dependency(self, prerequisite: str) -> None:
        """Share the outer feedback prerequisite, including independent assessment."""
        if prerequisite not in {"users", "feedback_imported", "objective_grading"}:
            raise ValueError("unsupported feedback prerequisite")
        self._feedback_dependency = prerequisite

    def triage_once(
        self, pending: list | None = None, shard: tuple[int, int] | None = None
    ) -> TriageOutcome:
        """Process a batch of reports. When pending=None, auto-fetch all reports from flat tickets (including legacy needs-triage data);
        when shard=(k, n), fetch only pending[k::n] after sorting by ticket number (Spec-0029/T8 orchestration layer sharding with parallelism—duplicate detection moved to Owner, output as unconstrained proposals, sharding is independent and partitions are disjoint). Can also pass a pending subset directly."""
        if pending is None:
            backlog = self._tracker.list_open_issues()
            pending = sorted(
                (i for i in backlog if plane(i.labels) == REPORT), key=lambda i: i.number
            )
            if shard is not None:
                k, n = shard
                pending = pending[k :: max(1, n)]
        if not pending:
            self._emit(running=False, status="No reports awaiting triage")
            return TriageOutcome()
        self._emit(running=True, status=f"Triaging {len(pending)} reports…")

        outcome = TriageOutcome()
        details: list[str] = []
        # Each report has its own independent model context; adjacent reports cannot pollute problem definition or evidence judgment.
        for issue in pending:
            recovery_key = self._recovery_key(issue.number)
            recovery_unit = self._begin_recovery_item(issue=issue, key=recovery_key)
            if recovery_unit is not None and recovery_unit.get("status") == "completed":
                self._restore_completed_item(
                    unit=recovery_unit, issue_number=issue.number, outcome=outcome
                )
                continue
            session_id = self._session_id_for_issue(issue.number)
            from ahe_beta.observations.grants import grant

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
            # One isolated report has one decision. Validate the whole output
            # before saving it or applying any tracker mutation; conflicting
            # decisions must never partially promote then close the same issue.
            if len(dispositions) != 1:
                outcome.failed[issue.number] = "invalid-report-disposition-count"
                self._fail_recovery_item(
                    key=recovery_key,
                    error=outcome.failed[issue.number],
                )
                continue
            if (
                recovery_unit is not None
                and recovery_unit.get("output_digest")
                and not Draft202012Validator(dispositions_input_schema()).is_valid(
                    {"dispositions": dispositions}
                )
            ):
                # Saved output bypasses the live tool validator. Check the current
                # contract before a stale field format can change any issue state.
                outcome.failed[issue.number] = "saved-submit-contract-mismatch"
                self._fail_recovery_item(key=recovery_key, error=outcome.failed[issue.number])
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
                        "The implementation target is outside harness scope"
                        if target == "outside_harness"
                        else "The implementation target is not yet confirmed to be within harness scope"
                    )
                    d["reason"] = (
                        f"{boundary} (original disposition was accept, implementation_target={target!r}). "
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
                f"Triaged {outcome.handled}: promoted {len(outcome.accepted)}, "
                f"rejected {len(outcome.rejected)}, needs info {len(outcome.needs_info)}, "
                f"failed {len(outcome.failed)}"
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
        # d already validated by nexau input_schema (issue/disposition required, three-value enum, fields keys locked).
        try:
            num = int(d.get("issue"))
        except (TypeError, ValueError):
            return
        issue = by_number.get(num)
        if issue is None:  # Not in this batch set → skip (prevent out-of-bounds modifications)
            return
        disp = str(d.get("disposition", "")).strip()

        if disp == "accept":
            kind = str(d.get("kind", "")).strip().lower()
            # Invalid kind → treat as insufficient information (retry in next round)
            if kind not in USER_KINDS:
                self._decline(
                    issue,
                    "Insufficient information",
                    f"triage supplied an invalid kind {kind!r}",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            fields = d.get("fields", {})
            model_title = str(d.get("proposal_title", "")).strip()
            proposal_title = _proposal_title(model_title)
            if not proposal_title:
                self._decline(
                    issue,
                    "Insufficient information",
                    "triage did not provide a task-independent proposal_title",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            errs = schema_validate(kind=kind, fields=fields, section="triage")
            if errs:  # Normalized fields incomplete → downgrade to needs_info (ensure elevated proposals have complete positioning)
                self._decline(
                    issue,
                    "Insufficient information",
                    f"triage localization is incomplete: {'；'.join(errs)}",
                    outcome.needs_info,
                    operation_prefix=operation_prefix,
                )
                return
            # Suggested value; Owner may change during approval
            priority = str(d.get("priority", "")).strip().upper()
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
            # Archive raw evidence first; tracker updates core title/body/labels in single pass, avoiding partial proposal migration.
            if not self._safe_comment(
                num,
                f"## Original user report (case evidence, not an implementation target)\n\n"
                f"**Original title:** {issue.title}\n\n{issue.body or '(empty)'}",
                operation_key=(
                    operation_key(operation_prefix, "original-report") if operation_prefix else None
                ),
            ):
                outcome.warnings.setdefault(num, []).append(
                    "Original report audit comment write failed"
                )
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
                "Rejected",
                str(d.get("reason", "")).strip(),
                outcome.rejected,
                operation_prefix=operation_prefix,
            )
        elif disp == "needs_info":
            self._decline(
                issue,
                "Insufficient information",
                str(d.get("reason", "")).strip(),
                outcome.needs_info,
                operation_prefix=operation_prefix,
            )
        # Unknown disposition: ignore (ticket remains in report plane, retriage next round)

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
        """declined terminal state + write reason + close."""
        labels = _declined_labels(list(issue.labels))
        already_applied = False
        if operation_prefix is not None:
            already_applied = self._check_recovery_decline(issue=issue, labels=labels)
        if not already_applied:
            self._tracker.transition_issue(issue.number, state="closed", labels=labels)
        self._safe_comment(
            issue.number,
            f"{head}: {reason or '(No reason provided)'}",
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
        except Exception:  # noqa: BLE001  Single chain failure does not drag down the rest
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
                if (envelope.get("harness_source") or {}).get("ref") in {None, "unavailable"}:
                    session = self._session_for_issue(int(issue.number))
                    envelope["harness_source"] = build_evidence_envelope(session).harness_source
                # Spec-0084/T4: join immutable conditions and sealed public assessment facts.
                from ahe_beta.demand.evidence_contract import session_execution_facts

                session = self._store.load(sid)
                envelope.update(
                    session_execution_facts(
                        session, assessment_summaries=self._store.load_assessment_summaries(sid)
                    )
                )
                return project_for_role(envelope, "triage")
            except FileNotFoundError:
                pass
        return project_for_role(build_evidence_envelope(None, report=report), "triage")

    def _run_agent(self, *, pending: list) -> str:
        # triage only does 'single-record normalization': receives only this batch of reports + read-only code + progressively fetched single-session traces (including that session's subjective score,
        # to inform suggested priority). Does not feed deduplication reference/aggregated runtime_agg/global subjective curves—cross-proposal absorption belongs to Architect, global belongs to architect.
        issue = pending[0] if pending else None
        triage_evidence = (
            self._evidence_for_issue(issue)
            if issue is not None
            else project_for_role(build_evidence_envelope(None), "triage")
        )
        msg = (
            "The following raw reports are pending in this batch. Determine each kind, inspect "
            "harness source as needed, and retrieve session evidence by issue number. If evidence "
            "is insufficient, use timeline, then beat, then step; do not read sessions files directly.\n"
            "accept requires a task-independent proposal_title and complete normalized fields; "
            "reject or needs_info requires a reason. Handle each report independently; Owner "
            "handles cross-proposal deduplication.\n\n"
            f"## Reports pending triage ({len(pending)})\n{self._format_issues(pending)}\n\n"
            "## Goal-aware user evidence for the current report "
            "(deterministic L1; missing fields explicitly unavailable)\n"
            f"{self._format_evidence(triage_evidence)}\n\n"
            "After investigating, call submit_triage once. dispositions may contain only the "
            "current report."
        )
        report_id = str(pending[0].number) if pending else ""
        from contextlib import nullcontext

        from ahe_beta.demand.source import bind_harness_source, current_harness_source

        source = current_harness_source()
        report_sha = triage_evidence.get("harness_source", {}).get("ref")
        source_scope = (
            bind_harness_source(source.repo if source is not None else self._repo, report_sha)
            if report_sha and report_sha != "unavailable"
            else nullcontext()
        )
        with (
            source_scope,
            bind_usage_context(harness_sha=report_sha)
            if report_sha and report_sha != "unavailable"
            else nullcontext(),
        ):
            history: list[object] | None = None

            def remember_history(messages: list[object]) -> None:
                nonlocal history
                history = messages

            for attempt in range(2):
                message = msg
                if attempt:
                    closing = (
                        "\nThe previous invocation did not submit a valid disposition. This is the "
                        "last bounded opportunity to finish. Do not guess missing facts or keep "
                        "searching out-of-scope directories. Call submit_triage promptly using "
                        "the available evidence. If no reliable judgment is possible, submit "
                        "needs_info and identify what is missing."
                    )
                    # The eight-iteration finalizer continues the evidence already read;
                    # it must not spend that budget starting the investigation again.
                    message = closing if history else msg + closing
                    if self._on_event is not None:
                        self._on_event("retry", f"report #{report_id}: retry missing submit (2/2)")
                result = run_agent_def(
                    self._agent_def,
                    message,
                    store=self._store,
                    repo=self._repo,
                    role="triager",
                    tracker=self._tracker,
                    source_issue_ids={i.number for i in pending},
                    timeout=_TRIAGE_TIMEOUT,
                    on_event=self._on_event,
                    max_iterations=8 if attempt else None,
                    history=history if attempt else None,
                    on_history=remember_history,
                    subject={"kind": "report", "id": report_id},
                    evidence={
                        "default_level": "L1",
                        "session_id": triage_evidence.get("session_id", "unavailable"),
                        "allowed_levels": ["L2", "L3", "L4"],
                        "evidence_refs": list(triage_evidence.get("evidence_refs") or [])[:24],
                    },
                )
                submitted = read_submit(result, "dispositions")
                if submitted is not None and len(submitted) == 1:
                    return result
        return result

    @staticmethod
    def _format_evidence(evidence: dict) -> str:
        import json

        return json.dumps(evidence, ensure_ascii=False, indent=2)

    @staticmethod
    def _format_issues(issues: list) -> str:
        if not issues:
            return "(none)"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in issues
        )

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
