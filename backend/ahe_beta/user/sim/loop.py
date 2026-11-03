"""
loop.py
Simulated-user control loop: coordinate the three cognitive stages and shared state.

Each turn pipeline:
  ① Receive harness output    harness_output (text)                  (harness_adapter / scenarios)
  ② Derive action space   phase ∩ cap ∩ authz (∪ terminate/accept)  (action_space, pure code)
  ③ Three subjective stages   persona LLM -> {perceive, verdict, action, message}  (persona_client)
  ④ resolve               free-form output classification + privilege projection + channel validation  (action_space.resolve)
  ⑤ state write-back      consume only subjective verdict                        (state.apply_verdict)
  ⑥ termination check     Effect.TERMINATE -> record end_reason and break
  ⑦ routing               EMIT -> drive harness for next turn; terminate action -> wrap up

This round is purely subjective (no objective ground truth track):
- harness returns only text, no gold / exit_code; bugs surface in the text, identified by persona's capability.
- state and experience signals throughout depend only on subjective verdict / trust, not any objective ground truth.
- user's own file reads / command runs / diff inspection occur in the private tool loop of AgenticPersonaClient,
  forming evidence for perceive/verdict in the judge phase; not an outer action.
- perception is not filtered at framework level: harness text feeds raw into persona LLM, constrained by prompt(G1) + persona tier to "perceive only within capability".
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from ahe_beta.usage import set_usage_context

from .action_space import ActionResolutionError, derive_action_space, resolve_action
from .actions import CATALOG, Channel, Effect, Executor, Phase
from .dimensions import Persona
from .feeling import FeelingScore, derive_feeling, experience_feedback, parse_feeling_llm
from .goals import GoalLedger, audit_acceptance_basis, audit_goal_fields
from .persona_client import (
    PersonaClient,
    PersonaProtocolError,
    drain_call_traces,
    drain_protocol_events,
)
from .prompt import (
    WAITING_JUDGMENTS,
    build_issue_turn,
    build_main_act_turn,
    build_main_final_check_turn,
    build_main_intent_turn,
    build_main_judge_turn,
    build_main_reintent_turn,
    build_main_rejudge_turn,
    build_rating_turn,
    build_system,
    build_waiting_act_turn,
    build_waiting_intent_turn,
    build_waiting_judge_turn,
)
from .state import (
    VERDICTS,
    Coef,
    State,
    apply_task_load,
    apply_verdict,
    init_state,
    make_coef,
)


@dataclass
class TurnLog:
    turn: int
    phase: str
    action_space: list
    perceive: str
    verdict: str
    action: str
    message: str
    executor: str
    channel: str
    patience: int
    trust: str
    harness_output: str = ""
    # Paired with harness_output: the harness's inner process stream for the reply the persona saw in that round (a sequence of {kind,text}).
    # Only used when the observation layer is expanded; the persona only perceives harness_output (the final answer) and does not consume the steps.
    harness_steps: list = field(default_factory=list)
    # Visible events on the harness stdout since the last user decision (reply/progress/status/ack/error);
    # Preserved in observation order, with no request/reply pairing inference.
    harness_events: list = field(default_factory=list)
    # Raw LLM calls (system/user/raw/steps) triggered by the user agent for this decision; keep everything for now, filter later.
    persona_trace: list = field(default_factory=list)
    # Spec-0024/T6: request–reply pairing (for observability; does not change the harness wire protocol).
    # utterance_id: handle of the user instruction sent out this tick; delivery=open|queued; when queued, queued_behind=the current open one.
    # answers_*: the utterance (and body-text preview) that this tick's harness_output answers.
    utterance_id: str = ""
    delivery: str = ""
    queued_behind: str = ""
    answers_utterance_id: str = ""
    answers_said: str = ""
    # Explicit user-goal control: compact before/after snapshots plus the model's
    # declared change/effect.  The complete append-only event history lives on
    # SessionResult.goal_ledger.
    goal_before: dict = field(default_factory=dict)
    # Perception-level goal appraisal.  This is deliberately separate from goal_updates:
    # reading a goal's progress guides the next decision but does not mutate the ledger.
    goal_reading: list[dict] = field(default_factory=list)
    # Intent-level binding: which goals this decision is trying to move, and how.
    target_goal_ids: list[str] = field(default_factory=list)
    expected_progress: str = ""
    goal_updates: list[dict] = field(default_factory=list)
    goal_after: dict = field(default_factory=dict)
    goal_effect: dict = field(default_factory=dict)
    # Soft content/integrity audit for goal_reading, targets, expected progress and effect.
    # Warnings are observational and never turn a valid user decision into a protocol error.
    goal_field_audit: dict = field(default_factory=dict)
    # Terminal-only explanation of the persona's acceptance basis.
    acceptance_basis: dict = field(default_factory=dict)


@dataclass
class _UtteranceLedger:
    """In-session user → harness instruction ledger: assign a number to each outbound directive, with reply linked back to the open instruction it closes.

    Spec-0024/T6: persona may still "learn the truth only upon seeing content"; explicit request/reply pairing is required when persisting / integrating structures.
    """

    _seq: int = 0
    open_id: str | None = None
    said: dict[str, str] = field(default_factory=dict)
    pending_answers_id: str | None = None

    def alloc(self, text: str) -> str:
        self._seq += 1
        uid = f"u{self._seq}"
        self.said[uid] = text
        return uid

    def mark_open(self, uid: str) -> None:
        self.open_id = uid

    def clear_open(self) -> None:
        """Abandon current open (e.g., give_up), do not produce answers."""
        self.open_id = None

    def close_open_as_answered(self) -> str | None:
        """Current open receives reply/interrupt receipt: record in pending, available for next TurnLog write to answers."""
        answered = self.open_id
        self.pending_answers_id = answered
        self.open_id = None
        return answered

    def consume_pending_answers(self) -> tuple[str, str]:
        uid = self.pending_answers_id or ""
        self.pending_answers_id = None
        preview = (self.said.get(uid) or "") if uid else ""
        if len(preview) > 120:
            preview = preview[:120] + "…"
        return uid, preview


@dataclass
class SessionResult:
    persona_id: str
    end_reason: str
    turns: list[TurnLog] = field(default_factory=list)
    # Behavioral feedback signal for developers (purely subjective derivation)
    signals: list[str] = field(default_factory=list)
    issue_artifact: str | None = None
    # Body text recorded via the mid-session report_issue tool (does not terminate the session); at wrap-up it is handed to the tracker together with issue_artifact.
    issue_notes: list[str] = field(default_factory=list)
    # Training signal: persona LLM's end-of-session self-rating (1–4)
    feeling: FeelingScore | None = None
    # Independent diagnostic; does not fill in missing self-rating values
    feeling_derived: FeelingScore | None = None
    experience: dict = field(default_factory=dict)
    terminal_issue_mode: str | None = None
    # Harness replies received but not yet entered into the TurnLog (a harness reply has to wait for the next round's TurnLog before being logged along with the
    # harness_output; here it is surfaced early to the observability layer for real-time display; cleared when the next TurnLog entry is appended)
    pending_harness_output: str | None = None
    # Inner process stream paired with pending_harness_output
    pending_harness_steps: list | None = None
    # stdout-visible events within the same window as pending_harness_output
    pending_harness_events: list | None = None
    # End-of-episode user agent calls not attached to any particular Turn (file_issue body text / subjective experience rating).
    persona_tail: list = field(default_factory=list)
    # Spec-0048: evaluator protocol anomalies and harness task failures are tracked on separate rails; invalid results must not count toward the normal pass rate.
    evaluation_status: str = "valid"
    evaluation_error: dict | None = None
    # Lightweight protocol split: keeps the legacy-compatible semantics of evaluation_status while letting consumers know whether it is merely a
    # persona output-contract failure, rather than misreading it as a user give_up or an objective code failure.
    interaction_status: str = "completed"
    # Every failed contract attempt is retained separately from persona_tail so an
    # auditor can distinguish malformed output, recovery, and the eventual outcome.
    protocol_events: list[dict] = field(default_factory=list)
    # Explicit goal ledger snapshot and terminal claim.  Objective evaluation remains separate.
    goal_ledger: dict = field(default_factory=dict)
    goal_acceptance: dict | None = None
    # Final non-gating integrity audit; per-turn audits live on TurnLog.
    goal_audit: dict = field(default_factory=dict)
    terminal_audit: dict = field(default_factory=dict)


MAX_TURNS = 24

# Blocking send path: wall-clock time beyond this value additionally drains a bit of patience (to prevent waiting indefinitely). The heartbeat path uses history [+Ns] + conditional patience drain.
_EXTREME_WAIT_SEC = 480.0

# The framework's own harness-failure sentinel prefix: when harness.send() crashes or times out, route backfills this string (see below) and feeds it verbatim to
# the user agent's perception. It no longer triggers any framework-side action gating—whether to accept the work, file a ticket, or walk away in the face of a crash is left to the model's own judgment
# (governed primarily by prompt G6 + the termination-timing clause); the framework only surfaces the failure faithfully—neither blowing up the whole episode nor drawing conclusions on the model's behalf.
HARNESS_ERROR_PREFIX = "[harness error] "
_HARNESS_TERMINAL_STATUSES = frozenset({"timed_out", "crashed"})

# Event waiting (user-side initiative while waiting):
#   AwaitEvent = poll until a harness reply (which wakes the main loop) or until the heartbeat threshold is reached (a one-shot waiting decision).
#   A heartbeat is a one-shot action (including keep_waiting)—once done, it ends and returns to AwaitEvent; it does not
#   keep polling within the heartbeat in order to 'claim the previous send'.
#   The persona side may still only know what happened after seeing the reply's content; the observability side uses _UtteranceLedger for explicit pairing
#   （Spec-0024/T6：heard.answers → utterance）。
_HEARTBEAT_SEC = 90.0
# Hard cap on heartbeat wakeups (a backstop against the pathological case where the model keeps keep_waiting and the harness never replies). Hitting the cap forces a give-up.
_MAX_HEARTBEATS = 12
# A malformed persona reply is not a user give-up. Allow one warning heartbeat
# to keep listening; repeated failures then stop safely with an auditable status.
_MAX_PROTOCOL_STALL_HEARTBEATS = 2
# Waiting menu: inside = send_message; outside = interrupt (Ctrl+C) + give_up; keep_waiting = decide to keep waiting.
WAITING_ACTIONS = ["keep_waiting", "send_message", "interrupt", "give_up"]


def _supports_heartbeat(harness) -> bool:
    """Real subprocess handle: unified write + poll + external interrupt/shutdown; Fake/Scripted requires no heartbeat."""
    has_write = hasattr(harness, "write_message") or hasattr(harness, "begin")
    return has_write and all(hasattr(harness, m) for m in ("poll", "interrupt", "shutdown"))


def _harness_terminal_status(harness) -> str:
    """Read terminal state from launcher output; never infer from human-facing reply text."""
    status = str(getattr(harness, "last_request_status", "") or "")
    return status if status in _HARNESS_TERMINAL_STATUSES else ""


def _write_harness_message(harness, message: str) -> None:
    """Unified stdin write (Spec-0036): prefer write_message, compatible with legacy begin/emit_message aliases."""
    for name in ("write_message", "begin", "emit_message"):
        fn = getattr(harness, name, None)
        if callable(fn):
            fn(message)
            return
    raise AttributeError("harness has no write_message/begin/emit_message")


def _take_persona_calls(client: PersonaClient, role: str) -> list[dict]:
    """Drain raw call just completed on client, tag with role (for TurnLog / persona_tail)."""
    out: list[dict] = []
    for call in drain_call_traces(client):
        tagged = dict(call)
        tagged["role"] = role
        out.append(tagged)
    return out


def _take_protocol_events(client: PersonaClient, result: SessionResult) -> None:
    """Drain protocol evidence into the session; never raise on an audit side channel."""
    for event in drain_protocol_events(client):
        if isinstance(event, dict):
            result.protocol_events.append(dict(event))


_PRIVATE_EVIDENCE_MAX_ITEMS = 8
_PRIVATE_EVIDENCE_MAX_ITEM_CHARS = 650
_PRIVATE_EVIDENCE_MAX_CMD_CHARS = 160


def _phase_stage_label(*, phase: str, role: str) -> str:
    stage = role.rsplit("_", 1)[-1] if "_" in role else role
    if phase == "waiting":
        where = "during_wait"
    elif phase == "opening":
        where = "opening"
    else:
        where = "after_reply"
    return f"{where}/{stage}"


def _one_line(text: object, *, limit: int) -> str:
    out = " ".join(str(text or "").split())
    if len(out) > limit:
        return out[: max(0, limit - 3)] + "..."
    return out


def _tool_action_summary(text: str) -> str:
    raw_full = _one_line(text, limit=4000)
    m = re.match(r"^(\w+)\s+(\{.*\})$", raw_full)
    if not m:
        return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)
    name, arg_s = m.groups()
    try:
        args = json.loads(arg_s)
    except json.JSONDecodeError:
        return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)
    if name in {"read_file", "write_file"} and args.get("path"):
        return f"{name} `{_one_line(args['path'], limit=90)}`"
    if name == "run_shell" and args.get("cmd"):
        return f"run_shell `{_one_line(args['cmd'], limit=120)}`"
    if name == "report_issue" and args.get("body"):
        return "report_issue `<body>`"
    return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)


def _tool_result_summary(text: str) -> str:
    try:
        obj = json.loads(str(text or ""))
    except json.JSONDecodeError:
        return _one_line(text, limit=220)
    bits: list[str] = []
    if "returncode" in obj:
        bits.append(f"returncode={obj.get('returncode')}")
    for key in ("stdout", "stderr", "error", "content"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            bits.append(f"{key}: {_one_line(val, limit=180)}")
            break
    return "; ".join(bits)[:240]


def _record_private_evidence(*, state: State, calls: list[dict], phase: str) -> None:
    """Compress this round's private tool-use into user's own cross-turn short memory."""
    for call in calls:
        steps = [
            s
            for s in (call.get("steps") or [])
            if isinstance(s, dict) and s.get("kind") in {"tool", "tool_result", "tool_error"}
        ]
        if not steps:
            continue
        tools = [
            _tool_action_summary(str(s.get("text") or "")) for s in steps if s.get("kind") == "tool"
        ]
        results = [
            _tool_result_summary(str(s.get("text") or ""))
            for s in steps
            if s.get("kind") in {"tool_result", "tool_error"}
        ]
        parsed = call.get("parsed") if isinstance(call.get("parsed"), dict) else {}
        perceive = _one_line(parsed.get("perceive", ""), limit=360)
        state.private_evidence_seq += 1
        label = _phase_stage_label(phase=phase, role=str(call.get("role") or "unknown"))
        lines = [f"[E{state.private_evidence_seq} {label}]"]
        if tools:
            lines.append("Private tools: " + "; ".join(tools[:4]) + ".")
        if perceive:
            lines.append("Conclusion: " + perceive)
        elif results:
            lines.append("Observed: " + results[0])
        item = "\n".join(lines)
        if len(item) > _PRIVATE_EVIDENCE_MAX_ITEM_CHARS:
            item = item[: _PRIVATE_EVIDENCE_MAX_ITEM_CHARS - 3] + "..."
        if state.private_evidence is None:
            state.private_evidence = []
        state.private_evidence.append(item)
        if len(state.private_evidence) > _PRIVATE_EVIDENCE_MAX_ITEMS:
            del state.private_evidence[:-_PRIVATE_EVIDENCE_MAX_ITEMS]


def _resolve_gap(ret: dict) -> bool:
    """act self-reports gap; illegal/default → False."""
    gap_raw = ret.get("gap")
    return gap_raw is True or (
        isinstance(gap_raw, str) and gap_raw.strip().lower() in ("true", "1", "yes")
    )


def _resolve_waiting(ret: dict) -> tuple[str, str, bool]:
    """Route heartbeat-awakened free output to WAITING_ACTIONS + message + gap.

    Illegal/default always safely fall back to keep_waiting (never unilaterally abandon or interrupt for user).
    send_message missing body → return to keep_waiting (do not fabricate, do not send empty string).
    gap: self-reported by act step—intent is open; after convergence, if only fallback is possible and user intent is not truly fulfilled, then True.
    """
    action = str(ret.get("action", "")).strip()
    if action not in WAITING_ACTIONS:
        action = "keep_waiting"
    message = str(ret.get("message", "")).strip()
    if action == "send_message" and not message:
        action = "keep_waiting"
    if action != "send_message":
        message = ""
    return action, message, _resolve_gap(ret)


def _resolve_judgment(ret: dict) -> str:
    """Heartbeat judgment round: route to WAITING_JUDGMENTS; illegal/default → unclear (safe bias toward continued waiting, action round decides next)."""
    raw = str(ret.get("judgment", "")).strip().lower().replace("-", "_")
    if raw in WAITING_JUDGMENTS:
        return raw
    return "unclear"


def _resolve_intent(ret: dict) -> str:
    """Open intent: free text; empty/default → keep waiting. Optional intent_detail may be merged into one sentence."""
    raw = str(ret.get("intent", "")).strip()
    detail = str(ret.get("intent_detail", "")).strip()
    if not raw:
        return "keep waiting"
    if detail and detail.lower() not in raw.lower():
        return f"{raw} ({detail})"
    return raw


def _goal_reading(raw: object) -> list[dict]:
    """Keep the model's per-turn goal appraisal as an auditable soft signal.

    Missing or malformed readings are intentionally tolerated.  The goal layer guides
    cognition; it is not a protocol gate that can invalidate a session.
    """
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    return [dict(item) for item in values if isinstance(item, dict)]


def _goal_ids(raw: object) -> list[str]:
    """Normalize soft intent target ids without rejecting unknown future goal ids."""
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, str) else [])
    out: list[str] = []
    for item in values:
        value = str(item).strip()
        if value and value not in out:
            out.append(value)
    return out


def _current_goal_text(task: str, goal_ledger: GoalLedger | None) -> str:
    """Use the current B0 wording for cognition; keep the seed task in the ledger audit."""
    if goal_ledger is not None:
        baseline = goal_ledger.goals.get(goal_ledger.baseline_id)
        if baseline is not None and baseline.text.strip():
            return baseline.text.strip()
    return task


def _main_decide(
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    harness_output: str,
    harness_events: list,
    space: list,
    state: State,
    help_text: str,
    appraise_task: bool,
    result: SessionResult,
    phase: str,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[dict, list[dict], str, bool]:
    """Main loop decision: judge → intent → [once final-check → rejudge → reintent] → act.

    Return (act_ret contains action/message, persona_calls, intent, gap).
    judge's perceive/verdict/task_load already merged into act_ret, available for downstream apply_verdict / session startup task_load.
    """
    calls: list[dict] = []
    goal_updates: list = []
    current_goal_frame = goal_frame
    decision_task = _current_goal_text(task, goal_ledger)

    def apply_goal_updates(raw: object) -> None:
        """Apply updates between cognitive stages so this turn sees its own changes."""
        nonlocal current_goal_frame, decision_task
        if goal_ledger is None or raw is None:
            return
        values = goal_ledger.apply_updates(raw, turn=state.turn + 1)
        goal_updates.extend(values)
        current_goal_frame = goal_ledger.prompt_snapshot()
        decision_task = _current_goal_text(task, goal_ledger)

    jret = client.respond(
        system,
        build_main_judge_turn(
            decision_task,
            history,
            harness_output,
            [],  # judge does not see the current action menu; the real action_space is exposed only during the act convergence stage
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            appraise_task=appraise_task,
        ),
    )
    new_calls = _take_persona_calls(client, "main_judge")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    perceive = str(jret.get("perceive", ""))
    verdict = str(jret.get("verdict", "unsure"))
    task_load = jret.get("task_load")
    goal_reading = _goal_reading(jret.get("goal_reading"))
    apply_goal_updates(jret.get("goal_update"))
    target_goal_ids: list[str] = []
    expected_progress = ""
    iret = client.respond(
        system,
        build_main_intent_turn(
            decision_task,
            history,
            harness_output,
            [],  # intent remains an open wish and does not look at the current action menu
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            verdict=verdict,
            perceive=perceive,
            goal_reading=goal_reading,
            final_check_available=phase == Phase.ACTIVE.value,
        ),
    )
    new_calls = _take_persona_calls(client, "main_intent")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    intent = _resolve_intent(iret)
    target_goal_ids = _goal_ids(iret.get("target_goal_ids"))
    expected_progress = str(iret.get("expected_progress") or "").strip()
    apply_goal_updates(iret.get("goal_update"))

    # Spec-0048: only one final private check is allowed per decision cycle while ACTIVE; regardless of whether the check succeeds, is unavailable, or
    # fails at the protocol level, everything afterwards must go through tool-less rejudge/reintent, and it may not jump back again within the same cycle.
    if phase == Phase.ACTIVE.value and iret.get("needs_final_check") is True:
        check_goal = str(iret.get("check_goal") or "").strip()
        check_status = "failed"
        check_evidence = "The final check could not be completed. Judge from existing evidence."
        try:
            cret = client.respond(
                system,
                build_main_final_check_turn(
                    decision_task,
                    history,
                    harness_output,
                    state,
                    help_text=help_text,
                    harness_events=harness_events,
                    goal_frame=current_goal_frame,
                    verdict=verdict,
                    perceive=perceive,
                    intent=intent,
                    check_goal=check_goal,
                ),
            )
            new_calls = _take_persona_calls(client, "main_final_check")
            calls.extend(new_calls)
            _record_private_evidence(state=state, calls=new_calls, phase=phase)
            check_status = str(cret.get("check_status") or "failed")
            check_evidence = str(cret.get("perceive") or "").strip() or check_evidence
        except PersonaProtocolError as exc:
            # final-check itself is an optional evidence channel: on failure, the failure is handed over as evidence to the forced re-judgment; it is not
            # mistaken for a harness failure, and re-entering the tool phase is not allowed.
            new_calls = _take_persona_calls(client, "main_final_check")
            calls.extend(new_calls)
            _record_private_evidence(state=state, calls=new_calls, phase=phase)
            check_status = "failed"
            check_evidence = f"Final check unavailable ({exc.code}); use existing evidence."

        rjret = client.respond(
            system,
            build_main_rejudge_turn(
                decision_task,
                history,
                harness_output,
                state,
                help_text=help_text,
                harness_events=harness_events,
                goal_frame=current_goal_frame,
                prior_verdict=verdict,
                prior_perceive=perceive,
                check_status=check_status,
                check_evidence=check_evidence,
            ),
        )
        new_calls = _take_persona_calls(client, "main_rejudge")
        calls.extend(new_calls)
        _record_private_evidence(state=state, calls=new_calls, phase=phase)
        perceive = str(rjret.get("perceive") or "")
        verdict = str(rjret.get("verdict") or "unsure")
        goal_reading = _goal_reading(rjret.get("goal_reading"))
        apply_goal_updates(rjret.get("goal_update"))

        riret = client.respond(
            system,
            build_main_reintent_turn(
                decision_task,
                history,
                harness_output,
                state,
                help_text=help_text,
                harness_events=harness_events,
                goal_frame=current_goal_frame,
                verdict=verdict,
                perceive=perceive,
                goal_reading=goal_reading,
            ),
        )
        new_calls = _take_persona_calls(client, "main_reintent")
        calls.extend(new_calls)
        _record_private_evidence(state=state, calls=new_calls, phase=phase)
        intent = _resolve_intent(riret)
        target_goal_ids = _goal_ids(riret.get("target_goal_ids"))
        expected_progress = str(riret.get("expected_progress") or "").strip()
        apply_goal_updates(riret.get("goal_update"))

    aret = client.respond(
        system,
        build_main_act_turn(
            decision_task,
            history,
            harness_output,
            space,
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            verdict=verdict,
            perceive=perceive,
            intent=intent,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
        ),
    )
    new_calls = _take_persona_calls(client, "main_act")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    _drain_issue_notes(client, result)
    _record_act_report(aret, result, history, stage="main_act", turn=state.turn)
    gap = _resolve_gap(aret)
    act_target_ids = _goal_ids(aret.get("target_goal_ids"))
    if act_target_ids:
        target_goal_ids = act_target_ids
    act_expected_progress = str(aret.get("expected_progress") or "").strip()
    if act_expected_progress:
        expected_progress = act_expected_progress
    apply_goal_updates(aret.get("goal_update"))
    goal_effect = aret.get("goal_effect") if isinstance(aret.get("goal_effect"), dict) else {}
    goal_field_audit = (
        audit_goal_fields(
            goal_ledger,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
            goal_effect=goal_effect,
            goal_updates=goal_updates,
        )
        if goal_ledger is not None
        else {}
    )
    merged = {
        "perceive": perceive,
        "verdict": verdict,
        "intent": intent,
        "action": aret.get("action"),
        "message": aret.get("message", ""),
        "gap": gap,
        "goal_reading": goal_reading,
        "target_goal_ids": target_goal_ids,
        "expected_progress": expected_progress,
        "goal_field_audit": goal_field_audit,
    }
    if goal_updates:
        # These are already applied summaries, not raw updates.  Keeping them under a
        # separate key prevents run_session from applying them a second time.
        merged["goal_updates_applied"] = goal_updates
    if "goal_effect" in aret:
        merged["goal_effect"] = aret.get("goal_effect")
    if isinstance(aret.get("acceptance_basis"), dict):
        merged["acceptance_basis"] = dict(aret["acceptance_basis"])
    if task_load is not None:
        merged["task_load"] = task_load
    return merged, calls, intent, gap


def route(action_id: str, message: str, state: State, harness, observable: str) -> str | None:
    """Dispatch by executor×channel, return next round's harness text (None if absent)."""
    spec = CATALOG[action_id]

    if action_id == "keep_waiting":
        # Main loop 'wait again': poll for the next reply (soft wakeup, without binding a write flag; Spec-0036).
        if not hasattr(harness, "poll"):
            return None
        try:
            kind, val = harness.poll(_HEARTBEAT_SEC)
        except Exception as exc:  # noqa: BLE001
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"
        if kind == "reply":
            return str(val)
        return None

    if action_id == "interrupt":
        try:
            ctrl_out = harness.interrupt()
        except Exception as exc:  # noqa: BLE001
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"
        return str(ctrl_out or "[interrupt] no running harness work to stop")

    if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE:
        if not message.strip():
            # The model chose an action requiring it to speak but did not supply that message (still empty after the client re-asks—very rare): do not fabricate, do not send anything out.
            # This round is a no-op (the harness does not advance); MAX_TURNS is the backstop; never send framework-invented text to the harness.
            return None
        try:
            # Send line B -> drive the harness to produce the next round of text
            return harness.send(message)
        except Exception as exc:  # noqa: BLE001
            # The harness is a black box: crashes/timeouts/protocol violations must not blow up the whole game; they should be fed back to the user agent as observable failure signals
            # (Reads as: [harness error] → judged stuck/failed_blame_harness → patience drops → eventually terminate and leave an issue).
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"

    return None  # Terminal action: stop driving the harness


