"""Terminal coding assistant runtime.

The process reads one JSON object per line from stdin and writes JSON objects to stdout.
It builds a NexAU Agent from this directory's agent.yaml and uses SANDBOX_WORK_DIR as
the workspace for shell commands. The internal agent topology is an implementation detail.

Project guidance: LLM_* environment variables configure the model endpoint. The process maintains
a stable session_id; recovery from a hard interrupt may rebuild the internal agent_id
and restore conversation history. See META_SPEC.md for project boundaries and development guidance.
"""

from __future__ import annotations

import json
import math
import os
import queue
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from observability import observer

_HERE = Path(__file__).resolve().parent
# Empty replies / gateway glitches use _RUN_RETRIES backoff retry (same instance, no session switch).
# Spec-0084/T3: an explicit task deadline bounds all attempts; unknown means undeclared.
_RUN_RETRIES = 4
# Grace period (seconds) to wait for nexau graceful shutdown after interrupt (type:interrupt) while preserving session/history:
# executor.force_stop() only sets the interrupt signal; run will exit safely at the next checkpoint. If still running after grace period,
# it means graceful shutdown was missed → allocate new agent_id and rebuild to avoid deadlock, explicitly restore history.
_INTERRUPT_GRACE = 15.0
# Standard reply sent to user on interrupt: explicitly states "halted, incomplete, session context preserved" so user can decide next steps.
_INTERRUPT_REPLY = (
    "[interrupted] Stopped the current request as you asked; this step is incomplete. "
    "Session context has been preserved. Send revised requirements or your next instruction "
    "to continue from the current progress."
)
_HARNESS_USER_ID = "harness_user"

# Internal dispatch: match message first word against slash commands (e.g., /help /exit /quit); everything else goes to agent.
_HELP_PATH = _HERE / "HELP.md"
_EXIT_COMMANDS = frozenset({"/exit", "/quit"})
_EXIT_REPLY = (
    "[exited] Session closed at your request. Send a new message in a new session to start again."
)


class _Interrupted(Exception):
    """User interrupt received: abort current agent.run. rebuild=True means graceful shutdown was missed and agent must be rebuilt to avoid deadlock."""

    def __init__(self, *, rebuild: bool) -> None:
        super().__init__("interrupted by user")
        self.rebuild = rebuild


def _read_help() -> str:
    """Return the user-facing help text shown by /help."""
    try:
        text = _HELP_PATH.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "Harness help is unavailable: HELP.md is missing."
    return text or "Harness help is empty."


def _slash_command(message: str) -> tuple[str, bool] | None:
    """Recognize built-in slash commands by message body; return (reply, should_exit) or None.

    Command recognition happens inside harness; channel remains message. Only exact first-word match (case-insensitive).
    """
    text = (message or "").strip()
    if not text:
        return None
    head = text.split(None, 1)[0].lower()
    if head == "/help":
        return _read_help(), False
    if head in _EXIT_COMMANDS:
        return _EXIT_REPLY, True
    return None


def _force_stop(agent) -> bool:
    """Thread-safely request graceful shutdown of current run from nexau (set stop_signal + shutdown_event, preserve history).

    Returns True if signal is successfully set; returns False if nexau version lacks this primitive or signal set fails (caller falls back to agent rebuild)."""
    try:
        executor = getattr(agent, "executor", None)
        if executor is not None and hasattr(executor, "force_stop"):
            executor.force_stop()
            return True
    except Exception:  # noqa: BLE001  Interrupt is best-effort; failures must never crash harness
        pass
    return False


# Text length limits for inner process flow steps: tool arguments/outputs may contain entire file contents, summarized before entering timeline;
# assistant is the process core, given a generous limit only to prevent extreme runaway.
_TOOL_TEXT_CAP = 200
_TOOL_RESULT_CAP = 500
_ASSISTANT_TEXT_CAP = 20_000
# stdout write lock: tracer thread emits progress, main thread emits final reply—must be mutually exclusive to prevent interleaving.
_stdout_lock = threading.Lock()


def _wire_out(event_type: str, **payload) -> dict:
    """Encode a process event as one typed JSON object."""
    return {"type": event_type, **payload}


