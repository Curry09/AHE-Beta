# Spec-0042/T5: Divergent identifies product capability gaps from session behavior evidence.
"""Divergent (capability discovery) driver.

Experience trends provide the retrieval index, session timeline/beat/step provide on-demand evidence. Open proposals and ready items serve only as
duplication-direction reference. Output written to the proposal plane marked from-divergent; Architect is responsible for cross-proposal absorption, Owner
for final handoff.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ahe_beta.demand.agent_runtime import read_submit, run_agent_def
from ahe_beta.demand.evidence_contract import build_evidence_envelope, project_for_role
from ahe_beta.demand.issue_schema import (
    FROM_DIVERGENT,
    PROPOSAL,
    READY,
    plane,
    round_label,
)
from ahe_beta.demand.proposal_view import format_proposal_reference_list
from ahe_beta.demand.role_contract import render_pm_artifact, validate_pm
from ahe_beta.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from ahe_beta.models import IssueDraft, OpenIssue
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore

_DIVERGENT_TIMEOUT = 3600
# Per-round candidate limit; semantic absorption across proposals is Architect's responsibility.
_MAX_CANDIDATES = 3

StatusFn = Callable[..., None]


@dataclass
class DivergentOutcome:
    """propose_once once: newly arrived candidate ticket number."""

    proposal_numbers: list[int] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


class Divergent:
    """Form a proposal from session behavior capabilities without modifying code or workflow state."""

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
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        self._round_provider = round_provider
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

    def propose_once(self) -> DivergentOutcome:
        recovery_key = self._recovery_key()
        recovery_unit = (
            self._recovery.unit(round_no=self._round_no(), stage="divergent", key=recovery_key)
            if self._recovery is not None
            else None
        )
        if recovery_unit is not None:
            frozen = recovery_unit["input"]
            trend = [tuple(item) for item in frozen["trend"]]
            reference = [OpenIssue.from_dict(item) for item in frozen["reference"]]
        else:
            # Full reference used to understand product status; PM does not halt generation due to adjacent value directions; cross-proposal absorption is judged by Architect.
            backlog = self._tracker.list_open_issues()
            reference = [i for i in backlog if plane(i.labels) in (PROPOSAL, READY)]
            trend = self._feeling_trend()
        if self._recovery is not None:
            recovery_unit = self._recovery.begin_unit(
                round_no=self._round_no(),
                stage="divergent",
                key=recovery_key,
                input_value={
                    "trend": [list(item) for item in trend],
                    "reference": [item.to_dict() for item in reference],
                },
                expected_postconditions={"completed": True},
                dependencies=(self._feedback_dependency,),
            )
            if recovery_unit.get("status") == "completed":
                saved = self._recovery.read_output(
                    round_no=self._round_no(), stage="divergent", key=recovery_key
                )
                observed = recovery_unit.get("observed_postconditions") or {}
                return DivergentOutcome(
                    proposal_numbers=[int(n) for n in observed.get("proposal_numbers") or []],
                    artifacts=[dict(item) for item in saved.get("parsed") or []],
                )
        self._emit(
            running=True,
            status=f"Discovering opportunities… (sessions={len(trend)} · references={len(reference)})",
        )

        if recovery_unit is not None and recovery_unit.get("output_digest"):
            saved = self._recovery.read_output(
                round_no=self._round_no(), stage="divergent", key=recovery_key
            )
            parsed = list(saved.get("parsed") or [])
            result_text = "[replayed saved divergent output]"
        else:
            result_text = self._run_agent(trend=trend, reference=reference)
            raw = read_submit(result_text, "proposals") or []
            parsed = raw[:_MAX_CANDIDATES]
            if self._recovery is not None:
                self._recovery.save_output(
                    round_no=self._round_no(),
                    stage="divergent",
                    key=recovery_key,
                    output={"parsed": parsed},
                )

        numbers: list[int] = []
        if parsed:
            self._tracker.ensure_labels([PROPOSAL, FROM_DIVERGENT])
        round_no = self._round_provider() if self._round_provider is not None else None
        known_sessions = {sid for _, _, _, sid in trend if sid}
        for index, item in enumerate(parsed):
            if not item.get("title"):
                continue
            if validate_pm(item, known_sessions=known_sessions):
                continue
            body = render_pm_artifact(item)
            labels = [PROPOSAL, FROM_DIVERGENT]
            if isinstance(round_no, int) and round_no > 0:
                labels.append(round_label(round_no))
            draft = IssueDraft(title=str(item["title"]), body=body, labels=labels)
            if self._recovery is not None:
                ref = self._tracker.create_issue_once(
                    draft,
                    operation_key=operation_key(recovery_key, "proposal", index),
                )
            else:
                ref = self._tracker.create_issue(draft)
            from ahe_beta.observations.grants import grant

            grant(
                store=self._store,
                issue=ref.number,
                sessions=set(item["evidence_sessions"]),
                pm_origin=True,
            )
            numbers.append(ref.number)

        self._emit(
            running=False,
            status=(
                f"Created {len(numbers)} capability proposals (awaiting admission)"
                if numbers
                else "No product proposals this round"
            ),
            proposals=numbers,
            detail=(result_text or None),
        )
        if self._recovery is not None:
            self._recovery.complete_unit(
                round_no=self._round_no(),
                stage="divergent",
                key=recovery_key,
                observed_postconditions={
                    "completed": True,
                    "proposal_numbers": numbers,
                },
            )
        return DivergentOutcome(proposal_numbers=numbers, artifacts=[dict(item) for item in parsed])

    def _round_no(self) -> int:
        round_no = current_usage_context().round_no
        if round_no is None:
            raise RecoveryConflictError("divergent recovery requires a bound round number")
        return round_no

    def _recovery_key(self) -> str:
        context = current_usage_context()
        return operation_key(context.operation or "divergent", "model-output")

    def _run_agent(self, *, trend: list[tuple[str, int, str, str]], reference: list) -> str:
        # The global PM view is an index of compact, deterministic projections.
        # It deliberately does not concatenate raw timeline/step output.
        known_sessions = {sid for _, _, _, sid in trend if sid}
        goal_index = self._goal_index(trend)
        msg = (
            "You are Product PM. The full visible user-experience index, open proposals, and "
            "ready items follow. Understand what users were trying to accomplish and the "
            "experience tensions their behavior reveals before proposing product opportunities. "
            "Existing proposals provide product-state context; overlap does not invalidate a "
            "candidate. PM goes independently to Owner; Architect does not read or absorb PM "
            "proposals. Verify using get_session_timeline with session IDs; continue to beats "
            "and steps only when needed. Do not read sessions files directly.\n"
            f"Submit at most {_MAX_CANDIDATES} product insights this round, each traceable to "
            "specific session evidence.\n\n"
            f"## Experience trend (index: time, score 1-4, reason, session handle)\n{self._format_trend(trend)}\n\n"
            "## Goal-aware experience summary (deterministic L1; goals, key actions, and feedback only)\n"
            f"{self._format_goal_index(goal_index)}\n\n"
            f"## Existing proposals / ready items ({len(reference)})\n{self._format_issues(reference)}\n\n"
            "After investigating, call `submit_divergent` once. `proposals` contains 0..n entries "
            "(an empty array if none), each separating user_goal, observed_behaviors, "
            "experience_tension, product_opportunity, desired_outcome, evidence_sessions, "
            "solution_level, abstraction_rationale, and optional related_proposals. The tool "
            "enforces the field contract."
        )
        from ahe_beta.usage import current_usage_context  # noqa: PLC0415

        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="divergent",
            tracker=self._tracker,
            source_issue_ids={i.number for i in reference},
            timeout=_DIVERGENT_TIMEOUT,
            on_event=self._on_event,
            subject={"kind": "round", "id": str(current_usage_context().round_no or "")},
            evidence={
                "default_level": "L1",
                "allowed_levels": ["L2", "L3"],
                "session_count": len(goal_index),
                "session_ids": [
                    str(row.get("session_id")) for row in goal_index if row.get("session_id")
                ],
            },
            allowed_session_ids=known_sessions,
        )

    def _goal_index(self, trend: list[tuple[str, int, str, str]]) -> list[dict]:
        rows: list[dict] = []
        seen: set[str] = set()
        for _ts, _score, _reason, session_id in trend:
            if not session_id:
                continue
            if session_id in seen:
                continue
            seen.add(session_id)
            try:
                session = self._store.load(session_id)
            except FileNotFoundError:
                continue
            try:
                envelope = self._store.load_user_feedback_envelope(session_id)
            except FileNotFoundError:
                envelope = build_evidence_envelope(session).to_dict()
            # Spec-0084/T4: the frozen grading summary is joined separately from raw objective logs.
            from ahe_beta.demand.evidence_contract import session_execution_facts

            envelope.update(
                session_execution_facts(
                    session, assessment_summaries=self._store.load_assessment_summaries(session_id)
                )
            )
            rows.append(project_for_role(envelope, "pm"))
        return rows

    @staticmethod
    def _format_goal_index(rows: list[dict]) -> str:
        import json

        if not rows:
            return "(No goal evidence available; do not guess for older or missing sessions)"
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
    def _format_issues(issues: list) -> str:
        return format_proposal_reference_list(issues)

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

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