def _append_issue_note(result: SessionResult, body: str) -> bool:
    text = body.strip()
    if not text or text in result.issue_notes:
        return False
    result.issue_notes.append(text)
    result.signals.append(f"ISSUE_TOOL: report_issue ({len(result.issue_notes)})")
    return True


def _record_act_report(
    ret: dict, result: SessionResult, history: list[str], *, stage: str, turn: int
) -> None:
    """Spec-0057/T1: reporting is independent of action and persona tool ability.

    The act's raw/parsed trace retains the choice. Malformed optional feedback must
    never retry or replace an otherwise valid main action (including acceptance).
    """
    report = ret.get("report_issue")
    if report is None:
        return
    body = report.get("body") if isinstance(report, dict) else None
    if not isinstance(body, str) or not body.strip():
        result.protocol_events.append(
            {"stage": stage, "turn": turn, "code": "invalid_report_issue", "status": "warning"}
        )
        result.signals.append(f"PERSONA_PROTOCOL_WARNING: stage={stage} code=invalid_report_issue")
        return
    if _append_issue_note(result, body):
        history.append(
            f"[turn {turn}] feedback recorded for tool developers (queued for session close): "
            f"{body.strip()}"
        )


def _drain_issue_notes(client: PersonaClient, result: SessionResult) -> None:
    """Merge agentic mid-session report_issue notes into SessionResult (idempotent if idle; no-op if absent)."""
    drain = getattr(client, "drain_issue_notes", None)
    if not callable(drain):
        return
    for note in drain():
        text = str(note).strip()
        if not text:
            continue
        _append_issue_note(result, text)