def _emit_progress(*, kind: str, text: str) -> None:
    """Emit a Codex-style activity summary to user (side-channel before final reply).

    Only emit tool / tool_error—brief and scannable; full assistant text does not go to progress bar (that is internal diagnostics).
    Failures are always silent: losing progress must never drag down the agent.
    """
    if kind not in ("tool", "tool_error"):
        return
    try:
        line = json.dumps(_wire_out("progress", kind=kind, text=text), ensure_ascii=False)
        with _stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _emit_status(text: str) -> None:
    """Emit harness's own visible state to user; only describe what is being done, do not correlate request/reply pairs."""
    try:
        line = json.dumps(_wire_out("status", text=text), ensure_ascii=False)
        with _stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _emit_usage(**payload) -> None:
    """Per-invocation machine observation side-channel; never carry prompt/response body."""
    try:
        line = json.dumps(_wire_out("usage", **payload), ensure_ascii=False)
        with _stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


class _BudgetExhausted(Exception):
    def __init__(self, *, reason, rebuild):
        super().__init__(reason)
        self.reason = reason
        self.rebuild = rebuild


def _run_supervised(agent, message, ctrl_q, *, deadline=None, message_id=None):
    """Supervise the native Agent call without wrapping its async model client."""
    box: dict = {}
    outcome = getattr(agent, "_harness_outcome", None)
    if outcome is not None:
        outcome.reset()
    attempt_id = uuid.uuid4().hex
    began = time.monotonic()

    def expired_reason():
        limit, reason = deadline() if deadline is not None else (None, None)
        return reason if limit is not None and time.monotonic() >= limit else None

    if reason := expired_reason():
        raise _BudgetExhausted(reason=reason, rebuild=False)
    observer.event("attempt_started", attempt_id=attempt_id)

    def target():
        try:
            box["out"] = agent.run(message=message)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    while thread.is_alive():
        thread.join(0.1)
        reason = expired_reason()
        control = None
        if ctrl_q is not None:
            try:
                control = ctrl_q.get_nowait()
            except queue.Empty:
                pass
        interrupted = (
            isinstance(control, dict)
            and control.get("type") == "interrupt"
            and (message_id is None or control.get("message_id") in (None, "", message_id))
        )
        if interrupted and control.get("reason") in {
            "task_budget_exhausted",
            "message_activity_exhausted",
        }:
            reason = control["reason"]
        if reason or interrupted:
            observer.event(
                "budget_exhausted" if reason else "interrupt_requested", attempt_id=attempt_id
            )
            stopped = _force_stop(agent)
            if stopped:
                thread.join(_INTERRUPT_GRACE)
            observer.event(
                "attempt_failed",
                attempt_id=attempt_id,
                error_type="_BudgetExhausted" if reason else "_Interrupted",
                elapsed_seconds=time.monotonic() - began,
            )
            if reason:
                raise _BudgetExhausted(reason=reason, rebuild=not stopped or thread.is_alive())
            raise _Interrupted(rebuild=not stopped or thread.is_alive())
    if "err" in box:
        observer.event(
            "attempt_failed",
            attempt_id=attempt_id,
            error_type=type(box["err"]).__name__,
            elapsed_seconds=time.monotonic() - began,
        )
        raise box["err"]
    observer.event(
        "attempt_returned", attempt_id=attempt_id, elapsed_seconds=time.monotonic() - began
    )
    return box.get("out")


def _setup_workspace() -> str:
    """Create a clean workspace per session as bash's "project root directory", write to SANDBOX_WORK_DIR (read by nexau local sandbox)."""
    ws = os.environ.get("SANDBOX_WORK_DIR")
    if not ws:
        ws = tempfile.mkdtemp(prefix="harness_ws_")
        os.environ["SANDBOX_WORK_DIR"] = ws
    return ws


def _snapshot_history(agent) -> list:
    """Extract restorable history snapshot from live agent; return empty list on failure (rebuild still changes lock, just with no memory to restore)."""
    try:
        hist = getattr(agent, "history", None)
        if hist is None:
            return []
        return list(hist)
    except Exception:  # noqa: BLE001  Snapshot failure must not block rebuild to avoid deadlock
        return []


def _restore_history(agent, messages) -> None:
    """Seed snapshot into new agent so next run carries old context (after agent_id change, storage key differs, must explicitly restore)."""
    if not messages:
        return
    try:
        agent.history = list(messages)
    except Exception:  # noqa: BLE001  Restore failure does not crash process; manifests as memory gap exposed by upper layer
        pass


