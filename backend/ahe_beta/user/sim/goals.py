"""Explicit, append-only user goals for the persona control loop.

The goal ledger is deliberately small.  It does not try to infer completion from
natural language or objective test results; it records what the simulated user
currently expects, how that expectation changed, and what the persona claims at
the point of a terminal action.  Objective evaluation remains a separate lane.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class GoalStatus(StrEnum):
    OPEN = "open"
    PARTIAL = "partial"
    MET = "met"
    DROPPED = "dropped"


class GoalKind(StrEnum):
    BASELINE = "baseline"
    CORE = "core"
    REQUEST = "request"
    OPTIONAL = "optional"


GOAL_PROGRESS = frozenset({"unchanged", "advancing", "blocked", "unclear", "complete"})
GOAL_EFFECT_KINDS = frozenset(
    {"advance", "wait", "close", "close_with_reservations", "abandon", "abandon_and_report"}
)
GOAL_UPDATE_OPS = frozenset({"add", "status", "focus", "revise", "relax", "withdraw"})
ACCEPTANCE_BASIS_MODES = frozenset(
    {"subjective", "independent", "delegated", "waived", "unreported"}
)


@dataclass
class Goal:
    goal_id: str
    text: str
    kind: str = GoalKind.CORE.value
    done_if: str = ""
    status: str = GoalStatus.OPEN.value
    evidence_refs: list[str] = field(default_factory=list)
    version: int = 1
    # B0 is revisable.  Keep the origin beside the current text so a final snapshot
    # remains intelligible even when a revision event is filtered by a consumer.
    initial_text: str = ""
    initial_done_if: str = ""

    def prompt_dict(self) -> dict[str, Any]:
        """Current goal only; do not repeatedly place the origin in the LLM context."""
        return {
            "goal_id": self.goal_id,
            "text": self.text,
            "kind": self.kind,
            "done_if": self.done_if,
            "status": self.status,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "text": self.text,
            "kind": self.kind,
            "done_if": self.done_if,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "version": self.version,
            "initial_text": self.initial_text or self.text,
            "initial_done_if": self.initial_done_if if self.initial_text else self.done_if,
        }


@dataclass
class GoalEvent:
    seq: int
    turn: int
    op: str
    goal_id: str
    actor: str = "persona"
    text: str = ""
    kind: str = ""
    status: str = ""
    reason: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    # State transition snapshots make revisions auditable without reconstructing
    # them from a model's prose or relying on event ordering alone.
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_done_if(task: str) -> str:
    """Spec-0056/T1: derive a visible criterion without using benchmark gold."""
    text = str(task or "").strip().lower()
    if any(token in text for token in ("repro", "reproduction", "example", "expected")):
        return "The reported reproduction or expected behavior works after the requested change."
    if any(token in text for token in ("test", "pytest", "regression")):
        return "The requested change is delivered and a relevant test or check reports success."
    return "The requested behavior is delivered and a relevant check reports success."


@dataclass
class GoalLedger:
    """Current goals plus an append-only history of goal changes."""

    goals: dict[str, Goal] = field(default_factory=dict)
    baseline_id: str = "B0"
    focus_goal_id: str = ""
    events: list[GoalEvent] = field(default_factory=list)
    _next_id: int = 1

    @classmethod
    def from_task(cls, task: str, *, done_if: str = "") -> GoalLedger:
        ledger = cls()
        if not done_if.strip():
            done_if = default_done_if(task)
        ledger.goals[ledger.baseline_id] = Goal(
            goal_id=ledger.baseline_id,
            text=task.strip(),
            kind=GoalKind.BASELINE.value,
            done_if=done_if,
            initial_text=task.strip(),
            initial_done_if=done_if,
        )
        ledger.focus_goal_id = ledger.baseline_id
        ledger._record(
            turn=0,
            op="initialize",
            goal_id=ledger.baseline_id,
            actor="system",
            text=task.strip(),
            kind=GoalKind.BASELINE.value,
            after=ledger.goals[ledger.baseline_id].to_dict(),
        )
        return ledger

    def prompt_snapshot(self) -> dict[str, Any]:
        """Compact current view supplied to the persona.

        The current baseline is authoritative for the next decision, while its origin
        and revision count make it explicit that B0 is editable rather than a hidden
        immutable anchor.  Full event history remains in ``snapshot`` for audit.
        """
        revisions = [event for event in self.events if event.op == "revise"]
        return {
            "baseline_id": self.baseline_id,
            "focus_goal_id": self.focus_goal_id,
            # Prompt context gets the current wording only.  The original wording is
            # preserved in snapshot/events for audit, but is not a recurring anchor.
            "goals": [goal.prompt_dict() for goal in self.goals.values()],
            "unresolved": [goal.goal_id for goal in self.unresolved()],
            "baseline_revision_count": len(revisions),
            "recent_goal_changes": [
                {
                    "seq": event.seq,
                    "turn": event.turn,
                    "op": event.op,
                    "goal_id": event.goal_id,
                    "reason": event.reason,
                    "before": dict(event.before),
                    "after": dict(event.after),
                }
                for event in self.events[-4:]
                if event.op != "initialize"
            ],
        }

    def snapshot(self) -> dict[str, Any]:
        snapshot = self.prompt_snapshot()
        snapshot["goals"] = [goal.to_dict() for goal in self.goals.values()]
        snapshot["events"] = [event.to_dict() for event in self.events]
        return snapshot

    def unresolved(self) -> list[Goal]:
        """Goals that must be closed for a normal accept."""
        return [
            goal
            for goal in self.goals.values()
            if goal.kind
            in {
                GoalKind.BASELINE.value,
                GoalKind.CORE.value,
                GoalKind.REQUEST.value,
            }
            and goal.status not in {GoalStatus.MET.value, GoalStatus.DROPPED.value}
        ]

    def _new_id(self) -> str:
        while f"G{self._next_id}" in self.goals:
            self._next_id += 1
        goal_id = f"G{self._next_id}"
        self._next_id += 1
        return goal_id

    @staticmethod
    def _refs(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    @staticmethod
    def _state_view(goal: Goal) -> dict[str, Any]:
        """Small transition view; avoid duplicating evidence lists in every event."""
        return {
            "goal_id": goal.goal_id,
            "text": goal.text,
            "done_if": goal.done_if,
            "kind": goal.kind,
            "status": goal.status,
            "version": goal.version,
        }

    def apply_updates(self, raw: Any, *, turn: int, actor: str = "persona") -> list[dict[str, Any]]:
        """Apply small structured model updates; malformed entries are ignored and logged.

        Supported operations: ``add``, ``status`` (open/partial/met), ``focus``,
        ``revise``, ``relax`` and ``withdraw``.  The baseline cannot be withdrawn,
        but its text and done-if can be revised with a reason; the old and new
        snapshots are retained in the append-only event log.  Relax/withdraw always
        require a reason, so lowering the bar is observable.
        """
        updates = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        applied: list[dict[str, Any]] = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            op = str(update.get("op") or update.get("kind") or "").strip().lower()
            goal_id = str(update.get("goal_id") or "").strip()
            reason = str(update.get("reason") or "").strip()
            refs = self._refs(update.get("evidence_refs"))
            if op == "add":
                text = str(update.get("text") or "").strip()
                if not text:
                    continue
                goal_id = goal_id or self._new_id()
                if goal_id in self.goals:
                    continue
                kind = str(update.get("goal_kind") or update.get("kind") or GoalKind.REQUEST.value)
                if kind not in {item.value for item in GoalKind}:
                    kind = GoalKind.REQUEST.value
                goal = Goal(
                    goal_id=goal_id,
                    text=text,
                    kind=kind,
                    done_if=str(update.get("done_if") or "").strip(),
                    evidence_refs=refs,
                    initial_text=text,
                    initial_done_if=str(update.get("done_if") or "").strip(),
                )
                self.goals[goal_id] = goal
                self._record(
                    turn=turn,
                    op="add",
                    goal_id=goal_id,
                    actor=actor,
                    text=goal.text,
                    kind=goal.kind,
                    evidence_refs=refs,
                    after=goal.to_dict(),
                )
                applied.append({"op": "add", "goal_id": goal_id})
                continue

            if not goal_id or goal_id not in self.goals:
                continue
            goal = self.goals[goal_id]
            if op == "focus":
                self.focus_goal_id = goal_id
                self._record(turn=turn, op="focus", goal_id=goal_id, actor=actor, reason=reason)
                applied.append({"op": "focus", "goal_id": goal_id})
                continue
            if op == "revise":
                # A revision is a change of the goal's meaning/acceptance wording,
                # not a status update.  Require an explicit reason and at least one
                # non-empty changed value.  B0 remains present and keeps its origin.
                if not reason or not ("text" in update or "done_if" in update):
                    continue
                before = self._state_view(goal)
                changed: list[str] = []
                if "text" in update:
                    new_text = str(update.get("text") or "").strip()
                    if not new_text:
                        continue
                    if new_text != goal.text:
                        goal.text = new_text
                        changed.append("text")
                if "done_if" in update:
                    new_done_if = str(update.get("done_if") or "").strip()
                    if new_done_if != goal.done_if:
                        goal.done_if = new_done_if
                        changed.append("done_if")
                if not changed:
                    continue
                goal.version += 1
                after = self._state_view(goal)
                self._record(
                    turn=turn,
                    op="revise",
                    goal_id=goal_id,
                    actor=actor,
                    text=goal.text,
                    reason=reason,
                    evidence_refs=refs,
                    before=before,
                    after=after,
                )
                applied.append(
                    {
                        "op": "revise",
                        "goal_id": goal_id,
                        "changed": changed,
                        "reason": reason,
                        "before": before,
                        "after": after,
                    }
                )
                continue
            if op in {"relax", "withdraw"}:
                if goal_id == self.baseline_id or not reason:
                    continue
                before = self._state_view(goal)
                if op == "withdraw":
                    goal.status = GoalStatus.DROPPED.value
                else:
                    goal.status = GoalStatus.PARTIAL.value
                    if update.get("done_if"):
                        goal.done_if = str(update["done_if"]).strip()
                goal.version += 1
                after = self._state_view(goal)
                self._record(
                    turn=turn,
                    op=op,
                    goal_id=goal_id,
                    actor=actor,
                    reason=reason,
                    evidence_refs=refs,
                    before=before,
                    after=after,
                )
                applied.append({"op": op, "goal_id": goal_id, "reason": reason})
                continue
            if op == "status":
                status = str(update.get("status") or "").strip().lower()
                if status not in {
                    GoalStatus.OPEN.value,
                    GoalStatus.PARTIAL.value,
                    GoalStatus.MET.value,
                }:
                    continue
                before = self._state_view(goal)
                goal.status = status
                goal.version += 1
                goal.evidence_refs.extend(refs)
                after = self._state_view(goal)
                self._record(
                    turn=turn,
                    op="status",
                    goal_id=goal_id,
                    actor=actor,
                    status=status,
                    reason=reason,
                    evidence_refs=refs,
                    before=before,
                    after=after,
                )
                applied.append({"op": "status", "goal_id": goal_id, "status": status})
        return applied

    def _record(self, *, turn: int, op: str, goal_id: str, actor: str, **kwargs: Any) -> None:
        self.events.append(
            GoalEvent(
                seq=len(self.events) + 1,
                turn=turn,
                op=op,
                goal_id=goal_id,
                actor=actor,
                **kwargs,
            )
        )

    def audit(self) -> dict[str, Any]:
        """Return a non-gating integrity/content audit for the goal ledger.

        This is deliberately observational: malformed model fields should be visible
        to architects without turning a user conversation into ``evaluator_invalid``.
        """
        warnings: list[str] = []
        if self.baseline_id not in self.goals:
            warnings.append("missing_baseline")
        if not self.focus_goal_id or self.focus_goal_id not in self.goals:
            warnings.append("invalid_focus_goal")
        expected_seq = list(range(1, len(self.events) + 1))
        if [event.seq for event in self.events] != expected_seq:
            warnings.append("non_contiguous_event_seq")
        revisions = [event for event in self.events if event.op == "revise"]
        for event in revisions:
            if not event.reason:
                warnings.append(f"revision_without_reason:{event.seq}")
            if not event.before or not event.after:
                warnings.append(f"revision_without_transition:{event.seq}")
            if event.goal_id not in self.goals:
                warnings.append(f"revision_unknown_goal:{event.seq}")
        baseline = self.goals.get(self.baseline_id)
        return {
            "status": "warning" if warnings else "ok",
            "warnings": warnings,
            "baseline_id": self.baseline_id,
            "baseline_origin_text": baseline.initial_text if baseline else "",
            "baseline_current_text": baseline.text if baseline else "",
            "baseline_version": baseline.version if baseline else None,
            "baseline_revision_count": len(revisions),
            "event_count": len(self.events),
            "focus_goal_id": self.focus_goal_id,
        }

    def commit_terminal_effect(
        self, action: str, effect: Any = None, *, turn: int
    ) -> dict[str, Any]:
        """Spec-0056/T1: commit an explicit close to the subjective goal ledger.

        This is intentionally a subjective transaction: it records what the persona
        claimed at termination, not whether the code is objectively correct.  The
        independent evaluator remains the only source of technical truth.
        """
        raw = effect if isinstance(effect, dict) else {}
        kind = str(raw.get("kind") or "").strip()
        raw_ids = raw.get("goal_ids")
        goal_ids = (
            [str(item).strip() for item in raw_ids if str(item).strip()]
            if isinstance(raw_ids, list)
            else []
        )
        refs = self._refs(raw.get("evidence_refs"))
        warnings: list[str] = []
        expected_kind = {
            "accept": "close",
            "accept_with_reservations": "close_with_reservations",
        }.get(action)
        if expected_kind and kind != expected_kind:
            warnings.append(f"terminal_effect_mismatch:{action}:{kind or 'missing'}")
        if expected_kind and not goal_ids:
            warnings.append("terminal_close_missing_goal_ids")

        committed: list[str] = []
        if kind in {"close", "close_with_reservations"}:
            for goal_id in goal_ids:
                goal = self.goals.get(goal_id)
                if goal is None:
                    warnings.append(f"terminal_unknown_goal:{goal_id}")
                    continue
                before = self._state_view(goal)
                if refs:
                    for ref in refs:
                        if ref not in goal.evidence_refs:
                            goal.evidence_refs.append(ref)
                if goal.status != GoalStatus.MET.value:
                    goal.status = GoalStatus.MET.value
                    goal.version += 1
                after = self._state_view(goal)
                self._record(
                    turn=turn,
                    op="status",
                    goal_id=goal_id,
                    actor="terminal",
                    status=GoalStatus.MET.value,
                    reason=f"{action} declared {kind}",
                    evidence_refs=refs,
                    before=before,
                    after=after,
                )
                committed.append(goal_id)

        return {
            "status": "warning" if warnings else "ok",
            "warnings": warnings,
            "action": action,
            "effect_kind": kind,
            "effect_goal_ids": list(dict.fromkeys(goal_ids)),
            "committed_goal_ids": committed,
            "evidence_refs": refs,
            "unresolved_after": [goal.goal_id for goal in self.unresolved()],
        }

    def terminal_check(
        self, action: str, effect: Any = None, *, terminal_audit: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Check a terminal claim without overriding the user's chosen action."""
        unresolved = [goal.goal_id for goal in self.unresolved()]
        if action == "accept":
            status = "accepted" if not unresolved else "subjective_accept_unverified"
        elif action == "accept_with_reservations":
            status = (
                "accepted_with_reservations" if not unresolved else "reservations_with_unmet_goals"
            )
        else:
            status = "not_applicable"
        result: dict[str, Any] = {
            "status": status,
            "unresolved_goals": unresolved,
        }
        if isinstance(effect, dict):
            result["effect"] = dict(effect)
        if isinstance(terminal_audit, dict):
            result["terminal_audit"] = dict(terminal_audit)
        return result