def emit_issue_artifact(persona: Persona, log: list[TurnLog], issue_text: str) -> str:
    """Derive issue from this session's subjective data (do not hard-code scenarios, do not read objective ground truth).

    Body = issue_text: persona composes via specialized build_issue_turn in first person a *self-contained* issue
    (submitted to absent developers), not wrapped in third-person title or template shell; only append one line of italic
    auto-collected metadata (capability tier / error correction style / reproduction round / recent harness last line) for
    developer triage, clearly delimited from user's original words. When issue_text is empty, fall back to file_issue's
    message for that round.
    """
    fails = [t for t in log if t.verdict == "failed_blame_harness"]
    last_out = next((t.harness_output for t in reversed(log) if t.harness_output.strip()), "")
    symptom = last_out.strip().splitlines()[-1][:160] if last_out.strip() else "—"
    body = (
        issue_text.strip() or (log[-1].message.strip() if log else "") or "(filed without detail)"
    )
    meta = (
        f"_auto-collected · {persona.persona_id} · {persona.d1.value}/{persona.d43.value} · "
        f"{len(log)} turns, {len(fails)} blamed the assistant · last reply: {symptom}_"
    )
    return f"{body}\n\n---\n{meta}\n"


def _log_waiting(
    result: SessionResult,
    state: State,
    action: str,
    message: str,
    *,
    judgment: str,
    intent: str,
    perceive: str,
    gap: bool,
    on_progress: Callable[[SessionResult], None] | None,
    persona_trace: list,
    ledger: _UtteranceLedger,
    goal_before: dict | None = None,
    goal_reading: list[dict] | None = None,
    target_goal_ids: list[str] | None = None,
    expected_progress: str = "",
    goal_updates: list[dict] | None = None,
    goal_after: dict | None = None,
    goal_effect: dict | None = None,
    goal_field_audit: dict | None = None,
) -> None:
    """Record one heartbeat-awakened waiting decision as phase='waiting' TurnLog (for observation; does not occupy harness_output).

    perceive resembles [judgment|intent→action] notes; act self-reports gap, then append WAIT_GAP signal.
    send_message body written to TurnLog.message (internal channel); other actions are empty.
    Spec-0024/T6: send_message allocates utterance, delivery=queued (queued after current open).
    """
    note = perceive.strip()
    head = f"[{judgment}|{intent}→{action}]"
    perceive_logged = f"{head} {note}" if note else head
    # Channel annotations: send_message is inner (EMIT); interrupt/give_up/keep_waiting are outer/local (SILENT).
    if action == "send_message":
        executor, channel = Executor.HARNESS.value, Channel.EMIT.value
    else:
        executor, channel = Executor.PERSONA_LOCAL.value, Channel.SILENT.value
    utterance_id = ""
    delivery = ""
    queued_behind = ""
    if action == "send_message" and message.strip():
        utterance_id = ledger.alloc(message)
        delivery = "queued"
        queued_behind = ledger.open_id or ""
    result.turns.append(
        TurnLog(
            turn=state.turn,
            phase="waiting",
            action_space=list(WAITING_ACTIONS),
            perceive=perceive_logged,
            verdict="stuck",
            action=action,
            message=message if action == "send_message" else "",
            executor=executor,
            channel=channel,
            patience=state.patience,
            trust=state.trust.value,
            harness_output="",
            harness_steps=[],
            persona_trace=list(persona_trace),
            utterance_id=utterance_id,
            delivery=delivery,
            queued_behind=queued_behind,
            goal_before=dict(goal_before or {}),
            goal_reading=[dict(item) for item in (goal_reading or [])],
            target_goal_ids=list(target_goal_ids or []),
            expected_progress=expected_progress,
            goal_updates=[dict(item) for item in (goal_updates or [])],
            goal_after=dict(goal_after or {}),
            goal_effect=dict(goal_effect or {}),
            goal_field_audit=dict(goal_field_audit or {}),
        )
    )
    if gap:
        result.signals.append(f"WAIT_GAP: intent={intent} action={action}")
    if on_progress is not None:
        on_progress(result)


