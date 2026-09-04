"""Goal-aware evidence contracts for demand-side roles.

This module is intentionally deterministic.  A session is projected into a small
evidence envelope before it is handed to a demand-side agent; no model call is
made while building the projection.  The projection keeps user intent separate
from objective execution evidence and has bounded text/event budgets so that a
large trace cannot silently become a large prompt.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from auto_designer.models import Session, SimTrace, SimTurn


class EvidenceLevel(StrEnum):
    RAW_REPORT = "L0"
    COMPACT = "L1"
    TIMELINE = "L2"
    BEAT = "L3"
    DETAIL = "L4"


# These are deliberately modest defaults.  They bound the default role prompt,
# while preserving all revision reasons and enough events to explain a decision.
L1_MAX_EVENTS = 12
L1_MAX_REVISIONS = 8
L1_MAX_TEXT = 500
L1_MAX_FEEDBACK = 1200
L1_MAX_REFS = 24
L1_MAX_CHARS = 12_000
EVIDENCE_CATEGORIES = ("report", "user_goal", "interaction", "objective", "harness_source")

_HOST_PATH = re.compile(r"(?:/mnt/[A-Za-z0-9_.-]+/|/root/src/|/workspace/)[^\s,;\]\[(){}<>\"']*")
_ABS_PATH = re.compile(r"(?<![\w.-])/(?:[A-Za-z0-9_.-]+/){2,}[A-Za-z0-9_.-]+")
_LONG_WS = re.compile(r"\s+")
_ACCESS_LOCK = threading.Lock()


def _clip(value: object, limit: int = L1_MAX_TEXT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _safe_text(value: object, limit: int = L1_MAX_TEXT) -> str:
    """Compact user-facing text and redact host/workspace paths.

    This is not intended to redact arbitrary source code.  It prevents the
    common host-path leak while keeping the user's wording useful for design
    analysis.  Full step/output bodies never enter L1 in the first place.
    """

    text = _LONG_WS.sub(" ", str(value or "").replace("\x00", " ")).strip()
    text = _HOST_PATH.sub("<path>", text)
    text = _ABS_PATH.sub("<path>", text)
    return _clip(text, limit)


def _unavailable(reason: str = "not recorded") -> dict[str, str]:
    return {"status": "unavailable", "reason": reason}


def _source(kind: str, *, session_id: str, locator: str = "") -> dict[str, str]:
    out = {"kind": kind, "session_id": session_id}
    if locator:
        out["locator"] = locator
    return out


def _goal_summary(trace: SimTrace | None, *, session_id: str) -> dict[str, Any]:
    ledger = dict(trace.goal_ledger or {}) if trace is not None else {}
    if not ledger:
        return {
            "status": "unavailable",
            "baseline_id": "B0",
            "initial": _unavailable("legacy session has no goal ledger"),
            "current": _unavailable("legacy session has no goal ledger"),
            "revisions": [],
            "unresolved": [],
            "provenance": _source("goal_ledger", session_id=session_id),
        }

    goals = [g for g in (ledger.get("goals") or []) if isinstance(g, Mapping)]
    by_id = {str(g.get("goal_id") or ""): g for g in goals}
    baseline_id = str(ledger.get("baseline_id") or "B0")
    baseline = by_id.get(baseline_id)
    if baseline is None and not goals:
        return {
            "status": "unavailable",
            "baseline_id": baseline_id,
            "initial": _unavailable("goal ledger is empty"),
            "current": _unavailable("goal ledger is empty"),
            "revisions": [],
            "unresolved": [],
            "provenance": _source("goal_ledger", session_id=session_id),
        }
    initial = {
        "goal_id": baseline_id,
        "text": (
            _safe_text((baseline or {}).get("initial_text") or (baseline or {}).get("text"))
            if (baseline or {}).get("initial_text") or (baseline or {}).get("text")
            else _unavailable("baseline goal text missing")
        ),
        "done_if": (
            _safe_text((baseline or {}).get("initial_done_if") or (baseline or {}).get("done_if"))
            if (baseline or {}).get("initial_done_if") or (baseline or {}).get("done_if")
            else _unavailable("baseline completion condition missing")
        ),
        "status": str((baseline or {}).get("status") or "open"),
    }
    current_id = str(ledger.get("focus_goal_id") or baseline_id)
    current = by_id.get(current_id) or baseline
    current_view = {
        "goal_id": current_id,
        "text": (
            _safe_text((current or {}).get("text"))
            if (current or {}).get("text")
            else _unavailable("current goal text missing")
        ),
        "done_if": (
            _safe_text((current or {}).get("done_if"))
            if (current or {}).get("done_if")
            else _unavailable("current completion condition missing")
        ),
        "status": str((current or {}).get("status") or "open"),
        "version": (current or {}).get("version"),
    }
    revisions: list[dict[str, Any]] = []
    for event in (ledger.get("events") or []):
        if not isinstance(event, Mapping) or event.get("op") != "revise":
            continue
        row: dict[str, Any] = {
            "seq": event.get("seq"),
            "turn": event.get("turn"),
            "goal_id": str(event.get("goal_id") or ""),
            "reason": _safe_text(event.get("reason")),
            "provenance": _source(
                "goal_revision", session_id=session_id, locator=f"event:{event.get('seq', '')}"
            ),
        }
        for key in ("before", "after"):
            value = event.get(key)
            if isinstance(value, Mapping):
                row[key] = {
                    "text": _safe_text(value.get("text")),
                    "status": str(value.get("status") or "open"),
                    "version": value.get("version"),
                }
        revisions.append(row)
        if len(revisions) >= L1_MAX_REVISIONS:
            break
    return {
        "status": "available",
        "baseline_id": baseline_id,
        "initial": initial,
        "current": current_view,
        "revisions": revisions,
        "unresolved": [_safe_text(x, 120) for x in (ledger.get("unresolved") or [])[:L1_MAX_REFS]],
        "revision_count": ledger.get("baseline_revision_count", len(revisions)),
        "provenance": _source("goal_ledger", session_id=session_id),
    }


def _goal_events(trace: SimTrace | None, *, session_id: str) -> list[dict[str, Any]]:
    if trace is None:
        return []
    events: list[dict[str, Any]] = []
    for turn in trace.turns:
        if not isinstance(turn, SimTurn):
            continue
        # Do not copy the complete message or harness response into L1.  The
        # action/intent/effect tuple is sufficient for role-level reasoning.
        if not any(
            (
                turn.target_goal_ids,
                turn.expected_progress,
                turn.goal_effect,
                turn.goal_updates,
                turn.action,
                turn.message,
            )
        ):
            continue
        event: dict[str, Any] = {
            "turn": turn.turn,
            "phase": str(turn.phase or ""),
            "action": str(turn.action or ""),
            "target_goal_ids": [str(x) for x in (turn.target_goal_ids or [])[:8]],
            "expected_progress": _safe_text(turn.expected_progress, 300),
            "goal_effect": {},
            "provenance": _source("interaction", session_id=session_id, locator=f"turn:{turn.turn}"),
        }
        if isinstance(turn.goal_effect, Mapping):
            if turn.goal_effect.get("kind") not in (None, ""):
                event["goal_effect"]["kind"] = _safe_text(turn.goal_effect.get("kind"), 80)
            goal_ids = turn.goal_effect.get("goal_ids")
            if isinstance(goal_ids, list):
                event["goal_effect"]["goal_ids"] = [
                    _safe_text(item, 80) for item in goal_ids[:8]
                ]
        # Free intent is useful but must remain bounded and path-safe.
        parsed = [c.parsed for c in (turn.persona_trace or []) if isinstance(c.parsed, Mapping)]
        intents = [p.get("intent") for p in parsed if p.get("intent")]
        if intents:
            event["intent"] = _safe_text(intents[0], 300)
        if turn.action == "send_message" and turn.message:
            event["message"] = _safe_text(turn.message, 300)
        if turn.action == "interrupt":
            event["interrupt"] = True
        events.append(event)
        if len(events) >= L1_MAX_EVENTS:
            break
    return events


def _feedback_events(session: Session, *, session_id: str) -> list[dict[str, Any]]:
    trace = session.sim_trace
    out: list[dict[str, Any]] = []
    if trace is not None:
        for call in trace.persona_tail or []:
            parsed = call.parsed if isinstance(call.parsed, Mapping) else {}
            role = str(call.role or "")
            if role == "file_issue" or parsed.get("issue"):
                text = _safe_text(parsed.get("issue"), L1_MAX_FEEDBACK)
                if text:
                    out.append({
                        "kind": "issue_report",
                        "text": text,
                        "provenance": _source("report", session_id=session_id, locator="persona_tail:file_issue"),
                    })
            if role == "rate" or ("score" in parsed and "reason" in parsed):
                out.append({
                    "kind": "experience_rating",
                    "score": parsed.get("score", session.feeling.score),
                    "reason": _safe_text(parsed.get("reason") or session.feeling.reason, L1_MAX_FEEDBACK),
                    "provenance": _source("feeling", session_id=session_id, locator="persona_tail:rate"),
                })
    if not out and session.feeling.reason:
        out.append({
            "kind": "experience_rating",
            "score": session.feeling.score,
            "reason": _safe_text(session.feeling.reason, L1_MAX_FEEDBACK),
            "provenance": _source("feeling", session_id=session_id, locator="session:feeling"),
        })
    return out[:4]


def _objective_evidence(session: Session) -> dict[str, Any]:
    value = session.objective_evaluation
    if not isinstance(value, Mapping):
        return _unavailable("objective evaluator has not run")
    # Explicit allow-list: no patch, stdout, test bodies or benchmark oracle.
    out: dict[str, Any] = {"status": _safe_text(value.get("status") or "unavailable", 80)}
    for key in ("passed", "exit_code", "evaluator", "instance_id", "patch_sha256", "finished_at"):
        if key in value and value[key] not in (None, ""):
            out[key] = _safe_text(value[key], 180) if isinstance(value[key], str) else value[key]
    if value.get("error"):
        out["error"] = _safe_text(value.get("error"), 300)
    out["provenance"] = {
        "kind": "objective_evaluator",
        "session_id": str(session.session_id),
        "status": "recorded",
    }
    return out


def _goal_acceptance(trace: SimTrace | None, *, session_id: str) -> dict[str, Any]:
    if trace is None or not isinstance(trace.goal_acceptance, Mapping):
        return _unavailable("persona did not reach a goal decision")
    value = trace.goal_acceptance
    out: dict[str, Any] = {}
    for key in ("status", "unresolved_goals", "goal_ids"):
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, list):
            out[key] = [str(x)[:100] for x in item[:24]]
        else:
            out[key] = _safe_text(item, 300)
    out["provenance"] = {
        "kind": "goal_acceptance",
        "session_id": session_id,
        "status": "recorded",
    }
    return out or _unavailable("persona goal decision was empty")


def _enforce_l1_budget(result: dict[str, Any]) -> dict[str, Any]:
    """Trim optional event detail until the serialized projection fits its cap."""
    def size() -> int:
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    events = result.get("key_events")
    while size() > L1_MAX_CHARS and isinstance(events, list) and len(events) > 1:
        # Keep the opening event and recent tail; middle events are least useful
        # for a compact global index and remain available in L2 timeline.
        events.pop(-2)
        result["truncation"]["events_omitted_for_char_budget"] = (
            result["truncation"].get("events_omitted_for_char_budget", 0) + 1
        )
    feedback = result.get("feedback_events")
    while size() > L1_MAX_CHARS and isinstance(feedback, list) and len(feedback) > 1:
        feedback.pop(0)
        result["truncation"]["feedback_omitted_for_char_budget"] = (
            result["truncation"].get("feedback_omitted_for_char_budget", 0) + 1
        )
    return result


def build_l1_summary(session: Session) -> dict[str, Any]:
    """Build a deterministic, bounded L1 projection from a persisted session."""

    sid = str(session.session_id)
    trace = session.sim_trace
    goal = _goal_summary(trace, session_id=sid)
    events = _goal_events(trace, session_id=sid)
    feedback = _feedback_events(session, session_id=sid)
    refs = [item["provenance"] for item in [*events, *feedback] if isinstance(item, Mapping) and item.get("provenance")]
    result: dict[str, Any] = {
        "level": EvidenceLevel.COMPACT.value,
        "session_id": sid,
        "goal_summary": goal,
        "key_events": events,
        "feedback_events": feedback,
        "user_outcome": {
        "end_reason": _safe_text(
            (session.user_outcome or {}).get("end_reason")
            or (trace.end_reason if trace else "unavailable"),
            120,
        ),
            "terminal_note": _safe_text((session.user_outcome or {}).get("terminal_note"), 500),
        },
        "goal_acceptance": _goal_acceptance(trace, session_id=sid),
        "accept_validity": str(session.accept_validity or "not_applicable"),
        "objective_evidence": _objective_evidence(session),
        "evidence_refs": refs[:L1_MAX_REFS],
        "truncation": {
            "max_events": L1_MAX_EVENTS,
            "max_revisions": L1_MAX_REVISIONS,
            "text_limit": L1_MAX_TEXT,
            "max_chars": L1_MAX_CHARS,
            "raw_prompts_included": False,
            "raw_stdout_included": False,
            "target_source_included": False,
        },
        "provenance": {"kind": "session_projection", "session_id": sid, "deterministic": True},
    }
    return _enforce_l1_budget(result)


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Role handoff envelope with separated evidence lanes."""

    source_report: dict[str, Any]
    session_id: str
    user_evidence: dict[str, Any]
    objective_evidence: dict[str, Any]
    harness_source: dict[str, Any] = field(default_factory=lambda: {"status": "read_only"})
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    accept_validity: str = "not_applicable"
    evidence_categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    level: str = EvidenceLevel.COMPACT.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "source_report": dict(self.source_report),
            "session_id": self.session_id,
            "user_evidence": dict(self.user_evidence),
            "objective_evidence": dict(self.objective_evidence),
            "harness_source": dict(self.harness_source),
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
            "accept_validity": self.accept_validity,
            "evidence_categories": {
                key: dict(value) for key, value in self.evidence_categories.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceEnvelope":
        """Restore a persisted handoff without widening any evidence lane."""
        return cls(
            source_report=dict(data.get("source_report") or {}),
            session_id=str(data.get("session_id") or "unavailable"),
            user_evidence=dict(data.get("user_evidence") or {}),
            objective_evidence=dict(data.get("objective_evidence") or _unavailable()),
            harness_source=dict(data.get("harness_source") or {"status": "read_only"}),
            evidence_refs=[dict(item) for item in (data.get("evidence_refs") or []) if isinstance(item, Mapping)],
            accept_validity=str(data.get("accept_validity") or "not_applicable"),
            evidence_categories={
                str(key): dict(value)
                for key, value in (data.get("evidence_categories") or {}).items()
                if isinstance(value, Mapping)
            },
            level=str(data.get("level") or EvidenceLevel.COMPACT.value),
        )


def build_evidence_envelope(
    session: Session | None,
    *,
    report: Mapping[str, Any] | None = None,
    harness_ref: str | None = None,
) -> EvidenceEnvelope:
    """Create the formal session→role handoff; legacy sessions remain explicit unavailable."""

    if session is None:
        sid = str((report or {}).get("session_id") or "unavailable")
        l1 = {
            "level": EvidenceLevel.COMPACT.value,
            "session_id": sid,
            "goal_summary": {"status": "unavailable"},
            "key_events": [],
            "feedback_events": [],
            "user_outcome": {"end_reason": "unavailable", "accept_validity": "not_applicable"},
            "objective_evidence": _unavailable("session not found"),
            "evidence_refs": [],
            "provenance": {"kind": "missing_session", "deterministic": True},
        }
    else:
        sid = str(session.session_id)
        l1 = build_l1_summary(session)
    source = {"status": "read_only", "repo": "harness", "ref": harness_ref or "unavailable"}
    categories = {
        "report": {"level": "L0", "status": "provided" if report else "unavailable", "provenance": {"kind": "report", "session_id": sid}},
        "user_goal": {"level": "L1", "status": (l1.get("goal_summary") or {}).get("status", "unavailable"), "provenance": {"kind": "goal_ledger", "session_id": sid}},
        "interaction": {"level": "L1", "status": "provided" if l1.get("key_events") else "unavailable", "provenance": {"kind": "interaction", "session_id": sid}},
        "objective": {"level": "L1", "status": (l1.get("objective_evidence") or {}).get("status", "unavailable"), "provenance": {"kind": "objective_evaluator", "session_id": sid}},
        "harness_source": {"level": "L4", "status": "read_only", "provenance": {"kind": "harness_source", "session_id": sid}},
    }
    return EvidenceEnvelope(
        source_report=dict(report or {}),
        session_id=sid,
        user_evidence={
            "goal_summary": l1.get("goal_summary", {"status": "unavailable"}),
            "key_events": list(l1.get("key_events") or []),
            "feedback_events": list(l1.get("feedback_events") or []),
            "user_outcome": dict(l1.get("user_outcome") or {}),
            "goal_acceptance": dict(l1.get("goal_acceptance") or _unavailable()),
            "provenance": {"kind": "user_evidence", "session_id": sid, "level": EvidenceLevel.COMPACT.value},
        },
        objective_evidence=dict(l1.get("objective_evidence") or _unavailable()),
        harness_source=source,
        evidence_refs=list(l1.get("evidence_refs") or []),
        accept_validity=str(l1.get("accept_validity") or "not_applicable"),
        evidence_categories=categories,
    )


def project_for_role(envelope: EvidenceEnvelope | Mapping[str, Any], role: str) -> dict[str, Any]:
    """Apply the visibility matrix to an envelope before prompt construction.

    ``triage`` receives one report and one L1; ``pm`` receives the user lane;
    ``synthesize`` and ``owner`` receive references only.  Unknown roles fail
    closed instead of accidentally receiving the raw envelope.
    """

    raw = envelope.to_dict() if isinstance(envelope, EvidenceEnvelope) else dict(envelope)
    normalized = str(role or "").strip().lower()
    if normalized in {"triage", "triager", "triage_agent"}:
        return {
            "level": raw.get("level", EvidenceLevel.COMPACT.value),
            "source_report": dict(raw.get("source_report") or {}),
            "session_id": raw.get("session_id", "unavailable"),
            "user_evidence": dict(raw.get("user_evidence") or {}),
            "objective_evidence": dict(raw.get("objective_evidence") or _unavailable()),
            "accept_validity": raw.get("accept_validity", "not_applicable"),
            "harness_source": dict(raw.get("harness_source") or {}),
            "evidence_refs": list(raw.get("evidence_refs") or []),
        }
    if normalized in {"pm", "divergent", "divergent_pm"}:
        return {
            "level": raw.get("level", EvidenceLevel.COMPACT.value),
            "session_id": raw.get("session_id", "unavailable"),
            "user_evidence": dict(raw.get("user_evidence") or {}),
            "evidence_refs": list(raw.get("evidence_refs") or []),
        }
    if normalized in {"synthesize", "designer", "owner"}:
        return {
            "level": raw.get("level", EvidenceLevel.COMPACT.value),
            "session_id": raw.get("session_id", "unavailable"),
            "evidence_refs": list(raw.get("evidence_refs") or []),
        }
    return {"level": raw.get("level", EvidenceLevel.COMPACT.value), "session_id": raw.get("session_id", "unavailable"), "evidence_refs": []}


def validate_role_access(*, role: str, level: str, session_id: str | None = None, source_session_id: str | None = None) -> tuple[bool, str]:
    """Small fail-closed gate used by future evidence tools and replay tests."""

    allowed = {item.value for item in EvidenceLevel}
    if level not in allowed:
        return False, f"unknown evidence level: {level}"
    normalized = str(role or "").strip().lower()
    known_roles = {
        "triage", "triager", "triage_agent", "pm", "divergent", "divergent_pm",
        "synthesize", "designer", "owner",
    }
    if normalized not in known_roles:
        return False, f"unknown role: {normalized or 'unavailable'}"
    if normalized in {"synthesize", "designer", "owner"} and level in {EvidenceLevel.TIMELINE.value, EvidenceLevel.BEAT.value, EvidenceLevel.DETAIL.value}:
        return False, f"{normalized} cannot directly read {level}"
    if normalized in {"triage", "triager", "triage_agent"} and session_id and source_session_id and session_id != source_session_id:
        return False, "triage session does not match current report"
    return True, "ok"


def record_evidence_access(
    *, level: str, session_id: str, reason: str, allowed: bool, locator: str = ""
) -> None:
    """Append one bounded access audit event when role-run persistence is enabled."""
    root = os.environ.get("ROLE_RUNS_DIR", "").strip()
    if not root:
        return
    try:
        from auto_designer.usage import current_usage_context

        ctx = current_usage_context()
        row: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": ctx.run_id,
            "round": ctx.round_no,
            "role": ctx.role,
            "level": level,
            "session_id": session_id,
            "reason": _safe_text(reason, 300) or "unspecified",
            "allowed": bool(allowed),
        }
        if locator:
            row["locator"] = _safe_text(locator, 120)
        path = __import__("pathlib").Path(root) / "evidence_access.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _ACCESS_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        # Observability must not change role behavior.
        return


