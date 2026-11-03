# Spec-0042/T5: Architect forms structural proposals on normalized ProposalView.
"""Architect driver.

This role reads the ready queue, open ProposalView, experience trends, retrieves session/artifact
observation evidence as needed, and performs read-only checks on harness status. Output is written
to the proposal plane and marked from-architect. `covers` represents the Architect's absorption
decision for source proposals. PM-track proposals do not enter this role's proposals, ready input,
or evidence authorization; they are passed directly to Owner. Owner coordinates the dual-track
handoff and retains independent acceptance. RFC labels and submit_rfcs tool belong to the proposal
protocol.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ahe_beta.demand.agent_runtime import read_submit, run_agent_def
from ahe_beta.demand.issue_schema import (
    DIVERGENT,
    FROM_ARCHITECT,
    FROM_DIVERGENT,
    MERGED,
    NEEDS_TRIAGE,
    OBSERVATION_GAP,
    OPENAGENTS,
    PROPOSAL,
    READY,
    REPORT,
    RFC_LABEL,
    TRIAGED,
    filter_architect_round,
    format_covers_line,
    plane,
    round_label,
)
from ahe_beta.demand.proposal_view import evidence_session_ids, format_proposal_list
from ahe_beta.demand.role_contract import render_synthesis_artifact, validate_synthesis
from ahe_beta.loop.recovery import RecoveryConflictError, RecoveryStore, operation_key
from ahe_beta.models import IssueDraft, OpenIssue
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore

# A single propose_once involves multiple tool calls (reading files + synthesis + progressive drill-down through timeline/beat/step as needed); allow sufficient wall-clock time to prevent hangs.
_SYNTHESIS_TIMEOUT = 3600

StatusFn = Callable[..., None]


@dataclass
class SynthesisOutcome:
    """Result of a single propose_once: the structural proposal produced and the source proposals absorbed."""

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
    """Parsed structural proposal: title, normalized fields, and the Architect's absorption decision."""

    title: str
    artifact: dict
    covers: tuple[int, ...] = ()


def _parse_covers(raw: object) -> tuple[int, ...]:
    """The covers field of a proposal → deduplicated positive integer tuple; non-list or invalid elements are silently discarded (liberal input, strict output)."""
    if not isinstance(raw, list):
        return ()
    out: list[int] = []
    for x in raw:
        # bool is a subclass of int and must be explicitly excluded (True would be treated as #1).
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            continue
        if x not in out:
            out.append(x)
    return tuple(out)