class _SessionClock:
    """Session relative timeline: all history entries as `[+Ns] …`, avoid mixing multiple delta-time notations.

    Wall clock and harness-reported waited_sec take max, enabling unit tests with fake poll's waited to advance timeline.
    """

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._logical = 0.0

    def wall(self) -> float:
        return max(0.0, time.monotonic() - self._t0)

    def now(self) -> float:
        self._logical = max(self._logical, self.wall())
        return self._logical

    def observe(self, sec: float) -> float:
        self._logical = max(self._logical, float(sec), self.wall())
        return self._logical

    def stamp(self, history: list[str], body: str) -> None:
        history.append(f"[+{self.now():.0f}s] {body}")


def _note_waiting_memory(
    history: list[str],
    clock: _SessionClock,
    *,
    judgment: str,
    intent: str,
    action: str,
    message: str,
    perceive: str,
    gap: bool,
) -> None:
    """Heartbeat thought + action written to history (timestamps unified by clock, prefixed with [+Ns])."""
    intent_one = intent.strip().replace("\n", " ")[:120] or "(no intent)"
    note = perceive.strip().replace("\n", " ")[:160]
    gap_bit = " (felt a gap — action did not fully match intent)" if gap else ""
    if action == "send_message":
        msg_one = message.strip().splitlines()[0][:120] if message.strip() else "(empty)"
        act_bit = f"chose send_message: {msg_one}"
    else:
        act_bit = f"chose {action}"
    body = f"waiting: judged {judgment}; wanted {intent_one!r}; {act_bit}{gap_bit}."
    if note:
        body = f"{body} notes: {note}"
    clock.stamp(history, body)


