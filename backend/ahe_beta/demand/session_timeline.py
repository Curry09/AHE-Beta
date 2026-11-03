"""Structured synthesis as-needed projection: extract 'usage event timeline' from persisted Session.

Spec-0024/T4: Usage event projection + get_harness_beat / get_harness_step
Spec-0024/T5: Tool wiring see agent_defs/architect/ (this module implements projection functions only)

Design tradeoffs (why not raw sim_trace)
--------------------------------
Persisted authority remains Session.sim_trace (contains raw LLM system/user, for post-hoc KV/debugging).
Structured synthesis needs complete decision/usage timeline, not simulation engine playback.

Signals rarely present in real product logs but extremely valuable for finding structural root causes (should be retained and reformatted as events):
- Free intent before convergence (users don't write text then click buttons)
- intent↔action gap capability_gap (truly unreachable capabilities; do not confuse with 'user being indecisive')
- Process judgment on_track/off_track/unclear (explicit labels almost never exist in reality)
- Private verification private_check (local self-test/self-read not sent to chat)
- Observed activity summary saw_activity (aligned with decision at that moment)
- Silent interruption silent_stop (Ctrl+C style not entering transcript)
- Session-end feeling / issue statement

Should remove simulation machinery identity markers (confound attribution, unlike real user logs):
- persona_id, action_space permanent table columns, executor/channel original names, patience/trust counters,
  verdict fine enums, waiting_judge and other role names, decisions.steps half-raw LLM, fake:// URLs,
  LLM system/user/raw.

capability_gap exception: only when intent and final action mismatch, attach the current available action list—
 otherwise structured synthesis will wonder 'why not do it', yet cannot see 'the menu doesn't have that action at all'. Include only on mismatch,
 avoid unpacking the menu every round causing drift/overfitting."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ahe_beta.models import PersonaCallTrace, Session, SimTrace, SimTurn
from ahe_beta.user.session_store import SessionStore

_STORE: ContextVar[SessionStore | None] = ContextVar("architect_session_store", default=None)
# nexau tool callbacks often run on different threads; ContextVar is not auto-copied; sync-write this fallback during bind.
_STORE_FALLBACK: SessionStore | None = None

# Activity bars, private verification, and harness replies are length-limited to prevent concrete command output entering default proposal context.
_ACTIVITY_MAX = 8
_ACTIVITY_TEXT = 160
_HEARD_MAX = 1200
_PRIVATE_STEP_MAX = 6
_GOAL_TEXT_MAX = 500

# perceive labeled by loop with machine header: [judgment|intent→action] …
_PERCEIVE_HEAD = re.compile(r"^\[.*?\]\s*")


@contextmanager
def bind_session_store(store: SessionStore) -> Iterator[None]:
    """Inject SessionStore during Architect._run_agent for tool access."""
    global _STORE_FALLBACK
    token = _STORE.set(store)
    _STORE_FALLBACK = store
    try:
        yield
    finally:
        _STORE.reset(token)
        _STORE_FALLBACK = None


def _require_store() -> SessionStore:
    store = _STORE.get() or _STORE_FALLBACK
    if store is None:
        raise RuntimeError("session store not bound; call within Architect.run")
    return store


def _clean_notes(perceive: str) -> str:
    """Remove simulation-assembled [judgment|intent→action] header, keep only human-readable observations."""
    return _PERCEIVE_HEAD.sub("", (perceive or "").strip()).strip()


def _phase_when(phase: str) -> str:
    """phase → human-friendly phase labels (avoid opening/waiting/active looking like state machine)."""
    p = (phase or "").strip().lower()
    if p == "waiting":
        return "during_wait"
    if p == "opening":
        return "opening"
    if p in {"active", ""}:
        return "after_reply"
    return p or "after_reply"


def _parsed_from(turn: SimTurn) -> list[dict[str, Any]]:
    return [dict(c.parsed or {}) for c in turn.persona_trace if isinstance(c.parsed, dict)]


def _first_str(parsed_list: list[dict[str, Any]], key: str) -> str:
    for p in parsed_list:
        val = p.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _activity_summary(turn: SimTurn) -> list[str]:
    """User 'observed activity' summary: real products rarely have activity aligned with decisions, but invaluable for debugging delays.

    Keep only short titles; do not include full harness_steps / stdout.
    """
    out: list[str] = []
    for step in list(turn.harness_steps or [])[-_ACTIVITY_MAX:]:
        if not isinstance(step, dict):
            continue
        kind = str(step.get("kind") or "").strip()
        text = str(step.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        # tool_result is often lengthy, activity bar emphasizes tool call title
        if kind == "tool_result":
            continue
        line = text if not kind else f"{kind}: {text}"
        out.append(line[:_ACTIVITY_TEXT])
    return out


def _private_checks(turn: SimTurn) -> list[dict[str, str]]:
    """Private verification: steps the user ran/read locally, not sent to harness.

    Real chat logs rarely show 'user ran pytest locally'; simulation can capture it, critical for acceptance gates and over-confidence root causes.
    Private verification is inner agentic behavior within judge/intent/act, no longer maps to outer verify_self action.
    """
    out: list[dict[str, str]] = []
    for call in turn.persona_trace:
        for step in call.steps or []:
            if not isinstance(step, dict):
                continue
            kind = str(step.get("kind") or "")
            if kind not in {"tool", "tool_result", "tool_error"}:
                continue
            text = str(step.get("text") or "").strip().replace("\n", " ")[:_ACTIVITY_TEXT]
            if not text:
                continue
            out.append({"kind": kind, "detail": text})
            if len(out) >= _PRIVATE_STEP_MAX:
                return out
    return out


def _capability_gap(
    turn: SimTurn, *, wanted: str, did: str, parsed_list: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Capability gap event when intent does not align with final action.

    Real scenarios never show "clicked A but actually wanted B outside the menu".
    Without annotation, structural synthesis would assume user contradiction; the root cause
    is typically missing items in action_space. Thus: only attach current available when misaligned,
    not expand menu every turn.
    """
    gap = False
    for p in parsed_list:
        if p.get("gap") is True:
            gap = True
            break
    if not gap:
        return None
    return {
        # Simulation-specific, but extremely valuable for distinguishing "missing capability vs. user repetition"
        "wanted": wanted or "(unspecified intent)",
        "did": did,
        "available": [str(x) for x in (turn.action_space or [])],
        "note": (
            "User intent did not match the chosen action; the available actions at that "
            "moment likely lacked a closer fit (capability boundary), not random inconsistency."
        ),
    }