def audit_goal_fields(
    ledger: GoalLedger,
    *,
    goal_reading: Any = None,
    target_goal_ids: Any = None,
    expected_progress: Any = "",
    goal_effect: Any = None,
    goal_updates: Any = None,
) -> dict[str, Any]:
    """Audit newly added per-turn goal fields without making them a hard gate.

    The return value is persisted beside the turn so downstream agents can tell a
    missing/unknown model annotation from an actual goal state change.
    """
    known = set(ledger.goals)
    warnings: list[str] = []
    readings = goal_reading if isinstance(goal_reading, list) else []
    reading_ids: list[str] = []
    for item in readings:
        if not isinstance(item, dict):
            warnings.append("goal_reading_not_object")
            continue
        goal_id = str(item.get("goal_id") or "").strip()
        progress = str(item.get("progress") or "").strip().lower()
        if not goal_id:
            warnings.append("goal_reading_missing_goal_id")
        elif goal_id not in known:
            warnings.append(f"goal_reading_unknown_goal:{goal_id}")
        else:
            reading_ids.append(goal_id)
        if progress not in GOAL_PROGRESS:
            warnings.append(f"goal_reading_invalid_progress:{goal_id or '?'}")
        if not str(item.get("why") or "").strip():
            warnings.append(f"goal_reading_missing_why:{goal_id or '?'}")

    targets = target_goal_ids if isinstance(target_goal_ids, list) else []
    target_ids = [str(item).strip() for item in targets if str(item).strip()]
    for goal_id in target_ids:
        if goal_id not in known:
            warnings.append(f"target_unknown_goal:{goal_id}")
    if target_ids and not isinstance(expected_progress, str):
        warnings.append("expected_progress_not_string")

    effect = goal_effect if isinstance(goal_effect, dict) else {}
    effect_kind = str(effect.get("kind") or "").strip()
    effect_ids_raw = effect.get("goal_ids")
    effect_ids = (
        [str(item).strip() for item in effect_ids_raw if str(item).strip()]
        if isinstance(effect_ids_raw, list)
        else []
    )
    if effect and effect_kind not in GOAL_EFFECT_KINDS:
        warnings.append(f"goal_effect_invalid_kind:{effect_kind or '?'}")
    for goal_id in effect_ids:
        if goal_id not in known:
            warnings.append(f"goal_effect_unknown_goal:{goal_id}")
    if target_ids and effect_ids and set(target_ids) != set(effect_ids):
        warnings.append("goal_effect_target_mismatch")
    updates = goal_updates if isinstance(goal_updates, list) else []
    update_ops: list[str] = []
    update_goal_ids: list[str] = []
    for update in updates:
        if not isinstance(update, dict):
            warnings.append("goal_update_not_object")
            continue
        op = str(update.get("op") or "").strip().lower()
        goal_id = str(update.get("goal_id") or "").strip()
        update_ops.append(op)
        if goal_id:
            update_goal_ids.append(goal_id)
        if op not in GOAL_UPDATE_OPS:
            warnings.append(f"goal_update_invalid_op:{op or '?'}")
        if op != "add" and not goal_id:
            warnings.append(f"goal_update_missing_goal_id:{op or '?'}")
        if op != "add" and goal_id and goal_id not in known:
            warnings.append(f"goal_update_unknown_goal:{goal_id}")
        if op == "add" and not str(update.get("text") or "").strip():
            warnings.append("goal_update_add_missing_text")
        if op in {"revise", "relax", "withdraw"} and not str(update.get("reason") or "").strip():
            warnings.append(f"goal_update_missing_reason:{op}")
        if op == "revise" and not ("changed" in update or "text" in update or "done_if" in update):
            warnings.append("goal_update_revise_missing_change")
    return {
        "status": "warning" if warnings else "ok",
        "warnings": warnings,
        "known_goal_ids": sorted(known),
        "reading_goal_ids": list(dict.fromkeys(reading_ids)),
        "target_goal_ids": list(dict.fromkeys(target_ids)),
        "effect_goal_ids": list(dict.fromkeys(effect_ids)),
        "effect_kind": effect_kind,
        "update_ops": update_ops,
        "update_goal_ids": list(dict.fromkeys(update_goal_ids)),
        "ledger": ledger.audit(),
    }