class _ExecutionOutcome:
    """Per-attempt facts from NexAU hooks; reply text is never completion evidence."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.stop_reason = None
        self.completion_tool_succeeded = False

    def terminal(self):
        reason = self.stop_reason or "unavailable"
        if reason == "stop_tool_triggered" and self.completion_tool_succeeded:
            return "completed", "complete_task"
        if reason == "error_occurred":
            return "crashed", reason
        if reason == "user_interrupted":
            return "interrupted", reason
        return "incomplete", reason


def _make_terminal_observer(outcome):
    """Observe typed execution facts without modifying the model/tool lifecycle."""
    from nexau.archs.main_sub.execution.hooks import HookResult, Middleware

    class TerminalObserver(Middleware):
        def after_tool(self, hook_input):
            if hook_input.tool_name == "complete_task":
                output = hook_input.tool_output
                # NexAU normalizes a string tool result into {"result": ...}.
                if isinstance(output, dict) and "result" in output:
                    output = output["result"]
                if isinstance(output, str):
                    try:
                        output = json.loads(output)
                    except (ValueError, TypeError):
                        output = None
                outcome.completion_tool_succeeded = (
                    isinstance(output, dict)
                    and output.get("success") is True
                    and output.get("task_completed") is True
                )
            return HookResult.no_changes()

        def after_agent(self, hook_input):
            reason = hook_input.stop_reason
            outcome.stop_reason = reason.name.lower() if reason is not None else None
            return HookResult.no_changes()

    return TerminalObserver()


def _build_agent(collector, session_id, agent_id):
    """Construct tool-based nexau Agent per agent.yaml in this directory (only attach bash + complete_task).

    session_id is fixed per process; agent_id identifies lock key—must use new agent_id on rebuild to avoid deadlock.
    Attach collector as tracer: each inner step collected into collector.steps, provided to caller via protocol steps field.
    """
    from nexau import Agent, AgentConfig
    from nexau.archs.main_sub.execution.hooks import MiddlewareManager

    cfg = AgentConfig.from_yaml(config_path=_HERE / "agent.yaml")
    if raw_limit := os.environ.get("LLM_MAX_CONTEXT_TOKENS"):
        input_limit = int(raw_limit)
        if input_limit <= 0:
            raise ValueError("LLM_MAX_CONTEXT_TOKENS must be positive")
        cfg.max_context_tokens = input_limit
    # Inner process flow → collector.steps (diagnostics, does not affect reply)
    cfg.resolved_tracer = collector
    outcome = _ExecutionOutcome()
    terminal_observer = _make_terminal_observer(outcome)
    cfg.middlewares = [*(cfg.middlewares or []), terminal_observer]
    agent = Agent(
        config=cfg,
        session_id=session_id,
        agent_id=agent_id,
        user_id=_HARNESS_USER_ID,
    )
    # NexAU 0.4.1 bridges model calls to sync whenever this manager is nonempty.
    # Our observer only needs execution/tool hooks. Keep model wrappers exactly
    # as configured, preserving native async cancellation for the default Seed.
    agent.executor.llm_caller.middleware_manager = MiddlewareManager(
        [
            middleware
            for middleware in agent.executor.middleware_manager.middlewares
            if middleware is not terminal_observer
        ]
    )
    agent._harness_outcome = outcome
    return agent


def _unwrap_reply(text: str) -> str:
    """Unwrap complete_task envelope → final answer for user.

    Tool-based agents often return the entire envelope ({"success":…, "status":"TASK_COMPLETED",
    "output":{"result":…}}) as a string, even double-JSON-encoded. User should only see the result itself,
    not protocol metadata. Decode at most two levels, extract output.result (or top-level result); if not an envelope or decode fails, return as-is.
    """
    s: object = text
    for _ in range(2):  # Decode at most twice
        if not (isinstance(s, str) and s.lstrip()[:1] in ("{", '"')):
            break
        try:
            dec = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            break
        if isinstance(dec, dict):
            out = dec.get("output")
            if isinstance(out, dict) and isinstance(out.get("result"), str):
                return out["result"]
            if isinstance(dec.get("result"), str):
                return dec["result"]
            break  # Is dict but no result key: preserve original
        s = dec  # Decoded result is still string (double-encoded), decode one more level
    return text


def _make_step_collector():
    """Construct a tracer that collects nexau spans into {kind,text} process flow (self-contained, only depends on nexau).

    LLM end→assistant, TOOL start→tool, TOOL end→tool_result/tool_error. Reset before each agent.run, read steps after—
    that is the complete process of this harness iteration; provided to caller via protocol steps field. User-visible answer still comes only from reply.
    Collection failures are always silent, never drag down agent main flow.
    """
    from nexau import BaseTracer, Span, SpanType

    def _compact_params(params):
        for key in ("command", "cmd"):
            v = params.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        try:
            return json.dumps(params, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(params)

    def _assistant_text(outputs):
        if not isinstance(outputs, dict):
            return ""
        content = outputs.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):  # Anthropic content blocks
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return "\n".join(p for p in parts if p).strip()
        choices = outputs.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"].strip()
        return ""

    def _compact_outputs(outputs):
        if outputs is None:
            return ""
        if isinstance(outputs, str):
            return outputs.strip()
        try:
            return json.dumps(outputs, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(outputs)

    class _StepCollector(BaseTracer):
        def __init__(self):
            self.steps: list[dict] = []
            self.agent_run_id = None

        def set_session_id(self, session_id):
            self.agent_run_id = session_id

        def reset(self):
            self.steps = []

        def _add(self, kind, text, cap):
            try:
                t = (text or "")[:cap]
                if t:
                    self.steps.append({"kind": kind, "text": t})
                    # Visible activity indicator while waiting (side-channel)
                    _emit_progress(kind=kind, text=t)
            except Exception:  # noqa: BLE001  Diagnostic flow failure does not affect agent
                pass

        def start_span(self, name, span_type, inputs=None, parent_span=None, attributes=None):
            span = Span(id=uuid.uuid4().hex, name=name, type=span_type)
            observer.event("span_started", span_id=span.id, kind=str(span_type))
            if span_type == SpanType.TOOL:
                tool = name.removeprefix("Tool: ")
                params = (inputs or {}).get("parameters") or {}
                summary = _compact_params(params) if isinstance(params, dict) else str(params)
                self._add(
                    "tool", f"🔧 {tool}: {summary}" if summary else f"🔧 {tool}", _TOOL_TEXT_CAP
                )
            return span

        def end_span(self, span, outputs=None, error=None, attributes=None):
            observer.event(
                "span_finished",
                span_id=span.id,
                kind=str(span.type),
                elapsed_seconds=max(0.0, time.time() - span.start_time),
                has_error=error is not None,
            )
            if span.type == SpanType.LLM:
                payload = outputs if isinstance(outputs, dict) else {}
                usage = payload.get("usage") or payload.get("usageMetadata") or {}
                if not isinstance(usage, dict):
                    dump = getattr(usage, "model_dump", None)
                    usage = dump() if callable(dump) else {}
                prompt_details = (
                    usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
                )
                completion_details = (
                    usage.get("completion_tokens_details")
                    or usage.get("output_tokens_details")
                    or {}
                )

                def number(*keys):
                    for key in keys:
                        value = usage.get(key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            return int(value)
                    return None

                input_tokens = number("prompt_tokens", "input_tokens", "promptTokenCount")
                output_tokens = number("completion_tokens", "output_tokens", "candidatesTokenCount")
                total_tokens = number("total_tokens", "totalTokenCount")
                if total_tokens is None and input_tokens is not None and output_tokens is not None:
                    total_tokens = input_tokens + output_tokens
                cached = number(
                    "cached_input_tokens", "cache_read_tokens", "cache_read_input_tokens"
                )
                if cached is None and isinstance(prompt_details, dict):
                    cached = prompt_details.get("cached_tokens")
                reasoning = number("reasoning_tokens", "thoughtsTokenCount")
                if reasoning is None and isinstance(completion_details, dict):
                    reasoning = completion_details.get("reasoning_tokens")
                available = any(
                    v is not None
                    for v in (input_tokens, output_tokens, total_tokens, cached, reasoning)
                )
                _emit_usage(
                    provider="nexau",
                    model=payload.get("model") or payload.get("modelVersion"),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning,
                    cached_input_tokens=cached,
                    total_tokens=total_tokens,
                    latency_ms=max(0.0, (time.time() - span.start_time) * 1000),
                    success=error is None,
                    error=type(error).__name__ if error is not None else None,
                    request_id=payload.get("id") or payload.get("request_id"),
                    agent_run_id=self.agent_run_id,
                    operation=span.name,
                    usage_source="reported" if available else "unavailable",
                )
            if span.type == SpanType.TOOL:
                tool = span.name.removeprefix("Tool: ")
                if error is not None:
                    self._add("tool_error", f"❌ {tool}: {error}", _TOOL_TEXT_CAP)
                else:
                    summary = _compact_outputs(outputs)
                    if summary:
                        self._add("tool_result", summary, _TOOL_RESULT_CAP)
            elif span.type == SpanType.LLM and error is None:
                text = _assistant_text(outputs)
                if text:
                    self._add("assistant", text, _ASSISTANT_TEXT_CAP)

    return _StepCollector()


def _reply(agent, message: str, rebuild, ctrl_q=None, *, deadline=None, message_id=None):
    """Returns (live_agent, reply, terminal_status).

    Hard interrupt can invoke `rebuild()` to swap agent_id and replay history (see META_SPEC.md).
    Empty reply / 502 equivalent to instance backoff retry. Graceful interrupt preserves same instance; hard interrupt triggers rebuild.
    """
    last = None
    agent._harness_termination_reason = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = _run_supervised(agent, message, ctrl_q, deadline=deadline, message_id=message_id)
            # Tool-type return result string
            text = out if isinstance(out, str) else (out[0] if out else "")
            if text and text.strip():
                outcome = getattr(agent, "_harness_outcome", None)
                status, reason = (
                    outcome.terminal() if outcome is not None else ("incomplete", "unavailable")
                )
                if status == "incomplete":
                    text = f"[incomplete: {reason}]\n" + text
                elif status == "crashed":
                    if _is_context_overflow(text):
                        agent._harness_termination_reason = "context_overflow"
                        return (
                            agent,
                            "[incomplete: context_overflow] The model rejected the context capacity.",
                            "incomplete",
                        )
                    text = "[harness error] " + text
                elif status == "interrupted":
                    text = _INTERRUPT_REPLY
                return agent, text, status
            last = "empty reply"  # Empty reply (gateway 200 + empty content does not throw) treated as failure, must not return silently
        except _BudgetExhausted as exhausted:
            if exhausted.rebuild:
                agent = rebuild(agent)
            agent._harness_termination_reason = exhausted.reason
            return (
                agent,
                f"[incomplete: {exhausted.reason}] Task activity stopped at its declared limit.",
                "incomplete",
            )
        # User interrupt: no retry, preserve or rebuild then return standard reply
        except _Interrupted as it:
            if it.rebuild:
                agent = rebuild(agent)
            return agent, _INTERRUPT_REPLY, "interrupted"
        # Gateway 502 etc. → same agent backoff retry (thread ended, lock released)
        except Exception as exc:
            last = exc
            if _is_context_overflow(exc):
                agent._harness_termination_reason = "context_overflow"
                observer.event("context_overflow", outer_attempt=attempt + 1, retry_suppressed=True)
                return (
                    agent,
                    "[incomplete: context_overflow] The model rejected the context capacity; partial work is retained.",
                    "incomplete",
                )
        if attempt < _RUN_RETRIES - 1:  # Last iteration skips sleep
            time.sleep(1.5 * (attempt + 1))
    return agent, f"[harness error] {last}", "crashed"


def _is_context_overflow(error) -> bool:
    """Classify deterministic capacity errors, not arbitrary task reply text."""
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "context window exceeded",
            "prompt is too long",
            "exceeds the context window",
            "max_model_len",
            "input tokens + max_tokens",
            "input tokens plus max_tokens",
        )
    )


class _TaskFrames:
    """Spec-0084/T3: anchor remaining time at enqueue, never at dequeue."""

    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.task_id = None
        self.declaration = None
        self.deadline = None
        self.message_ids = set()
        self.lock = threading.Lock()

    def accept(self, frame):
        now = self.clock()
        value = dict(frame)
        with self.lock:
            declared = "contract_id" in value
            if declared:
                required = {
                    "task_id",
                    "message_id",
                    "contract_id",
                    "followup_input",
                    "task_budget_seconds",
                    "remaining_budget_seconds",
                    "budget_source",
                }
                if not required <= value.keys():
                    raise ValueError("Incomplete execution conditions")
                if not isinstance(value["followup_input"], str) or value["followup_input"] not in {
                    "unavailable",
                    "possible",
                    "unknown",
                }:
                    raise ValueError("Invalid followup_input")
                for key in ("task_id", "message_id", "contract_id", "budget_source"):
                    if not isinstance(value[key], str) or not value[key].strip():
                        raise ValueError("Missing execution identity")
                declaration = tuple(
                    value[key]
                    for key in (
                        "contract_id",
                        "followup_input",
                        "task_budget_seconds",
                        "budget_source",
                    )
                )
                if self.declaration is not None and declaration != self.declaration:
                    raise ValueError("Execution declaration changed within a task")
            elif self.declaration is not None:
                raise ValueError("An active declared task cannot lose execution fields")
            for key in ("task_id", "message_id"):
                if key in value and (not isinstance(value[key], str) or not value[key].strip()):
                    raise ValueError("Invalid execution identity")
            task_id = value.get("task_id") or self.task_id or uuid.uuid4().hex
            message_id = value.get("message_id") or uuid.uuid4().hex
            if self.task_id is not None and task_id != self.task_id:
                raise ValueError("Unknown task identity")
            if message_id in self.message_ids:
                raise ValueError("Duplicate message identity")
            remaining = value.get("remaining_budget_seconds", value.get("budget_seconds"))
            budget = value.get("task_budget_seconds", value.get("budget_seconds"))
            for key, number in (("remaining budget", remaining), ("task budget", budget)):
                if number is not None and (
                    type(number) not in (int, float) or not math.isfinite(number) or number < 0
                ):
                    raise ValueError(f"Invalid {key}")
            if declared and (
                (remaining is None) != (budget is None)
                or (budget is not None and (budget <= 0 or remaining > budget))
            ):
                raise ValueError("Remaining budget does not match declared task budget")
            activity = value.get("message_activity_seconds")
            if activity is not None and (
                type(activity) not in (int, float) or not math.isfinite(activity) or activity <= 0
            ):
                raise ValueError("Invalid message activity limit")
            if _slash_command(value["text"]) is None and remaining is not None:
                deadline = now + remaining
                self.deadline = (
                    min(self.deadline, deadline) if self.deadline is not None else deadline
                )
            value.update(
                task_id=task_id,
                message_id=message_id,
                activity_deadline=now + activity if activity is not None else None,
            )
            if declared:
                self.declaration = declaration
            self.task_id = task_id
            self.message_ids.add(message_id)
        return value

    def limit(self, frame):
        with self.lock:
            candidates = [
                (limit, reason)
                for limit, reason in (
                    (self.deadline, "task_budget_exhausted"),
                    (frame.get("activity_deadline"), "message_activity_exhausted"),
                )
                if limit is not None
            ]
            return min(candidates) if candidates else (None, None)


def _bind_public_conditions(agent, frame):
    if not frame.get("contract_id"):
        return
    # System suffix is runtime context; the original user task text is unchanged.
    base = getattr(agent, "_harness_base_suffix", None)
    if base is None:
        base = agent.config.system_prompt_suffix or ""
        agent._harness_base_suffix = base
    agent.config.system_prompt_suffix = base + (
        "\n\nExecution conditions (trusted runtime declaration):\n"
        f"followup_input={frame['followup_input']}; task_budget_seconds={frame['task_budget_seconds']}; "
        f"remaining_budget_seconds_at_enqueue={frame['remaining_budget_seconds']}; budget_source={frame['budget_source']}.\n"
        "Follow-up input is optional and possible does not guarantee a reply. "
        "Pursue the stated goal autonomously within these conditions. Controls and follow-ups do not extend its deadline."
    )


_EOF = object()


def _stdin_reader(
    msg_q: queue.Queue, ctrl_q: queue.Queue, busy: threading.Event, frames=None
) -> None:
    frames = frames or _TaskFrames()
    for line in sys.stdin:
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        typ = obj.get("type")
        if typ == "shutdown":
            ctrl_q.put({"type": "interrupt"})
            msg_q.put(_EOF)
            return
        if typ == "interrupt":
            if obj.get("task_id") is not None and obj["task_id"] != frames.task_id:
                _emit_status("[ignored] Control belongs to an unknown task.")
                continue
            ctrl_q.put(obj)
        elif typ == "message" and isinstance(obj.get("text"), str):
            try:
                item = frames.accept(obj)
            except ValueError as exc:
                _emit_status(f"[rejected] {exc}")
                continue
            item["queued"] = busy.is_set()
            if item["queued"]:
                _emit_status(
                    "[queued] I am still working on the previous request; this message is queued."
                )
            msg_q.put(item)
    msg_q.put(_EOF)


def main() -> None:
    _setup_workspace()  # Prepare SANDBOX_WORK_DIR first for agent's local sandbox to read
    # Reuse same instance across turns / rebuilds, reset per turn
    collector = _make_step_collector()
    # Process-level session: session_id fixed; rebuild only swaps agent_id + replays history (see META_SPEC.md).
    session_id = f"harness_{uuid.uuid4().hex}"
    history_snapshot: list = []

    def rebuild(stale):
        nonlocal history_snapshot
        snap = _snapshot_history(stale) or history_snapshot
        history_snapshot = list(snap)
        fresh = _build_agent(
            collector,
            session_id,
            f"harness_{uuid.uuid4().hex[:8]}",
        )
        _restore_history(fresh, snap)
        observer.event("agent_rebuilt", restored_history_items=len(snap))
        return fresh

    agent = _build_agent(collector, session_id, "harness")
    msg_q: queue.Queue = queue.Queue()
    ctrl_q: queue.Queue = queue.Queue()
    busy = threading.Event()
    frames = _TaskFrames()
    threading.Thread(target=_stdin_reader, args=(msg_q, ctrl_q, busy, frames), daemon=True).start()
    while True:
        item = msg_q.get()
        if item is _EOF:  # stdin closed: normal shutdown and exit
            break
        if isinstance(item, dict):
            message = str(item.get("text") or "")
            was_queued = bool(item.get("queued"))
        else:
            message = str(item)
            was_queued = False
        # Drop previous-message controls, but keep an identified interrupt that
        # arrived after enqueue and before this message began execution.
        current_controls = []
        while not ctrl_q.empty():
            control = ctrl_q.get_nowait()
            if control.get("message_id") == item.get("message_id"):
                current_controls.append(control)
        for control in current_controls:
            ctrl_q.put(control)
        # Slash internal dispatch: /help returns reply and continues; /exit|/quit returns reply and ends process.
        slash = _slash_command(message)
        if slash is not None:
            slash_reply, should_exit = slash
            with _stdout_lock:
                sys.stdout.write(
                    json.dumps(
                        _wire_out(
                            "reply",
                            text=slash_reply,
                            kind="builtin_command",
                            status="acknowledged",
                            termination_reason="builtin_command",
                            task_id=item.get("task_id"),
                            message_id=item.get("message_id"),
                        ),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sys.stdout.flush()
            if should_exit:
                break
            continue
        if was_queued:
            preview = message.strip().splitlines()[0][:160] or "(empty message)"
            _emit_status(f"[status] Now handling queued message: {preview}")
        collector.reset()  # Collect only this turn's inner-loop events
        busy.set()
        try:
            _bind_public_conditions(agent, item)
            agent, raw, terminal_status = _reply(
                agent,
                message,
                rebuild,
                ctrl_q,
                deadline=lambda frame=item: frames.limit(frame),
                message_id=item.get("message_id"),
            )
        finally:
            busy.clear()
        history_snapshot = _snapshot_history(agent) or history_snapshot
        reply = _unwrap_reply(raw)  # Unpack envelope: user sees only final answer
        # Full inner-loop iteration → diagnostic metadata; user answer shows only reply
        steps = list(collector.steps)
        payload = _wire_out(
            "reply",
            text=reply,
            steps=steps,
            status=terminal_status,
            task_id=item.get("task_id"),
            message_id=item.get("message_id"),
        )
        outcome = getattr(agent, "_harness_outcome", None)
        if getattr(agent, "_harness_termination_reason", None):
            payload["termination_reason"] = agent._harness_termination_reason
        elif terminal_status == "interrupted":
            payload["termination_reason"] = "user_interrupted"
        elif terminal_status == "crashed":
            payload["termination_reason"] = (
                "error_occurred"
                if outcome and outcome.stop_reason == "error_occurred"
                else "retry_exhausted"
            )
        else:
            payload["termination_reason"] = (
                outcome.terminal()[1] if outcome is not None else "unavailable"
            )
        # Mutually exclusive with progress side-channel, ensures final state completes
        with _stdout_lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