def _compact_goal_snapshot(snapshot: Any) -> dict[str, Any]:
    """Keep goal context useful for design while excluding the full event log."""
    if not isinstance(snapshot, dict):
        return {}
    goals: list[dict[str, Any]] = []
    for raw in snapshot.get("goals", []):
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {
            "goal_id": str(raw.get("goal_id") or ""),
            "text": str(raw.get("text") or "")[:_GOAL_TEXT_MAX],
            "kind": str(raw.get("kind") or ""),
            "status": str(raw.get("status") or ""),
            "version": raw.get("version"),
        }
        if raw.get("initial_text") and raw.get("initial_text") != raw.get("text"):
            item["initial_text"] = str(raw.get("initial_text") or "")[:_GOAL_TEXT_MAX]
        if raw.get("done_if"):
            item["done_if"] = str(raw.get("done_if") or "")[:_GOAL_TEXT_MAX]
        goals.append(item)
    return {
        "baseline_id": snapshot.get("baseline_id"),
        "focus_goal_id": snapshot.get("focus_goal_id"),
        "unresolved": list(snapshot.get("unresolved") or []),
        "baseline_revision_count": snapshot.get("baseline_revision_count", 0),
        "goals": goals,
    }


def _goal_event_view(event: Any) -> dict[str, Any]:
    """Clip goal transition text but retain before/after versions for audit."""
    if not isinstance(event, dict):
        return {}
    out: dict[str, Any] = {
        key: event.get(key)
        for key in ("seq", "turn", "op", "goal_id", "actor", "reason", "evidence_refs")
        if event.get(key) not in (None, "", [])
    }
    for key in ("before", "after"):
        value = event.get(key)
        if isinstance(value, dict):
            compact = _compact_goal_snapshot({"goals": [value]})
            if compact.get("goals"):
                out[key] = compact["goals"][0]
    for key in ("text", "status", "kind"):
        if event.get(key) not in (None, ""):
            value = event[key]
            out[key] = str(value)[:_GOAL_TEXT_MAX] if key == "text" else value
    return out