def audit_acceptance_basis(
    action: str,
    basis: Any,
    *,
    persona_d1: str = "",
    persona_d3: str = "",
) -> dict[str, Any]:
    """Spec-0056/T1: audit the acceptance basis without turning it into a gate.

    ``subjective`` is valid for a trusting/low-bar persona.  A capable or strict
    persona should normally point to either its own check or a concrete harness
    result, but may still waive it with an explicit reason.  This records alignment;
    it never changes the chosen user action.
    """
    if action not in {"accept", "accept_with_reservations"}:
        return {"status": "not_applicable", "mode": "not_applicable", "warnings": []}
    value = basis if isinstance(basis, dict) else {}
    mode = str(value.get("mode") or "unreported").strip().lower()
    refs_raw = value.get("evidence_refs")
    refs = (
        [str(item).strip() for item in refs_raw if str(item).strip()]
        if isinstance(refs_raw, list)
        else []
    )
    reason = str(value.get("reason") or "").strip()
    warnings: list[str] = []
    if mode not in ACCEPTANCE_BASIS_MODES:
        warnings.append(f"acceptance_basis_invalid_mode:{mode or '?'}")
        mode = "unreported"
    if mode == "unreported":
        warnings.append("acceptance_basis_missing")
    if mode in {"independent", "delegated"} and not refs:
        warnings.append("acceptance_basis_missing_evidence_refs")
    if mode == "waived" and not reason:
        warnings.append("acceptance_basis_waiver_missing_reason")

    strict = persona_d1 in {"competent", "expert"} or persona_d3 in {"idiomatic", "rigorous"}
    if strict and mode in {"subjective", "waived", "unreported"}:
        alignment = "weak"
        warnings.append("strict_persona_without_independent_or_delegated_basis")
    elif mode == "unreported":
        alignment = "unreported"
    else:
        alignment = "aligned"
    return {
        "status": "warning" if warnings else "ok",
        "mode": mode,
        "evidence_refs": refs,
        "reason": reason,
        "expected": "independent_or_delegated" if strict else "subjective_or_delegated",
        "alignment": alignment,
        "warnings": warnings,
    }