def _finalize_terminal(
    action_id: str,
    *,
    result: SessionResult,
) -> None:
    """Record the chosen terminal action; narrate only after actor output freezing."""
    spec = CATALOG[action_id]
    result.end_reason = spec.end_reason or "terminated"
    result.terminal_issue_mode = {
        "file_issue": "filed",
        "give_up": "left",
        "accept_with_reservations": "accepted",
    }.get(action_id)
    # Spec-0084/T2: narration is deferred until the outer runner has frozen actor outputs.


def _narrate_terminal(*, result, persona, client, system, task, history, state) -> None:
    if result.terminal_issue_mode is not None:
        try:
            issue_resp = client.respond(
                system, build_issue_turn(task, history, state, mode=result.terminal_issue_mode)
            )
        except Exception as exc:  # noqa: BLE001 - preserve actor evidence when review is unavailable
            # Terminal issue narration is non-gating. Preserve the chosen terminal
            # action, but retain a typed warning instead of losing the whole session.
            stage = getattr(exc, "stage", "file_issue")
            code = getattr(exc, "code", type(exc).__name__)
            result.persona_tail.extend(_take_persona_calls(client, stage))
            _take_protocol_events(client, result)
            result.protocol_events.append(
                {
                    "stage": stage,
                    "code": code,
                    "attempts": getattr(exc, "attempts", 1),
                    "status": "warning",
                    "terminal_narration": True,
                }
            )
            result.signals.append(
                f"PERSONA_PROTOCOL_WARNING: stage={stage} code={code} terminal_narration"
            )
            return
        result.persona_tail.extend(_take_persona_calls(client, "file_issue"))
        _take_protocol_events(client, result)
        issue_text = str(issue_resp.get("issue") or "")
        result.issue_artifact = emit_issue_artifact(persona, result.turns, issue_text)


def _activity_from_harness(harness) -> list[dict]:
    """Activity seen this round: prefer last_progress; else extract tool/tool_error short titles from last_steps."""
    progress = list(getattr(harness, "last_progress", None) or [])
    if progress:
        return progress
    steps = list(getattr(harness, "last_steps", None) or [])
    out: list[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") in ("tool", "tool_error"):
            out.append({"kind": str(step.get("kind")), "text": str(step.get("text") or "")})
    return out


def _heartbeat_once(
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    clock: _SessionClock,
    state: State,
    coef: Coef,
    help_text: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    waited_sec: float,
    progress: list[dict],
    progress_seen: int,
    heartbeats: int,
    ledger: _UtteranceLedger,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[str, str, bool, int]:
    """One-shot waiting decision (timer triggered). Any action (including keep_waiting) completes this heartbeat.

    Spec-0023: only judge → intent → act (three).
    Return (action, message, gap, new_progress_seen).
    Forced give_up: heartbeat count maxed, or keep_waiting with no new progress exhausts patience.
    """
    new_progress = len(progress) > progress_seen
    goal_before = goal_ledger.snapshot() if goal_ledger is not None else {}
    decision_task = _current_goal_text(task, goal_ledger)
    seen = len(progress)
    ctx = dict(
        task=decision_task,
        history_lines=history,
        state=state,
        help_text=help_text,
        waited_sec=waited_sec,
        progress=progress,
        prior_activity=prior_activity,
        goal_frame=goal_frame,
    )
    jret = client.respond(system, build_waiting_judge_turn(**ctx))
    wait_calls = _take_persona_calls(client, "waiting_judge")
    _record_private_evidence(state=state, calls=wait_calls, phase="waiting")
    judgment = _resolve_judgment(jret)
    perceive = str(jret.get("perceive", ""))
    goal_reading = _goal_reading(jret.get("goal_reading"))
    goal_updates: list[dict] = []
    if goal_ledger is not None and jret.get("goal_update") is not None:
        raw_updates = jret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
        ctx["goal_frame"] = goal_ledger.prompt_snapshot()
        ctx["task"] = _current_goal_text(task, goal_ledger)
    iret = client.respond(
        system,
        build_waiting_intent_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
        ),
    )
    new_calls = _take_persona_calls(client, "waiting_intent")
    wait_calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase="waiting")
    intent = _resolve_intent(iret)
    target_goal_ids = _goal_ids(iret.get("target_goal_ids"))
    expected_progress = str(iret.get("expected_progress") or "").strip()
    if goal_ledger is not None and iret.get("goal_update") is not None:
        raw_updates = iret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
        ctx["goal_frame"] = goal_ledger.prompt_snapshot()
        ctx["task"] = _current_goal_text(task, goal_ledger)
    aret = client.respond(
        system,
        build_waiting_act_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
            intent=intent,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
        ),
    )
    new_calls = _take_persona_calls(client, "waiting_act")
    wait_calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase="waiting")
    _drain_issue_notes(client, result)
    _record_act_report(aret, result, history, stage="waiting_act", turn=state.turn)
    if goal_ledger is not None and aret.get("goal_update") is not None:
        raw_updates = aret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
    action, wait_message, gap = _resolve_waiting(aret)
    goal_effect = aret.get("goal_effect") if isinstance(aret.get("goal_effect"), dict) else {}
    goal_field_audit = (
        audit_goal_fields(
            goal_ledger,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
            goal_effect=goal_effect,
            goal_updates=goal_updates,
        )
        if goal_ledger is not None
        else {}
    )
    if heartbeats >= _MAX_HEARTBEATS:
        action = "give_up"
        wait_message = ""
        gap = False
    elif action == "keep_waiting":
        if not new_progress:
            state.patience = max(0, state.patience - coef.patience_decay)
        if state.patience <= 0:
            action = "give_up"
            wait_message = ""
            gap = False
    _log_waiting(
        result,
        state,
        action,
        wait_message,
        judgment=judgment,
        intent=intent,
        perceive=perceive,
        gap=gap,
        on_progress=on_progress,
        persona_trace=wait_calls,
        ledger=ledger,
        goal_before=goal_before,
        goal_reading=goal_reading,
        target_goal_ids=target_goal_ids,
        expected_progress=expected_progress,
        goal_updates=goal_updates,
        goal_after=goal_ledger.snapshot() if goal_ledger is not None else {},
        goal_effect=goal_effect,
        goal_field_audit=goal_field_audit,
    )
    _note_waiting_memory(
        history,
        clock,
        judgment=judgment,
        intent=intent,
        action=action,
        message=wait_message,
        perceive=perceive,
        gap=gap,
    )
    return action, wait_message, gap, seen


def _try_ready_reply(harness) -> str | None:
    """Before heartbeat action execution: non-blocking check if reply already arrived (may be buffered while LLM is thinking)."""
    fn = getattr(harness, "try_reply", None)
    if not callable(fn):
        return None
    return fn()