def _goal_turn_view(turn: SimTurn) -> dict[str, Any] | None:
    """Expose goal semantics beside each decision for downstream design audit."""
    if not any(
        (
            turn.goal_before,
            turn.goal_reading,
            turn.target_goal_ids,
            turn.expected_progress,
            turn.goal_updates,
            turn.goal_after,
            turn.goal_effect,
            turn.goal_field_audit,
            turn.acceptance_basis,
        )
    ):
        return None
    return {
        "before": _compact_goal_snapshot(turn.goal_before),
        "reading": [dict(item) for item in (turn.goal_reading or []) if isinstance(item, dict)],
        "targets": list(turn.target_goal_ids or []),
        "expected_progress": (turn.expected_progress or "").strip(),
        "updates": [dict(item) for item in (turn.goal_updates or []) if isinstance(item, dict)],
        "after": _compact_goal_snapshot(turn.goal_after),
        "effect": dict(turn.goal_effect or {}) if isinstance(turn.goal_effect, dict) else {},
        "field_audit": dict(turn.goal_field_audit or {})
        if isinstance(turn.goal_field_audit, dict)
        else {},
        "acceptance_basis": dict(turn.acceptance_basis or {})
        if isinstance(turn.acceptance_basis, dict)
        else {},
    }


def _project_turn(turn: SimTurn) -> dict[str, Any]:
    """One turn → one usage event (remove simulation wrapper, preserve valuable god's-eye annotations)."""
    parsed_list = _parsed_from(turn)
    wanted = _first_str(parsed_list, "intent")
    judgment = _first_str(parsed_list, "judgment")
    did = (turn.action or "").strip()
    said = (turn.message or "").strip()
    notes = _clean_notes(turn.perceive)
    heard = (turn.harness_output or "").strip()
    if len(heard) > _HEARD_MAX:
        heard = heard[:_HEARD_MAX] + "…"

    event: dict[str, Any] = {
        # SimTurn lacks wall-clock field; use sequence number for ordering. Upgrade to [+Ns] after elapsed time available.
        "t": turn.turn,
        "when": _phase_when(turn.phase),
    }

    activity = _activity_summary(turn)
    if activity:
        event["saw_activity"] = activity

    if notes:
        event["thought"] = notes
    # Process judgment: no explicit label in reality; useful for attributing "thought still on track / already diverged"
    if judgment:
        event["process_read"] = judgment
    # Open intent: free text before convergence, closer to actual needs than final button
    if wanted:
        event["wanted"] = wanted

    if did:
        event["did"] = did
    if said:
        event["said"] = said
    # Spec-0024/T6: outgoing directive handle + queued state (distinguish at a glance "interruption not yet consumed by current reply")
    utt = (turn.utterance_id or "").strip()
    if utt:
        event["utterance"] = utt
    delivery = (turn.delivery or "").strip()
    if delivery:
        event["delivery"] = delivery
    behind = (turn.queued_behind or "").strip()
    if behind:
        event["queued_behind"] = behind
    if heard:
        event["heard"] = heard
        # Spec-0024/T6: which user directive should this harness reply respond to
        ans = (turn.answers_utterance_id or "").strip()
        if ans:
            event["answers"] = ans
            preview = (turn.answers_said or "").strip()
            if preview:
                event["answers_said"] = preview

    # Silent interruption: not in conversation transcript; viewing only chat would miss "user pressed stop"
    if did == "interrupt":
        event["silent_stop"] = True

    private = _private_checks(turn)
    if private:
        event["private_check"] = private

    gap = _capability_gap(turn, wanted=wanted, did=did, parsed_list=parsed_list)
    if gap is not None:
        event["capability_gap"] = gap

    goal = _goal_turn_view(turn)
    if goal is not None:
        event["goal"] = goal

    return event