class Architect:
    """Architect driver: synthesize global context, create structural proposals, and absorb their source covers."""

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
        self._store = store  # Experience curve data source (local SessionStore index)
        self._repo = Path(harness_repo)  # Read-only grounding: agent views harness status
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = (
            on_event  # Process events (kind, text): assistant/tool/result for the timeline
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
                round_no=self._recovery_round_no(), stage="architect", key=recovery_key
            )
            if self._recovery is not None
            else None
        )
        if recovery_unit is not None:
            frozen = recovery_unit["input"]
            backlog = [OpenIssue.from_dict(item) for item in frozen["backlog"]]
            trend = [tuple(item) for item in frozen["trend"]]
        else:
            if not getattr(self._tracker, "architect_batch_scope", False):
                from ahe_beta.observations.delivery_gaps import ingest_delivery_gaps

                ingest_delivery_gaps(store=self._store, tracker=self._tracker)
            # PM products stay on their independent route.  A PM-origin diagnostic
            # gap is still a design input, despite carrying FROM_DIVERGENT.
            backlog = filter_architect_round(
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
                stage="architect",
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
        # Spec-0029/T4: Input = ready work queue + pending-admission proposal index (orchestration ensures it runs after this round's triage,
        # index thus includes from-triage proposals elevated this round). The proposal index also serves as a reference for "do not duplicate."
        ready = [i for i in backlog if plane(i.labels) == READY]
        proposals_open = [i for i in backlog if plane(i.labels) == PROPOSAL]
        self._emit(
            running=True,
            status=f"Synthesizing… (ready={len(ready)} · awaiting admission={len(proposals_open)})",
        )

        if recovery_unit is not None and recovery_unit.get("output_digest"):
            saved = self._recovery.read_output(
                round_no=self._recovery_round_no(), stage="architect", key=recovery_key
            )
            parsed = [
                _Proposal(
                    title=str(item["title"]),
                    artifact=dict(item["artifact"]),
                    covers=tuple(int(n) for n in item.get("covers") or []),
                )
                for item in saved.get("parsed") or []
            ]
            result_text = "[replayed saved architect output]"
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
                    stage="architect",
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
                [PROPOSAL, FROM_ARCHITECT] + ([round_name] if round_name else [])
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
                body += "\n\n## Evidence references\n\n" + "\n".join(
                    f"- session_id: {sid}" for sid in sorted(source_sessions)
                )
            covers_line = format_covers_line(list(covers))
            if covers_line:
                # Machine row = single source of truth for the Architect's absorption decision (consumers: state transition, web display). Not modified after creation.
                body = f"{body}\n\n{covers_line}"
            labels = [PROPOSAL, FROM_ARCHITECT] + ([round_name] if round_name else [])
            draft = IssueDraft(title=str(prop.title), body=body, labels=labels)
            proposal_key = operation_key(recovery_key, "proposal", proposal_index)
            if self._recovery is not None:
                ref = self._tracker.create_issue_once(draft, operation_key=proposal_key)
            else:
                ref = self._tracker.create_issue(draft)
            from ahe_beta.observations.grants import authorized_sessions, grant

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
                except Exception as exc:  # noqa: BLE001  Single source failure does not invalidate the target proposal
                    failed_merges[source_number] = f"{type(exc).__name__}: {exc}"
                else:
                    failed_merges.pop(source_number, None)
                    merged_sources.add(source_number)
                    merged_numbers.append(source_number)

        self._emit(
            running=False,
            status=(
                f"Created {len(numbers)} structural proposals, absorbed {len(merged_numbers)} sources (awaiting admission)"
                if numbers
                else "No structural proposals this round"
            ),
            proposals=numbers,
            # Full final report (shown in detail panel, not truncated)
            detail=(result_text or None),
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
                    stage="architect",
                    key=recovery_key,
                    error=f"source merges incomplete: {sorted(failed_merges)}",
                )
                raise RecoveryConflictError(
                    f"architect source merges remain incomplete: {sorted(failed_merges)}"
                )
            self._recovery.complete_unit(
                round_no=self._recovery_round_no(),
                stage="architect",
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
        """Wholly absorb a still-open source according to the Architect's covers decision."""
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
            raise RecoveryConflictError("architect recovery requires a bound round number")
        return value

    def _recovery_key(self) -> str:
        context = current_usage_context()
        return operation_key(context.operation or "architect", "model-output")

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
            "You are Architect. The ready queue and open ProposalViews follow. Analyze only "
            "structural relationships, shared tensions, and reusable mechanisms among existing "
            "proposals. Every output must cite at least two visible proposals. Experience trends "
            "are background evidence, not a substitute for cross-proposal relationships.\n"
            "If a visible ProposalView includes session evidence references, inspect observation "
            "files, timelines, beats, or steps as needed to verify a relationship. Do not use these "
            "tools to rediscover individual-ticket requirements outside the proposals.\n"
            "Structural proposals do not prescribe data structures, protocols, or implementation "
            "steps. `covers` is your decision to absorb source proposals. Once a structural "
            "proposal is created, the driver merges and closes its listed report/proposal sources "
            "that remain open. Sources omitted from covers remain independently deliverable.\n\n"
            f"## Ready queue ({len(ready)})\n{self._format_backlog(ready, store=self._store)}\n\n"
            f"## Open ProposalViews ({len(proposals)})\n{self._format_backlog(proposals, store=self._store)}\n\n"
            f"## Experience trend (time, score 1-4)\n{self._format_trend(trend)}\n\n"
            "After investigating, call `submit_rfcs` once. `proposals` contains 0..n structural "
            "proposals for this round (an empty array if none), each with title, source_proposals, "
            "relationship, common_tension, structural_direction, expected_leverage, solution_level, "
            "abstraction_rationale, and optional covers (fully absorbed sources). The tool's "
            "input_schema enforces the field contract. Do not copy the schema into the body."
        )
        if self._force_submit_prompt:
            msg += (
                "\n\n[Protocol completion] You did not call submit_rfcs. Stop reading files and "
                "investigating now. Call submit_rfcs exactly once to submit 0..n results; submit "
                "an empty array if there is nothing to submit. Explanatory prose cannot replace "
                "the tool call."
            )
        from ahe_beta.observations.grants import sessions_for_issues
        from ahe_beta.usage import current_usage_context  # noqa: PLC0415

        authorized = sessions_for_issues(store=self._store, issues=[*ready, *proposals])

        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            role="architect",
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
        """Experience over time: [(created_at, score, reason, session_id)], in ascending time order.

        reason = the user's final state sentence "why". session_id is for get_session_timeline to retrieve by experience point.
        """
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
    def _format_backlog(backlog: list, *, store) -> str:
        return format_proposal_list(backlog, store=store)

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

    @staticmethod
    def _proposals_from_submit(text: str) -> list[_Proposal]:
        """Parse a _Proposal list from the submit_rfcs return value (= the return value of agent.run).

        submit_rfcs is a stop tool; binding returns `{"proposals":[...]}` — nexau already performs strict validation at the tool layer
        (title/fields required, fields keys locked, covers as int array, no user-created fields). If submit is not called or
        parsing fails → empty list (no-op this round), no error thrown to break the loop. covers still goes through _parse_covers with liberal input, strict output.
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
        """Merge audit comments on best-effort basis; comment failure does not roll back when state transition has already succeeded."""
        try:
            marker = "<!-- openagents:agent=ahe-beta -->"
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
