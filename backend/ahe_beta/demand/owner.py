# Owner is a handoff router from demand to OpenAgents, not a solution reviewer.
"""Owner driver: package proposals losslessly and hand off to OpenAgents.

Generators (triage/architect/divergent) handle problem diagnosis, product discovery, and structural design; Owner does not re-judge root cause,
does not select prompt/runtime implementation layers, and does not compress scope due to delivery risk. Model coordinates PM/structural roadmap delivery overlap,
supplements handoff summary, preserves required capabilities, and segments independent acceptance. Log recovery initially restricts to mechanical admission set;
items in the set not listed by the model default to direct handoff, preventing omission from becoming implicit veto.

Routing actions:
- admit → add `openagents` handoff plane token;
- merge → only for duplicates with identical normalized title and body; non-exact duplicates stay as independent handoffs;
- hold  → only for missing information essential to forming development tasks, with explicit gap statement.

Architect's `covers` already executes source merge during structural proposal creation; Owner does not consume that relationship again. Owner
only processes current open proposals for handoff, preserving backward-compatible merge path for items with identical normalized title and body.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ahe_beta.demand.agent_runtime import read_submit, run_agent_def
from ahe_beta.demand.issue_schema import (
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
from ahe_beta.demand.proposal_view import format_proposal_list, normalized_proposal_body
from ahe_beta.demand.role_contract import validate_owner
from ahe_beta.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from ahe_beta.models import OpenIssue
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore

_ADMIT_TIMEOUT = 1800
StatusFn = Callable[..., None]


@dataclass
class AdmitOutcome:
    """Result of one admit_once: ticket numbers matched by each decision."""

    admitted: list[int] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)
    declined: list[int] = field(default_factory=list)
    held: list[int] = field(default_factory=list)
    # Backward compatibility with old API; always empty after full model review.
    mechanical: list[int] = field(default_factory=list)
    invalid: dict[int, str] = field(default_factory=dict)
    failed: dict[int, str] = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)


def _ready_labels(current: list[str], priority: str | None) -> list[str]:
    """admit: remove flat/legacy workflow labels, add `openagents` handoff token; replace old P* with valid priority (final priority).

    Spec-0032/T3: Owner admission no longer directly applies ready—`openagents` is the handoff plane (vigil) discovery label; vigil
    `_intake` applies ready after discovery and triggers curator dependency sorting; Owner applying ready directly causes vigil to skip the ticket
    and curator never runs (admission semantics unchanged: plane() treats both labels as READY plane).
    """
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED}
    keep = [x for x in current if x not in drop]
    if priority in PRIORITIES:
        keep = [x for x in keep if x not in PRIORITIES]
        keep.append(priority)
    return list(dict.fromkeys([*keep, OPENAGENTS]))


def _terminal_labels(current: list[str], terminal: str) -> list[str]:
    """merge/decline: remove plane labels (including handoff plane token), add terminal label."""
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED, READY, OPENAGENTS}
    keep = [x for x in current if x not in drop]
    return list(dict.fromkeys([*keep, terminal]))


class Owner:
    """Handoff router: model curates handoff, driver ensures independent capabilities are not compressed."""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        review: bool = True,
        recovery: RecoveryStore | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        # review=False = pure mechanical handoff: do not invoke model, handoff log recovery confirms designed proposals.
        self._review = review
        self._recovery = recovery

    def bind_recovery(self, recovery: RecoveryStore) -> None:
        """Attach the experiment ledger after role construction."""
        self._recovery = recovery

    def admit_once(self) -> AdmitOutcome:
        recovery_key = self._recovery_key()
        recovery_unit = (
            self._recovery.unit(round_no=self._round_no(), stage="owner", key=recovery_key)
            if self._recovery is not None
            else None
        )
        if recovery_unit is not None:
            frozen = recovery_unit["input"]
            backlog = [OpenIssue.from_dict(item) for item in frozen["backlog"]]
            trend = [tuple(item) for item in frozen["trend"]]
        else:
            backlog = self._tracker.list_open_issues()
            trend = self._feeling_trend()
        proposals = [i for i in backlog if plane(i.labels) == PROPOSAL]
        if self._recovery is not None:
            eligible = self._designed_proposal_ids()
            proposals = [i for i in proposals if i.number in eligible]
        ready = [i for i in backlog if plane(i.labels) == READY]
        if self._recovery is not None:
            recovery_unit = self._recovery.begin_unit(
                round_no=self._round_no(),
                stage="owner",
                key=recovery_key,
                input_value={
                    "backlog": [item.to_dict() for item in backlog],
                    "trend": [list(item) for item in trend],
                },
                expected_postconditions={"completed": True},
                dependencies=("divergent", "architect"),
            )
            if recovery_unit.get("status") == "completed":
                return self._outcome_from_observed(
                    recovery_unit.get("observed_postconditions") or {}
                )
        if not proposals:
            if self._recovery is not None:
                if not recovery_unit.get("output_digest"):
                    self._recovery.save_output(
                        round_no=self._round_no(),
                        stage="owner",
                        key=recovery_key,
                        output={"decisions": []},
                    )
                self._recovery.complete_unit(
                    round_no=self._round_no(),
                    stage="owner",
                    key=recovery_key,
                    observed_postconditions={"completed": True},
                )
            self._emit(running=False, status="No proposals awaiting admission")
            return AdmitOutcome()
        self._emit(running=True, status=f"Preparing handoff… ({len(proposals)} proposals)")

        outcome = AdmitOutcome()
        by_number = {i.number: i for i in backlog}

        # Cross-route overlap is a coordination relation, never an absorption instruction.
        review_needed = proposals
        decisions: list[dict] = []
        if recovery_unit is not None and recovery_unit.get("output_digest"):
            saved = self._recovery.read_output(
                round_no=self._round_no(), stage="owner", key=recovery_key
            )
            decisions = [dict(item) for item in saved.get("decisions") or []]
        else:
            if review_needed and self._review:
                result_text = self._run_agent(proposals=review_needed, ready=ready, trend=trend)
                decisions = read_submit(result_text, "decisions") or []
            if self._recovery is not None:
                self._recovery.save_output(
                    round_no=self._round_no(),
                    stage="owner",
                    key=recovery_key,
                    output={"decisions": decisions},
                )
        # review=False or item not listed by agent: items in admission set default to direct handoff in pass 2.

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
            # Only decide within current review batch; first explicit decision wins on duplicates.
            if num not in explicit:
                routing = dict(d)
                overlaps = d.get("delivery_overlaps", [])
                visible = visible_routing - {num}
                if not isinstance(overlaps, list):
                    overlaps = []
                    outcome.invalid[num] = (
                        "delivery_overlaps must be an array of visible issue numbers; handoff retained"
                    )
                valid = [n for n in overlaps if type(n) is int and n in visible]
                if len(valid) != len(overlaps):
                    outcome.invalid[num] = (
                        "delivery_overlaps contained invisible or self references; filtered them and retained the handoff"
                    )
                routing["delivery_overlaps"] = list(dict.fromkeys(valid))
                explicit[num] = routing

        # merge target must be an existing ready item or explicitly admitted proposal in this batch; driver will also verify
        # that both are exact duplicates, cannot suppress independent capabilities based on "same value direction".
        existing_ready = {i.number for i in ready}
        valid_merge_targets = existing_ready | {
            num
            for num, decision in explicit.items()
            if str(decision.get("decision", "")).strip() == "admit"
        }

        # pass 1: explicit decisions
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
                        outcome.invalid[num] = (
                            "merge target must be an existing ready item or a proposal admitted in this batch"
                        )
                        outcome.admitted.append(num)
                        continue
                    if self._dedupe_signature(issue) != self._dedupe_signature(target):
                        self._admit(
                            issue, priority=None, note="handoff: non-duplicate merge preserved"
                        )
                        self._safe_comment(num, self._decision_note(d))
                        outcome.invalid[num] = (
                            "Only proposals with exactly identical titles and normalized bodies may merge; handed off independently"
                        )
                        outcome.admitted.append(num)
                        continue
                    self._merge(issue, into=target.number)
                    self._safe_comment(num, self._decision_note(d))
                    outcome.merged.append(num)
                else:  # hold or unknown; schema removed decline
                    outcome.held.append(num)
            except Exception as exc:  # noqa: BLE001  single failure isolation, but must enter structured result
                outcome.failed[num] = f"{type(exc).__name__}: {exc}"
                if num not in outcome.held:
                    outcome.held.append(num)

        # pass 2: remaining proposals default to direct handoff. Architect's covers already processed at creation stage.
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
                f"Handoff: admit {len(outcome.admitted)} · "
                f"merge {len(outcome.merged)} · decline {len(outcome.declined)} · "
                f"hold {len(outcome.held)} · failed {len(outcome.failed)}"
            ),
            proposals=outcome.admitted,
        )
        if self._recovery is not None:
            observed = {
                "completed": True,
                "admitted": outcome.admitted,
                "merged": outcome.merged,
                "declined": outcome.declined,
                "held": outcome.held,
                "mechanical": outcome.mechanical,
                "invalid": outcome.invalid,
                "failed": outcome.failed,
                "artifacts": outcome.artifacts,
            }
            if outcome.failed:
                details = "; ".join(
                    f"#{number}: {error}" for number, error in sorted(outcome.failed.items())
                )
                self._recovery.fail_unit(
                    round_no=self._round_no(),
                    stage="owner",
                    key=recovery_key,
                    error=f"owner decisions incomplete: {details}",
                )
                raise RecoveryConflictError(f"owner decisions remain incomplete: {details}")
            self._recovery.complete_unit(
                round_no=self._round_no(),
                stage="owner",
                key=recovery_key,
                observed_postconditions=observed,
            )
        return outcome

    def _designed_proposal_ids(self) -> set[int]:
        """Admit PM output, Architect output, and sources Architect saw but retained.

        The recovery ledger is the authority for what Architect actually saw.  A
        diagnostic request arriving after its snapshot remains pending for the
        next design stage, regardless of its labels.
        """
        round_state = self._recovery.round_state(round_no=self._round_no()) or {}
        stages = round_state.get("stages") or {}
        if (stages.get("architect") or {}).get("status") != "completed":
            raise RecoveryConflictError("owner requires a completed architect stage")

        pm: set[int] = set()
        for unit in ((stages.get("divergent") or {}).get("units") or {}).values():
            if unit.get("status") == "completed":
                pm.update((unit.get("observed_postconditions") or {}).get("proposal_numbers") or [])

        seen: set[int] = set()
        merged: set[int] = set()
        architect_proposals: set[int] = set()
        for unit in (stages["architect"].get("units") or {}).values():
            if unit.get("status") != "completed":
                continue
            frozen = unit.get("input") or {}
            issues = frozen.get("issues") or frozen.get("backlog") or []
            seen.update(int(item["number"]) for item in issues)
            observed = unit.get("observed_postconditions") or {}
            merged.update(observed.get("merged_numbers") or [])
            architect_proposals.update(observed.get("proposal_numbers") or [])
        return pm | architect_proposals | (seen - merged)

    def _round_no(self) -> int:
        value = current_usage_context().round_no
        if type(value) is not int or value <= 0:
            raise RecoveryConflictError("owner recovery requires a bound round number")
        return value

    def _recovery_key(self) -> str:
        context = current_usage_context()
        return operation_key(context.operation or "owner", "decisions")

    @staticmethod
    def _outcome_from_observed(observed: dict) -> AdmitOutcome:
        return AdmitOutcome(
            admitted=[int(n) for n in observed.get("admitted") or []],
            merged=[int(n) for n in observed.get("merged") or []],
            declined=[int(n) for n in observed.get("declined") or []],
            held=[int(n) for n in observed.get("held") or []],
            mechanical=[int(n) for n in observed.get("mechanical") or []],
            invalid={int(k): str(v) for k, v in (observed.get("invalid") or {}).items()},
            failed={int(k): str(v) for k, v in (observed.get("failed") or {}).items()},
            artifacts=[dict(item) for item in observed.get("artifacts") or []],
        )

    def _admit(self, issue, *, priority: str | None, note: str) -> None:
        from ahe_beta.demand.delivery_evidence import publish_delivery_evidence

        publish_delivery_evidence(tracker=self._tracker, store=self._store, issue=issue)
        current = self._tracker.get_issue(number=issue.number)
        labels = _ready_labels(list(current["labels"]), priority)
        if set(labels) != set(current["labels"]):
            self._tracker.set_labels(issue.number, labels)
        self._safe_comment(issue.number, note)

    def _merge(self, issue, *, into: int) -> None:
        from ahe_beta.demand.delivery_evidence import publish_delivery_evidence
        from ahe_beta.observations.grants import authorized_sessions, grant, is_pm_source

        sessions = authorized_sessions(store=self._store, issue=into)
        sessions |= authorized_sessions(store=self._store, issue=issue.number)
        grant(
            store=self._store,
            issue=into,
            sessions=sessions,
            pm_origin=is_pm_source(store=self._store, issue=into)
            or is_pm_source(store=self._store, issue=issue.number),
        )
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
        from ahe_beta.usage import current_usage_context  # noqa: PLC0415

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
            "You are the Delivery Router from demand-side roles to OpenAgents. This batch's open "
            "ProposalViews, existing ready items, and experience trends follow. Package each "
            "handoff without losing information. Do not review upstream solutions, choose an "
            "implementation layer, or narrow a problem because it is less risky or easier to "
            "deliver. Default to admit; merge only duplicates with exactly identical titles and "
            "normalized bodies; hold only for information required to form a development task. "
            "Architect already handled `covers` sources when creating structural proposals. "
            "Do not close or merge those sources again.\n"
            "Preserve every distinct user problem, product capability, or structural mechanism "
            "as an independent handoff or acceptance group.\n\n"
            "PM goes independently to Owner; Architect absorbs only non-PM sources. Identify "
            "delivery overlap across the routes: optional delivery_overlaps lists related issue "
            "numbers in this batch or ready queue, and handoff_summary explains shared work and "
            "independent acceptance boundaries. Overlap is not duplication; admit each side "
            "separately. This field does not instruct merging, dependencies, or automatic "
            "implementation consolidation.\n\n"
            f"## Proposals for review ({len(proposals)})\n{self._format_index(proposals, store=self._store)}\n\n"
            f"## Existing ready items ({len(ready)}, duplicate references)\n{self._format_index(ready, store=self._store)}\n\n"
            f"## Experience trend\n{self._format_trend(trend)}\n\n"
            "## Goal-evidence summary (audit metadata only, not objective assessment)\n"
            f"{goal_summary}\n\n"
            "Prepare handoffs from ProposalView only; do not return to raw sessions for another "
            "diagnosis.\n\nAfter organizing the handoff, call `submit_admission` once, with one "
            "item per proposal and handoff_summary, preserved_capabilities, and acceptance_groups. "
            "The driver still directly hands off omitted proposals by default."
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
            return "(No goal metadata available)"
        return json.dumps(rows, ensure_ascii=False, indent=2)

    def _feeling_trend(self) -> list[tuple[str, int, str, str]]:
        rows = sorted(self._store.index(include_invalid=True), key=lambda e: e["created_at"])
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
    def _format_index(issues: list, *, store) -> str:
        """Admission index uses canonical ProposalView shared by all downstream roles."""
        return format_proposal_list(issues, store=store)

    @staticmethod
    def _format_trend(trend: list[tuple[str, int, str, str]]) -> str:
        if not trend:
            return "(No experience data yet)"
        lines = []
        for ts, score, reason, sid in trend:
            why = f" — {reason}" if reason else ""
            sid_bit = f" [session={sid}]" if sid else ""
            lines.append(
                f"- {ts}{sid_bit}: {score if score is not None else 'unavailable (unscored)'}{why}"
            )
        return "\n".join(lines)

    def _safe_comment(self, number: int, body: str) -> None:
        try:
            # Cross-system provenance contract: OpenAgents treats comments with
            # this machine identity as automation output, so Owner decisions do
            # not enter its human-reply queue.  Apply it to every Owner comment,
            # rather than matching individual decision text downstream.
            marker = "<!-- openagents:agent=ahe-beta -->"
            signed = body if marker in body else f"{body}\n\n{marker}"
            if self._recovery is not None:
                self._tracker.add_comment_once(
                    number,
                    signed,
                    operation_key=operation_key(self._recovery_key(), "comment", number, signed),
                )
            else:
                self._tracker.add_comment(number, signed)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _decision_note(decision: dict) -> str:
        return "\n".join(
            [
                "## OpenAgents handoff package",
                f"- Summary: {decision.get('handoff_summary', '')}",
                "- Preserved capabilities: "
                + ", ".join(decision.get("preserved_capabilities", [])),
                "- Acceptance groups: " + ", ".join(decision.get("acceptance_groups", [])),
                "- Delivery overlaps (association, not merging): "
                + (", ".join(f"#{n}" for n in decision.get("delivery_overlaps", [])) or "none"),
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