def _closing_from_tail(calls: list[PersonaCallTrace]) -> list[dict[str, Any]]:
    """Session end file_issue / rate: structured exit signals (real scenarios rarely have unified schema)."""
    events: list[dict[str, Any]] = []
    for call in calls:
        parsed = call.parsed if isinstance(call.parsed, dict) else {}
        role = (call.role or "").strip()
        if role == "file_issue" or "issue" in parsed:
            issue = str(parsed.get("issue") or "").strip()
            if issue:
                events.append({"when": "closing", "did": "file_issue", "issue_text": issue})
        if role == "rate" or ("score" in parsed and "reason" in parsed):
            try:
                score = int(parsed.get("score"))
            except (TypeError, ValueError):
                continue
            events.append(
                {
                    "when": "closing",
                    "did": "rate_experience",
                    "feeling": {
                        "score": score,
                        "reason": str(parsed.get("reason") or "").strip(),
                    },
                }
            )
    return events


def _project_sim_trace(trace: SimTrace) -> dict[str, Any]:
    events = [_project_turn(t) for t in trace.turns]
    events.extend(_closing_from_tail(list(trace.persona_tail)))
    out: dict[str, Any] = {
        "end_reason": trace.end_reason,
        "events": events,
    }
    if trace.goal_ledger:
        ledger = dict(trace.goal_ledger)
        out["goal_ledger"] = {
            "baseline_id": ledger.get("baseline_id"),
            "focus_goal_id": ledger.get("focus_goal_id"),
            "goals": _compact_goal_snapshot(ledger).get("goals", []),
            "unresolved": list(ledger.get("unresolved") or []),
            "baseline_revision_count": ledger.get("baseline_revision_count", 0),
            "events": [
                _goal_event_view(event)
                for event in (ledger.get("events") or [])
                if isinstance(event, dict)
            ],
        }
    if trace.goal_audit:
        out["goal_audit"] = dict(trace.goal_audit)
    if trace.goal_acceptance is not None:
        out["goal_acceptance"] = dict(trace.goal_acceptance)
    if trace.terminal_audit:
        out["terminal_audit"] = dict(trace.terminal_audit)
    # If signals like WAIT_GAP already fall in turns' capability_gap, do not repeat raw machine signal stream here
    return out