def _await_harness(
    harness,
    message: str,
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    clock: _SessionClock,
    state: State,
    coef: Coef,
    help_text: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    ledger: _UtteranceLedger,
    open_utterance_id: str,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[str, float, str | None, str | None]:
    """After message write, enter AwaitEvent: reply → pass to main loop; timer → one-shot heartbeat then return to AwaitEvent.

    Spec-0024/T6: this round's write associates with open_utterance_id; received reply/interrupt closes that open.
    Spec-0036: unified write_message (compatible with begin/emit aliases).
    Heartbeat actions (including keep_waiting / send_message) complete this heartbeat; do not continue poll within heartbeat.

    Return (harness_output, elapsed_sec, terminal_action, user_control):
      - reply: terminal=None, user_control=None (main loop next round decides);
      - interrupt: control response enters harness_output, user_control="interrupt";
      - give_up: harness_output="", terminal="give_up";
      - crash: harness_output is [harness error] string.
    """
    t0 = time.monotonic()
    begin_at = clock.now()
    try:
        _write_harness_message(harness, message)
    except Exception as exc:  # noqa: BLE001
        ledger.clear_open()
        return (
            f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
            time.monotonic() - t0,
            None,
            None,
        )
    ledger.mark_open(open_utterance_id)
    heartbeats = 0
    progress_seen = 0
    protocol_failures = 0
    while True:
        # —— AwaitEvent ——
        try:
            kind, val = harness.poll(_HEARTBEAT_SEC)
        except Exception as exc:  # noqa: BLE001
            ledger.clear_open()
            return (
                f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                time.monotonic() - t0,
                None,
                None,
            )
        if kind == "reply":
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            return str(val), time.monotonic() - t0, None, None

        # —— HeartbeatOnce（timer）——
        waited = float(val)  # type: ignore[arg-type]
        clock.observe(begin_at + waited)
        heartbeats += 1
        progress = list(getattr(harness, "last_progress", None) or [])
        current_goal_frame = (
            goal_ledger.prompt_snapshot() if goal_ledger is not None else goal_frame
        )
        try:
            action, wait_message, _gap, progress_seen = _heartbeat_once(
                client=client,
                system=system,
                task=task,
                history=history,
                clock=clock,
                state=state,
                coef=coef,
                help_text=help_text,
                result=result,
                on_progress=on_progress,
                prior_activity=prior_activity,
                waited_sec=waited,
                progress=progress,
                progress_seen=progress_seen,
                heartbeats=heartbeats,
                ledger=ledger,
                goal_frame=current_goal_frame,
                goal_ledger=goal_ledger,
            )
            # A successful complete heartbeat clears only the transient warning;
            # protocol evidence remains in result.protocol_events.
            protocol_failures = 0
        except PersonaProtocolError as exc:
            protocol_failures += 1
            result.persona_tail.extend(_take_persona_calls(client, exc.stage))
            _take_protocol_events(client, result)
            result.protocol_events.append(
                {
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                    "heartbeat": heartbeats,
                    "status": "warning"
                    if protocol_failures < _MAX_PROTOCOL_STALL_HEARTBEATS
                    else "stalled",
                }
            )
            result.signals.append(
                f"PERSONA_PROTOCOL_WARNING: stage={exc.stage} code={exc.code} "
                f"attempts={exc.attempts} heartbeat={heartbeats}"
            )
            # No fake intent/action, no patience mutation, and no harness write on
            # a malformed decision. Keep polling once so a later harness reply can
            # still be judged. Repeated failure becomes a distinct safe terminal.
            if protocol_failures >= _MAX_PROTOCOL_STALL_HEARTBEATS:
                result.interaction_status = "protocol_stalled"
                result.evaluation_status = "invalid"
                result.evaluation_error = {
                    "kind": "persona_protocol",
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                    "heartbeat_failures": protocol_failures,
                }
                # All protocol evidence has already been copied to result. Close
                # the harness only at this terminal boundary; the outer connector
                # also closes idempotently for production sessions.
                try:
                    harness.shutdown()
                except Exception:  # pragma: no cover - cleanup is best effort
                    pass
                return "", time.monotonic() - t0, "protocol_stalled", None
            continue
        # A reply may have entered the buffer during decision-making: verify before executing the action; if one is present, void the waiting action and hand control back to the main loop.
        ready = _try_ready_reply(harness)
        if ready is not None:
            clock.stamp(
                history,
                f"waiting decision aborted before acting ({action}): "
                "a harness reply arrived while you were deciding; "
                "you did not carry out that waiting action — "
                "back to the main loop to read the reply.",
            )
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            return ready, time.monotonic() - t0, None, None
        # Any action ends the current heartbeat; below we only perform the I/O side effects, then either return to the main loop or go back to AwaitEvent.
        if action == "send_message":
            try:
                _write_harness_message(harness, wait_message)
            except Exception as exc:  # noqa: BLE001
                ledger.clear_open()
                return (
                    f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                    time.monotonic() - t0,
                    None,
                    None,
                )
            continue  # Return to AwaitEvent: the next reply wakes the main loop; no more nested heartbeat decisions
        if action == "interrupt":
            try:
                ctrl_out = harness.interrupt()
            except Exception as exc:  # noqa: BLE001
                ledger.clear_open()
                return (
                    f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                    time.monotonic() - t0,
                    None,
                    None,
                )
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            if isinstance(ctrl_out, str) and ctrl_out.startswith(HARNESS_ERROR_PREFIX):
                return ctrl_out, time.monotonic() - t0, None, "interrupt"
            return str(ctrl_out or ""), time.monotonic() - t0, None, "interrupt"
        if action == "give_up":
            try:
                harness.shutdown()
            except Exception:  # noqa: BLE001  give_up is a terminal intent; a close failure must not block the session wrap-up
                pass
            ledger.clear_open()
            return "", time.monotonic() - t0, "give_up", None
        # keep_waiting: the action has been recorded and may drain patience; return to AwaitEvent and wait for the next reply or the next timer hop.
        continue


def run_session(
    persona: Persona,
    client: PersonaClient,
    harness,
    task: str,
    *,
    help_text: str = "",
    on_progress: Callable[[SessionResult], None] | None = None,
    deadline_seconds: float | None = None,
    before_terminal_review: Callable[[], None] | None = None,
    on_actor_complete: Callable[[dict], None] | None = None,
) -> SessionResult:
    # on_progress: after each round's TurnLog is written, invoke the callback once with the in-progress result (including the terminal round) so the observation layer (dashboard) can display round by round.
    # Spec-0023: both the main decision and the heartbeat are judge → intent → act (three); no mode knob.
    coef = make_coef(persona)
    state = init_state(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    goal_ledger = GoalLedger.from_task(task)
    result.goal_ledger = goal_ledger.snapshot()
    history: list[str] = []
    clock = _SessionClock()
    harness_output = ""
    harness_steps: list = []  # Inner process stream paired with harness_output
    harness_events: list = []  # The previous round's visible stdout event stream, for the next main decision to perceive
    # Activity bars of requests completed in the previous round (process memory, for comparison)
    prior_activity: list[dict] = []
    ledger = _UtteranceLedger()  # Spec-0024/T6: request–reply pairing
    started_at = time.monotonic()

    while state.turn < MAX_TURNS:
        if deadline_seconds is not None and time.monotonic() - started_at >= deadline_seconds:
            result.end_reason = "official_deadline"
            break
        set_usage_context(interaction_id=f"turn-{state.turn}", turn_no=state.turn)
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE
        goal_before = goal_ledger.snapshot()

        # ② Derived action space
        space = derive_action_space(phase, persona, state)

        # ③ Main decision follows the same stages: judge → intent → act.
        try:
            ret, decide_calls, intent, gap = _main_decide(
                client=client,
                system=system,
                task=task,
                history=history,
                harness_output=harness_output,
                harness_events=harness_events,
                space=space,
                state=state,
                help_text=help_text,
                appraise_task=phase is Phase.OPENING,
                result=result,
                phase=phase.value,
                goal_frame=goal_ledger.prompt_snapshot(),
                goal_ledger=goal_ledger,
            )
        except PersonaProtocolError as exc:
            result.persona_tail.extend(_take_persona_calls(client, exc.stage))
            _take_protocol_events(client, result)
            result.interaction_status = "protocol_unrecoverable"
            result.evaluation_status = "invalid"
            result.evaluation_error = {
                "kind": "persona_protocol",
                "stage": exc.stage,
                "code": exc.code,
                "attempts": exc.attempts,
            }
            result.end_reason = "evaluator_invalid"
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            break
        # _main_decide applies updates between judge/intent/rejudge stages so the current
        # decision sees them.  Do not apply them again here; this is only the turn-log view.
        goal_updates = [dict(item) for item in (ret.get("goal_updates_applied") or [])]
        goal_reading = _goal_reading(ret.get("goal_reading"))
        target_goal_ids = _goal_ids(ret.get("target_goal_ids"))
        expected_progress = str(ret.get("expected_progress") or "").strip()
        goal_effect = ret.get("goal_effect") if isinstance(ret.get("goal_effect"), dict) else {}
        acceptance_basis = (
            dict(ret.get("acceptance_basis") or {})
            if isinstance(ret.get("acceptance_basis"), dict)
            else {}
        )
        goal_field_audit = (
            dict(ret.get("goal_field_audit") or {})
            if isinstance(ret.get("goal_field_audit"), dict)
            else {}
        )
        goal_after = goal_ledger.snapshot()
        result.goal_ledger = goal_after
        result.goal_audit = goal_ledger.audit()
        # At session start: based on the persona's subjective reading of the task size, overlay a one-time small fluctuation on the patience baseline (the same persona shows different patience for different tasks).
        if phase is Phase.OPENING:
            apply_task_load(state, str(ret.get("task_load", "normal")))

        # ③.5 Option B: when action=='free', let the model self-assess and classify it into a legal id (replacing hard-coded keyword guessing).
        # Enabled only when the client supports classify_action; otherwise fall through to resolve's safe fallback.
        try:
            if ret.get("action") == "free" and hasattr(client, "classify_action"):
                ret = {**ret, "action": client.classify_action(system, ret, space)}
                decide_calls.extend(_take_persona_calls(client, "classify_action"))

            # ④ resolve: accepts only genuinely legal actions; missing, out-of-range, or channel-conflicting ones all fail closed.
            action_id, message = resolve_action(ret, space, persona)
        except (PersonaProtocolError, ActionResolutionError) as exc:
            result.persona_tail.extend(decide_calls)
            result.interaction_status = "protocol_unrecoverable"
            if isinstance(exc, PersonaProtocolError):
                result.persona_tail.extend(_take_persona_calls(client, exc.stage))
                _take_protocol_events(client, result)
                detail = {
                    "kind": "persona_protocol",
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                }
            else:
                detail = {
                    "kind": "action_resolution",
                    "code": exc.code,
                    "action": exc.action_id,
                }
            result.evaluation_status = "invalid"
            result.evaluation_error = detail
            result.end_reason = "evaluator_invalid"
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            break
        spec = CATALOG[action_id]

        # ⑤ State write-back (consumes only the subjective verdict)
        verdict = ret.get("verdict", "unsure")
        if verdict not in VERDICTS:
            verdict = "unsure"
        apply_verdict(state, verdict, coef)

        note = str(ret.get("perceive", "")).strip()
        head = f"[{verdict}|{intent}→{action_id}]"
        perceive_logged = f"{head} {note}" if note else head

        # Spec-0024/T6: if this beat carries the previous reply, attach answers; if this beat sends outward, allocate an utterance.
        answers_id, answers_said = ("", "")
        if harness_output.strip():
            answers_id, answers_said = ledger.consume_pending_answers()
        utterance_id = ""
        delivery = ""
        if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE and message.strip():
            utterance_id = ledger.alloc(message)
            delivery = "open"

        # This reply is about to be logged with this TurnLog and is no longer left hanging
        result.pending_harness_output = None
        result.pending_harness_steps = None
        result.pending_harness_events = None
        result.turns.append(
            TurnLog(
                turn=state.turn,
                phase=phase.value,
                action_space=space,
                perceive=perceive_logged,
                verdict=verdict,
                action=action_id,
                message=message,
                executor=spec.executor.value,
                channel=spec.channel.value,
                patience=state.patience,
                trust=state.trust.value,
                harness_output=harness_output,
                harness_steps=harness_steps,
                harness_events=list(harness_events or []),
                persona_trace=decide_calls,
                utterance_id=utterance_id,
                delivery=delivery,
                answers_utterance_id=answers_id,
                answers_said=answers_said,
                goal_before=goal_before,
                goal_reading=goal_reading,
                target_goal_ids=target_goal_ids,
                expected_progress=expected_progress,
                goal_updates=goal_updates,
                goal_after=goal_after,
                goal_effect=goal_effect,
                goal_field_audit=goal_field_audit,
                acceptance_basis=acceptance_basis,
            )
        )
        if gap:
            result.signals.append(f"WAIT_GAP: intent={intent} action={action_id}")
        if on_progress is not None:
            # Round-by-round observation hook (including the terminal round): feeds observation layers such as the dashboard; does not affect the main loop
            on_progress(result)

        # Record history (only utterances actually sent on line B; empty messages are not fabricated and not recorded); uniform [+Ns] prefix.
        if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE and message.strip():
            clock.stamp(history, f"you -> harness: {message}")

        # ⑥ Termination determination (all three termination types leave one self-contained issue in the persona's own voice; see _finalize_terminal)
        if spec.effect is Effect.TERMINATE:
            # Spec-0056/T4: persist the user's terminal claim without overriding it.
            terminal_audit = goal_ledger.commit_terminal_effect(
                action_id, goal_effect, turn=state.turn
            )
            basis_audit = audit_acceptance_basis(
                action_id,
                acceptance_basis,
                persona_d1=persona.d1.value,
                persona_d3=persona.d3.value if persona.d3 is not None else "",
            )
            terminal_audit["acceptance_basis"] = basis_audit
            if basis_audit.get("status") == "warning":
                terminal_audit["status"] = "warning"
                terminal_audit.setdefault("warnings", []).extend(
                    f"acceptance_basis:{warning}" for warning in basis_audit.get("warnings", [])
                )
            result.terminal_audit = terminal_audit
            result.goal_acceptance = goal_ledger.terminal_check(
                action_id, goal_effect, terminal_audit=terminal_audit
            )
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            result.goal_audit["terminal"] = terminal_audit
            if terminal_audit.get("status") == "warning":
                result.goal_audit["status"] = "warning"
                result.goal_audit.setdefault("warnings", []).extend(
                    terminal_audit.get("warnings", [])
                )
                result.signals.append(
                    "GOAL_TERMINAL_AUDIT_WARNING: " + ",".join(terminal_audit.get("warnings", []))
                )
            if basis_audit.get("alignment") == "weak":
                result.signals.append("PERSONA_ACCEPTANCE_ALIGNMENT: weak")
            # The terminal action is a subjective ledger transaction.  Update the
            # already-persisted terminal turn with the post-commit snapshot so the
            # trace cannot show close while the final goal remains open.
            result.turns[-1].goal_after = goal_ledger.snapshot()
            result.turns[-1].goal_field_audit = {
                **result.turns[-1].goal_field_audit,
                "terminal": terminal_audit,
            }
            if result.goal_acceptance["status"] in {
                "subjective_accept_unverified",
                "reservations_with_unmet_goals",
            }:
                result.signals.append(
                    "GOAL_ACCEPT_UNVERIFIED: "
                    + ",".join(result.goal_acceptance["unresolved_goals"])
                )
            _finalize_terminal(
                action_id,
                result=result,
            )
            break

        # ⑦ Routing. EMIT: a real subprocess goes through AwaitEvent (reply → main decide; timer → one-shot heartbeat);
        # Fake/Scripted fall back to the blocking route.
        _t0 = time.monotonic()
        _emits = spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE
        terminal_from_wait: str | None = None
        user_control: str | None = None
        supervised = _emits and bool(message.strip()) and _supports_heartbeat(harness)
        if supervised:
            nxt, elapsed, terminal_from_wait, user_control = _await_harness(
                harness,
                message,
                client=client,
                system=system,
                task=task,
                history=history,
                clock=clock,
                state=state,
                coef=coef,
                help_text=help_text,
                result=result,
                on_progress=on_progress,
                prior_activity=prior_activity,
                ledger=ledger,
                open_utterance_id=utterance_id,
                goal_frame=goal_ledger.prompt_snapshot(),
                goal_ledger=goal_ledger,
            )
            # Waiting decision gives up: take the termination path and finish
            if terminal_from_wait == "give_up":
                _finalize_terminal(
                    "give_up",
                    result=result,
                )
                break
            if terminal_from_wait == "protocol_stalled":
                # Protocol degradation is not user give-up and must not fabricate a
                # terminal message or issue. Keep the container/log evidence for the
                # outer session store, then leave the normal metrics as invalid.
                result.end_reason = "protocol_stalled"
                result.interaction_status = "protocol_stalled"
                result.evaluation_status = "invalid"
                break
        else:
            nxt = route(action_id, message, state, harness, harness_output)
            elapsed = time.monotonic() - _t0
            if nxt is not None:
                clock.observe(clock.now() + elapsed)
                # Blocking route: a reply immediately closes the open utterance just allocated this beat
                if utterance_id:
                    ledger.mark_open(utterance_id)
                    ledger.close_open_as_answered()
            elif action_id == "keep_waiting":
                # Waiting again with no new reply: still hand the side-channel events swallowed during the wait to the next round's perception (to avoid idle spinning that drops status).
                drain_only = getattr(harness, "drain_visible_events", None)
                if callable(drain_only):
                    ev_only = list(drain_only())
                    if ev_only:
                        harness_events = ev_only
        if nxt is not None:
            # Time awareness · light patience drain: only extreme timeouts automatically deduct a bit of patience.
            # Only for the blocking route: waiting frustration on the AwaitEvent path is already modeled by keep_waiting's one-shot heartbeat; no double counting.
            if not supervised and elapsed >= _EXTREME_WAIT_SEC:
                state.patience = max(0, state.patience - 1)
            harness_output = nxt
            # Inner process stream paired with the reply: after send, the launcher attaches it to harness.last_steps (observation side channel).
            # Fake/Scripted harnesses lack this attribute → []. route only actually calls send on EMIT rounds, so the value fetched here is this round's reply's.
            steps = getattr(harness, "last_steps", None)
            harness_steps = list(steps) if isinstance(steps, list) else []
            drain_events = getattr(harness, "drain_visible_events", None)
            if callable(drain_events):
                harness_events = list(drain_events())
            else:
                harness_events = []
            # Activity bars are written into process memory: available for comparison at the next wait (without asserting attribution of 'which round this activity belongs to').
            prior_activity = _activity_from_harness(harness)
            if prior_activity:
                titles = [
                    str(p.get("text") or "").strip()
                    for p in prior_activity[-8:]
                    if isinstance(p, dict) and str(p.get("text") or "").strip()
                ]
                if titles:
                    clock.stamp(
                        history,
                        "harness activity: " + "; ".join(titles)[:240],
                    )
            # Spec-0024/T6: answers are written to the next beat's TurnLog; history still carries a short human-readable preview.
            if user_control:
                clock.stamp(
                    history,
                    "YOU interrupted (Ctrl+C); harness acknowledged: "
                    f"{nxt.splitlines()[0][:80]}...",
                )
            else:
                clock.stamp(history, f"harness -> you: {nxt.splitlines()[0][:80]}...")
            # Push the harness reply to the observation layer as soon as it arrives (without waiting for the persona's next round); otherwise the dashboard conversation is missing half of the dialogue during long tasks
            result.pending_harness_output = nxt
            result.pending_harness_steps = harness_steps
            result.pending_harness_events = list(harness_events or [])
            if on_progress is not None:
                on_progress(result)
            # timeout/crash is the terminal state of an invalidated workspace session. Reply text remains as pending
            # evidence is retained, but cannot enter the next round of persona decision-making, and certainly cannot write messages to the dead container.
            terminal_status = _harness_terminal_status(harness)
            if terminal_status:
                result.end_reason = f"harness_{terminal_status}"
                result.signals.append(f"HARNESS_TERMINAL: {terminal_status}")
                break
        # If this round produces no next harness output (e.g., model idle), retain the previous visible output for the next round to continue evaluation.

    result.goal_ledger = goal_ledger.snapshot()
    final_goal_audit = goal_ledger.audit()
    if result.terminal_audit:
        final_goal_audit["terminal"] = result.terminal_audit
        if result.terminal_audit.get("status") == "warning":
            final_goal_audit["status"] = "warning"
            final_goal_audit.setdefault("warnings", []).extend(
                result.terminal_audit.get("warnings", [])
            )
    result.goal_audit = final_goal_audit
    checkpoint = {
        "version": 1,
        "result": asdict(result),
        "history": list(history),
        "state": {**asdict(state), "trust": state.trust.value},
        "task": _current_goal_text(task, goal_ledger),
    }
    if on_actor_complete is not None:
        on_actor_complete(checkpoint)
    if before_terminal_review is not None:
        before_terminal_review()
    return _finish_terminal_review(
        persona=persona,
        client=client,
        result=result,
        history=history,
        state=state,
        task=checkpoint["task"],
    )


def resume_terminal_review(
    *, persona: Persona, client: PersonaClient, checkpoint: dict
) -> SessionResult:
    """Resume only terminal review from a frozen completed interaction, never send to Harness."""
    from .dimensions import TrustStance

    if checkpoint.get("version") != 1:
        raise ValueError("Unsupported terminal review checkpoint")
    values = dict(checkpoint["result"])
    values["turns"] = [TurnLog(**row) for row in values["turns"]]
    for key in ("feeling", "feeling_derived"):
        if values.get(key) is not None:
            values[key] = FeelingScore.from_dict(values[key])
    result = SessionResult(**values)
    if result.persona_id != persona.persona_id:
        raise ValueError("Terminal review checkpoint belongs to another persona")
    state = State(**{**checkpoint["state"], "trust": TrustStance(checkpoint["state"]["trust"])})
    return _finish_terminal_review(
        persona=persona,
        client=client,
        result=result,
        history=list(checkpoint["history"]),
        state=state,
        task=checkpoint["task"],
    )


def _finish_terminal_review(*, persona, client, result, history, state, task) -> SessionResult:
    system = build_system(persona)
    _narrate_terminal(
        result=result,
        persona=persona,
        client=client,
        system=system,
        task=task,
        history=history,
        state=state,
    )
    _take_protocol_events(client, result)
    if result.evaluation_status == "invalid":
        err = result.evaluation_error or {}
        reason = f"Evaluator invalid; exclude from harness metrics: {err.get('code', 'unknown')}"
        if result.interaction_status in {"protocol_unrecoverable", "protocol_stalled"}:
            result.signals.append(f"PROTOCOL_UNRECOVERABLE: {err}")
        result.signals.append(f"EVALUATOR_INVALID: {err}")
        result.experience = experience_feedback(None, source="simulated_user", error=reason)
        return result

    # Conclusion: aggregate purely subjective behavioral signals
    _collect_signals(result, persona)

    # Session end: two-stream convergence of subjective experience scores (training signals), both consuming only subjective signals, not objective ground truth:
    # ② Framework derivation serves only as independent diagnosis, not to supplement missing measurements.
    result.feeling_derived = derive_feeling(result.end_reason, result.turns)
    # ① LLM self-evaluation: persona rates "this experience" 1–4 in-character + rationale (spec-0001/T3 output method)
    set_usage_context(interaction_id=None, turn_no=None, operation="rate")
    try:
        rating = client.respond(system, build_rating_turn(task, history, state))
        result.persona_tail.extend(_take_persona_calls(client, "rate"))
        _take_protocol_events(client, result)
        result.feeling = parse_feeling_llm(rating)
        result.experience = experience_feedback(rating, source="simulated_user")
    except Exception as exc:  # noqa: BLE001 - a failed reviewer cannot erase the actor's artifacts
        # Rating is non-gating. Retain its failure without inventing a self-rating.
        stage = getattr(exc, "stage", "rate")
        code = getattr(exc, "code", type(exc).__name__)
        result.persona_tail.extend(_take_persona_calls(client, stage))
        _take_protocol_events(client, result)
        result.protocol_events.append(
            {
                "stage": stage,
                "code": code,
                "attempts": getattr(exc, "attempts", 1),
                "status": "warning",
                "non_gating": True,
            }
        )
        result.signals.append(f"PERSONA_PROTOCOL_WARNING: stage={stage} code={code} rating")
        result.experience = experience_feedback(None, source="simulated_user", error=str(exc))
        if isinstance(exc, PersonaProtocolError) and not code.startswith("internal_error:"):
            result.experience["status"] = "invalid"
    return result


def _collect_signals(result: SessionResult, persona: Persona) -> None:
    """All behavior signals derived from this session's subjective data (end_reason / verdict / persona), never read objective ground truth."""
    fails = sum(1 for t in result.turns if t.verdict == "failed_blame_harness")
    if persona.d1.value in ("blind", "shallow") and result.end_reason == "abandoned":
        result.signals.append(
            "BEHAVIORAL: low-capability user abandoned without being able to self-fix."
        )
    if result.end_reason == "issue_filed":
        result.signals.append(
            "BEHAVIORAL: user was dissatisfied enough to stop and file a structured issue."
        )
    if fails >= 2:
        result.signals.append(
            f"FRICTION: user blamed the harness on {fails} turns before ending "
            f"({result.end_reason})."
        )