def validate_envelope(envelope: EvidenceEnvelope | Mapping[str, Any]) -> list[str]:
    """Structural checks used by replay/closed-loop tests.

    These checks intentionally do not judge whether a user's claim is true; they
    only catch missing provenance, unbounded L1 projections, and accidental lane
    mixing before a role is invoked.
    """

    raw = envelope.to_dict() if isinstance(envelope, EvidenceEnvelope) else dict(envelope)
    errors: list[str] = []
    if str(raw.get("level") or "") != EvidenceLevel.COMPACT.value:
        errors.append("missing-l1")
    if not str(raw.get("session_id") or ""):
        errors.append("missing-session")
    user = raw.get("user_evidence")
    if not isinstance(user, Mapping):
        errors.append("missing-user-evidence")
    else:
        for key in ("goal_summary", "key_events", "feedback_events"):
            if key not in user:
                errors.append(f"missing-user-field:{key}")
    objective = raw.get("objective_evidence")
    if not isinstance(objective, Mapping):
        errors.append("missing-objective-evidence")
    refs = raw.get("evidence_refs")
    if not isinstance(refs, list):
        errors.append("invalid-evidence-refs")
    elif len(refs) > L1_MAX_REFS:
        errors.append("evidence-refs-over-budget")
    categories = raw.get("evidence_categories")
    if not isinstance(categories, Mapping):
        errors.append("missing-evidence-categories")
    else:
        for category in EVIDENCE_CATEGORIES:
            item = categories.get(category)
            if not isinstance(item, Mapping):
                errors.append(f"missing-evidence-category:{category}")
            elif not isinstance(item.get("provenance"), Mapping):
                errors.append(f"missing-provenance:{category}")
    # Reject only actual raw-prompt/large-output field names, not ordinary user
    # vocabulary.  The projection is allowed to carry user text in bounded form.
    forbidden = {"system_prompt", "persona_prompt", "raw_prompt", "stdout", "patch", "source_code", "oracle"}
    def walk(value: object, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in forbidden:
                    errors.append(f"forbidden-field:{path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, f"{path}{i}.")
    walk(raw)
    return list(dict.fromkeys(errors))


# Compatibility aliases make the projection easy to discover for callers and
# keep the public vocabulary aligned with the spec.
build_goal_aware_summary = build_l1_summary
build_user_feedback_envelope = build_evidence_envelope
build_feedback_envelope = build_evidence_envelope