def format_session_timeline(session: Session) -> str:
    """Session → usage event timeline JSON for structural synthesis.

    Spec-0024/T4: projection without simulation wrapper (not raw pass-through for storage).
    """
    issues = [
        {
            "number": r.number,
            "state": r.state,
            # Intentionally omit url: fake:// / internal tracker URLs expose implementation and add no value to attribution
        }
        for r in session.issue_refs
    ]
    payload: dict[str, Any] = {
        "session_id": session.session_id,
        "started_at": session.created_at.isoformat(),
        "feeling": session.feeling.to_dict() if session.feeling is not None else None,
        "feedback": dict(session.feedback),
        "execution_contract": dict(session.execution_contract),
        "issues": issues,
        "timeline": (
            _project_sim_trace(session.sim_trace)
            if session.sim_trace is not None
            else _direct_timeline(session)
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def find_session_by_id(store: SessionStore, session_id: str) -> Session | None:
    sid = session_id.strip()
    if not sid:
        return None
    try:
        return store.load(sid)
    except FileNotFoundError:
        return None


def find_session_by_issue(store: SessionStore, issue_number: int) -> Session | None:
    """Reverse lookup by issue number; restore index from authoritative session file if index is missing."""
    sid = store.find_session_id_by_issue(int(issue_number))
    return find_session_by_id(store, sid) if sid else None


def _resolve_session(
    *, issue_number: int | None, session_id: str | None
) -> Session | dict[str, Any]:
    """Get Session by issue/session_id; return dict with ok=False on failure."""
    try:
        store = _require_store()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    sid = (session_id or "").strip() or None
    if sid is not None:
        session = find_session_by_id(store, sid)
        if session is None:
            return {"ok": False, "error": f"session not found: {sid}"}
        return session
    if issue_number is not None:
        session = find_session_by_issue(store, int(issue_number))
        if session is None:
            return {
                "ok": False,
                "error": f"no session linked to issue #{int(issue_number)}",
            }
        return session
    return {"ok": False, "error": "provide issue_number or session_id"}


def _check_role_access(*, level: str, session_id: str, reason: str) -> dict[str, Any] | None:
    """Enforce the role matrix at the tool boundary (prompts are not a permission system)."""
    from ahe_beta.demand.evidence_contract import (
        record_evidence_access,
        validate_role_access,
    )
    from ahe_beta.demand.observation_provider import current_observation_scope
    from ahe_beta.usage import current_usage_context

    ctx = current_usage_context()
    role = str(ctx.role or "").strip().lower()
    if not role:  # Compatibility for local projection helpers outside role execution.
        return None
    allowed, error = validate_role_access(
        role=role,
        level=level,
        session_id=session_id,
        source_session_id=ctx.session_id,
        allowed_session_ids=current_observation_scope(),
    )
    if allowed:
        return None
    record_evidence_access(
        level=level, session_id=session_id, reason=reason or error, allowed=False
    )
    return {"ok": False, "error": error}


def get_session_timeline(
    issue_number: int | None = None,
    session_id: str | None = None,
    reason: str = "",
    agent_state: Any = None,  # noqa: ARG001 — nexau injected, unused
) -> dict[str, Any]:
    """Structural synthesis tool: get one session's usage event timeline by issue or session_id (projection, not raw dump)."""
    del agent_state
    resolved = _resolve_session(issue_number=issue_number, session_id=session_id)
    if isinstance(resolved, dict):
        return resolved
    denied = _check_role_access(level="L2", session_id=resolved.session_id, reason=reason)
    if denied is not None:
        return denied
    from ahe_beta.demand.evidence_contract import record_evidence_access

    record_evidence_access(
        level="L2",
        session_id=resolved.session_id,
        reason=reason,
        allowed=True,
    )
    text = format_session_timeline(resolved)
    result: dict[str, Any] = {
        "ok": True,
        "session_id": resolved.session_id,
        "timeline": text,
        "evidence_access": {
            "level": "L2",
            "reason": str(reason or "unspecified"),
            "session_id": resolved.session_id,
        },
    }
    return result


# ── get_harness_beat: drill into what a specific harness beat did when needed ─────────────────────
# Why a separate tool (rather than embed in timeline):
# - Default timeline gives heard + short saw_activity, enough to judge "timeout/intent"; full steps would blow context.
# - When attributing "budget spent on exploration vs. stuck before delivery", need to **inspect one specific beat** and see tool sequence — drill in on demand.
# - Do not expose full LLM raw records; truncate tool_result to avoid single command output entering proposals.

_BEAT_TOOL_TEXT = 220
_BEAT_RESULT_TEXT = 280
_BEAT_HEARD_MAX = 1500
_BEAT_MAX_STEPS = 80  # ≈ max_iterations×2; preserve head and tail if longer


def _classify_stop(*, heard: str) -> str:
    """Classify stop reason from harness terminal reply (for structural synthesis to cross-reference entry.py / agent.yaml primary buttons)."""
    h = (heard or "").strip()
    low = h.lower()
    if "maximum iteration" in low or "iteration limit" in low:
        return "max_iterations"
    if low.startswith("[timeout]"):
        return "wall_timeout"
    if low.startswith("[interrupted]") or "interrupt" in low[:40]:
        return "interrupt"
    if low.startswith("[harness error]"):
        return "harness_error"
    if not h:
        return "empty"
    return "completed"


def _clip_step_text(*, kind: str, text: str) -> tuple[str, bool]:
    """Truncate step text by kind; return (text, truncated)."""
    raw = (text or "").strip().replace("\n", " ")
    limit = (
        _BEAT_RESULT_TEXT if kind in {"tool_result", "tool_error", "assistant"} else _BEAT_TOOL_TEXT
    )
    if len(raw) <= limit:
        return raw, False
    return raw[:limit] + "…", True


def _format_beat_steps(*, steps: list[Any]) -> list[dict[str, Any]]:
    """harness_steps → auditable short list; preserve head and tail for oversized sequences."""
    clean: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        kind = str(step.get("kind") or "").strip() or "unknown"
        text, truncated = _clip_step_text(kind=kind, text=str(step.get("text") or ""))
        if not text:
            continue
        item: dict[str, Any] = {"i": i, "kind": kind, "text": text}
        if truncated:
            item["truncated"] = True
        clean.append(item)

    if len(clean) <= _BEAT_MAX_STEPS:
        return clean
    head_n = 20
    tail_n = _BEAT_MAX_STEPS - head_n - 1
    omitted = len(clean) - head_n - tail_n
    return [
        *clean[:head_n],
        {
            "i": -1,
            "kind": "omitted",
            "text": f"… {omitted} steps omitted (too many for one beat peek) …",
        },
        *clean[-tail_n:],
    ]


def _candidate_beats(*, trace: SimTrace, turn: int) -> list[SimTurn]:
    """Same turn number may have multiple beats (waiting + active); prefer ones with harness output/steps."""
    matches = [t for t in trace.turns if int(t.turn) == int(turn)]
    with_harness = [t for t in matches if (t.harness_steps or (t.harness_output or "").strip())]
    return with_harness or matches


@dataclass(frozen=True)
class _DirectBeat:
    """A recorded request/reply exchange, without a simulated user decision."""

    message: str
    harness_output: str
    harness_steps: list[dict]
    turn: int = 1
    phase: str = "direct"
    action: str = "send_message"


def _session_beats(session: Session, turn: int) -> list[SimTurn | _DirectBeat]:
    if session.sim_trace is not None:
        return _candidate_beats(trace=session.sim_trace, turn=turn)
    record = session.user_outcome.get("execution_record") or {}
    if not isinstance(record, dict) or turn != 1 or record.get("contract_version") != 1:
        return []
    requests = [t for t in session.transcript.turns if t.role == "user"]
    replies = [t for t in session.transcript.turns if t.role == "harness"]
    if not requests or not replies:
        return []
    return [_DirectBeat(requests[0].content, replies[0].content, list(replies[0].steps))]


def _direct_timeline(session: Session) -> dict | None:
    beats = _session_beats(session, 1)
    if not beats:
        return None
    beat = beats[0]
    record = session.user_outcome["execution_record"]
    return {
        "interaction_mode": "direct",
        "end_reason": session.user_outcome.get("status", "unavailable"),
        "source": "recorded_direct_exchange",
        "events": [
            {
                "t": 1,
                "when": "direct",
                "user_did": "send_message",
                "user_said": beat.message[:_HEARD_MAX],
                "heard": beat.harness_output[:_HEARD_MAX],
                "n_harness_steps": len(beat.harness_steps),
            }
        ],
        "requests": list(session.request_outcomes),
        "stdout_observations": [
            {
                "type": event.get("type"),
                "text": str(event.get("text") or "")[:_ACTIVITY_TEXT],
                "observed_at": event.get("observed_at"),
                "source": event.get("source"),
            }
            for event in list(record.get("events") or [])[:_ACTIVITY_MAX]
            if isinstance(event, dict)
        ],
        "observations_total": record.get("events_total"),
        "steps_source": record.get("steps_source"),
        "reviewer_visibility": record.get("reviewer_visibility"),
        "note": "Recorded launcher observations do not establish model internals or task correctness.",
    }


def _beat_stop(session: Session, beat: SimTurn | _DirectBeat) -> str:
    if isinstance(beat, _DirectBeat) and session.request_outcomes:
        terminal = session.request_outcomes[-1]
        if terminal.get("termination_source") == "infrastructure":
            return (
                "infrastructure_timeout"
                if terminal.get("status") == "timed_out"
                else "harness_error"
            )
    return _classify_stop(heard=beat.harness_output or "")


def format_harness_beat(
    *, session: Session, turn: int, occurrence: int, reason: str = ""
) -> dict[str, Any]:
    """Session × turn → harness activity details for one specific beat (for tool return)."""
    if session.sim_trace is None and not session.user_outcome.get("execution_record"):
        return {"ok": False, "error": "session has no sim_trace"}
    denied = _check_role_access(level="L3", session_id=session.session_id, reason=reason)
    if denied is not None:
        return denied
    candidates = _session_beats(session, turn)
    if not candidates:
        return {
            "ok": False,
            "error": f"no sim turn with turn={turn}",
            "session_id": session.session_id,
        }
    if occurrence < 0 or occurrence >= len(candidates):
        return {
            "ok": False,
            "error": (
                f"occurrence={occurrence} out of range; "
                f"{len(candidates)} beat(s) for turn={turn} (0..{len(candidates) - 1})"
            ),
            "session_id": session.session_id,
            "n_candidates": len(candidates),
        }
    beat = candidates[occurrence]
    heard = (beat.harness_output or "").strip()
    if len(heard) > _BEAT_HEARD_MAX:
        heard = heard[:_BEAT_HEARD_MAX] + "…"
    steps = _format_beat_steps(steps=list(beat.harness_steps or []))
    result: dict[str, Any] = {
        "ok": True,
        "session_id": session.session_id,
        "turn": beat.turn,
        "occurrence": occurrence,
        "n_candidates": len(candidates),
        # Align with timeline's when for structural synthesis cross-reference
        "when": _phase_when(beat.phase),
        "phase": beat.phase,
        "user_did": (beat.action or "").strip(),
        "user_said": (beat.message or "").strip(),
        "stop_kind": _beat_stop(session, beat),
        "heard": heard,
        "n_steps_raw": len(beat.harness_steps or []),
        "n_steps_returned": len(steps),
        "steps": steps,
        "note": (
            "Harness inner tool trail for one user-sim beat. tool_result bodies are clipped; "
            "not a full LLM dump. If a step has truncated=true and you still need the body, "
            "call get_harness_step(turn=…, step_i=<that i>) for a larger (still capped) expand. "
            "Map stop_kind to runtime controls (agent.yaml max_iterations / launcher "
            "infrastructure cap), not to the SWE task."
        ),
    }
    if isinstance(beat, _DirectBeat):
        result["interaction_mode"] = "direct"
        record = session.user_outcome.get("execution_record", {})
        result["record_provenance"] = {
            key: record.get(key)
            for key in (
                "source",
                "storage_policy",
                "steps_source",
                "steps_total",
                "steps_omitted",
                "reviewer_visibility",
            )
        }
        result["request_outcomes"] = list(session.request_outcomes)
    goal = _goal_turn_view(beat) if isinstance(beat, SimTurn) else None
    if goal is not None:
        # Keep the same goal context at the second level so architects do not have
        # to join a beat back to its parent timeline to understand its purpose.
        result["goal"] = goal
    return result


def get_harness_beat(
    turn: int,
    issue_number: int | None = None,
    session_id: str | None = None,
    occurrence: int = 0,
    reason: str = "",
    agent_state: Any = None,  # noqa: ARG001 — nexau injected, unused
) -> dict[str, Any]:
    """Structural synthesis tool: drill down into a specific beat (timeline's t) to see which tools the harness inner layer performed.

    Spec-0024/T4+T5: stop_kind + truncated steps; first traverse timeline, then drill down into this beat.
    """
    del agent_state
    resolved = _resolve_session(issue_number=issue_number, session_id=session_id)
    if isinstance(resolved, dict):
        return resolved
    try:
        turn_n = int(turn)
        occ = int(occurrence)
    except (TypeError, ValueError):
        return {"ok": False, "error": "turn and occurrence must be integers"}
    result = format_harness_beat(session=resolved, turn=turn_n, occurrence=occ, reason=reason)
    if result.get("ok"):
        from ahe_beta.demand.evidence_contract import record_evidence_access

        record_evidence_access(
            level="L3",
            session_id=resolved.session_id,
            reason=reason,
            allowed=True,
            locator=f"turn:{turn_n}",
        )
        result["evidence_access"] = {
            "level": "L3",
            "reason": str(reason or "unspecified"),
            "session_id": resolved.session_id,
            "turn": turn_n,
        }
    return result


# ── get_harness_step: expand a step's body on demand (still has hard limit, never infinite) ────────────────
# Beat list is intentionally truncated; if structural synthesis determines "this step's stdout/error must be viewed", then expand the single step.
# Hard limit prevents a single pytest/log from exploding the context; overly long content still shows truncated + n_chars_raw.

_STEP_EXPAND_MAX = 6_000


def _pick_beat_or_error(
    *, session: Session, turn: int, occurrence: int
) -> SimTurn | _DirectBeat | dict[str, Any]:
    """Shared: parse turn/occurrence → SimTurn, or ok=False dict."""
    if session.sim_trace is None and not session.user_outcome.get("execution_record"):
        return {"ok": False, "error": "session has no sim_trace"}
    candidates = _session_beats(session, turn)
    if not candidates:
        return {
            "ok": False,
            "error": f"no sim turn with turn={turn}",
            "session_id": session.session_id,
        }
    if occurrence < 0 or occurrence >= len(candidates):
        return {
            "ok": False,
            "error": (
                f"occurrence={occurrence} out of range; "
                f"{len(candidates)} beat(s) for turn={turn} (0..{len(candidates) - 1})"
            ),
            "session_id": session.session_id,
            "n_candidates": len(candidates),
        }
    return candidates[occurrence]


def format_harness_step(
    *, session: Session, turn: int, occurrence: int, step_i: int
) -> dict[str, Any]:
    """Expand the body of step_i within a beat (hard-limited truncation)."""
    picked = _pick_beat_or_error(session=session, turn=turn, occurrence=occurrence)
    if isinstance(picked, dict):
        return picked
    steps = list(picked.harness_steps or [])
    if step_i < 0 or step_i >= len(steps):
        return {
            "ok": False,
            "error": f"step_i={step_i} out of range; beat has {len(steps)} steps (0..{len(steps) - 1})",
            "session_id": session.session_id,
            "turn": picked.turn,
            "n_steps_raw": len(steps),
        }
    raw_step = steps[step_i]
    if not isinstance(raw_step, dict):
        return {"ok": False, "error": f"step_i={step_i} is not a dict step"}
    kind = str(raw_step.get("kind") or "").strip() or "unknown"
    # Expansion preserves newlines for easier reading of tracebacks / diffs; still applies character hard limit
    raw = str(raw_step.get("text") or "")
    n_chars = len(raw)
    truncated = n_chars > _STEP_EXPAND_MAX
    text = raw if not truncated else raw[:_STEP_EXPAND_MAX] + "\n…[truncated]"
    result: dict[str, Any] = {
        "ok": True,
        "session_id": session.session_id,
        "turn": picked.turn,
        "occurrence": occurrence,
        "when": _phase_when(picked.phase),
        "stop_kind": _beat_stop(session, picked),
        "step_i": step_i,
        "kind": kind,
        "n_chars_raw": n_chars,
        "n_chars_returned": len(text),
        "truncated": truncated,
        "text": text,
        "note": (
            f"Expanded single harness step body (hard cap {_STEP_EXPAND_MAX} chars). "
            "Still not unlimited raw logs—if truncated again, treat as signal that the "
            "artifact is too large to paste into a design proposal; cite kind/path only."
        ),
    }
    goal = _goal_turn_view(picked) if isinstance(picked, SimTurn) else None
    if goal is not None:
        # A single harness step is still interpreted in the user's current goal
        # context; retain only the compact projection, not another raw trace dump.
        result["goal"] = goal
    return result


def get_harness_step(
    turn: int,
    step_i: int,
    issue_number: int | None = None,
    session_id: str | None = None,
    occurrence: int = 0,
    reason: str = "",
    agent_state: Any = None,  # noqa: ARG001 — nexau injected, unused
) -> dict[str, Any]:
    """Structural synthesis tool: expand the longer body of a step in get_harness_beat (still has hard limit).

    Spec-0024/T4+T5: hard character limit, never unlimited raw.
    """
    del agent_state
    resolved = _resolve_session(issue_number=issue_number, session_id=session_id)
    if isinstance(resolved, dict):
        return resolved
    denied = _check_role_access(level="L4", session_id=resolved.session_id, reason=reason)
    if denied is not None:
        return denied
    try:
        turn_n = int(turn)
        occ = int(occurrence)
        idx = int(step_i)
    except (TypeError, ValueError):
        return {"ok": False, "error": "turn, step_i, and occurrence must be integers"}
    result = format_harness_step(session=resolved, turn=turn_n, occurrence=occ, step_i=idx)
    if result.get("ok"):
        from ahe_beta.demand.evidence_contract import record_evidence_access

        record_evidence_access(
            level="L4",
            session_id=resolved.session_id,
            reason=reason,
            allowed=True,
            locator=f"turn:{turn_n}:step:{idx}",
        )
        result["evidence_access"] = {
            "level": "L4",
            "reason": str(reason or "unspecified"),
            "session_id": resolved.session_id,
            "turn": turn_n,
            "step_i": idx,
        }
    return result
