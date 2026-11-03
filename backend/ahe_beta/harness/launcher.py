"""Launch a harness version as spec-0001's HarnessInterface (spec-0003/T1).

Check out the requested git ref under data/harness_runs/<ref>/, start the harness entry point
in a subprocess, and adapt its stdio JSONL interface to send/reset/close (Spec-0036):
  stdin: user messages use write_message; interrupt/shutdown use a separate control channel.
  stdout: progress/status and other side-channel events are recorded; type=reply wakes a poller
          without requiring a prior write flag.
Control names are opaque to the launcher; HELP.md defines the harness's capabilities.
Unknown side-channel fields are accepted. The harness's internal arrangement of one or more
nexau agents remains hidden behind this interface.
"""

from __future__ import annotations

import io
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from ahe_beta.harness.budget import (
    RequestLimits,
    TaskBudget,
    product_budget_environment,
    request_limits,
)
from ahe_beta.harness.interface import HarnessInterface
from ahe_beta.user.sim.runtime import (
    DockerWorkspaceRuntime,
    LocalWorkspaceRuntime,
    Workspace,
    as_runtime,
)

_PARAMS_FILE = "params.yaml"

# Spec-0084/T3: negotiated task deadlines are authoritative. The old bounded
# process fallback applies only when no task execution conditions were bound.
# Process death is detected separately, even when an orphan holds stdout open.
_POLL_INTERVAL = 5.0
_SEND_ABS_CAP = 1800.0
# Sentinel pushed to line queue on read thread EOF / process exit (distinct from actual stdout lines).
_EOF = object()
_SIDEBAND_PREVIEW_CAP = 500
_POST_REPLY_DRAIN_SEC = 0.2


def _sideband_preview(payload: dict) -> str:
    """Compress side-channel JSON into short text for control() return value and wait condition display."""
    status = payload.get("status")
    if isinstance(status, dict):
        bits: list[str] = []
        for key in ("phase", "elapsed", "completed", "can_continue", "note"):
            if key in status and status[key] is not None:
                bits.append(f"{key}={status[key]}")
        step = status.get("current_step") or (status.get("progress") or {}).get("last_step")
        if isinstance(step, dict) and step.get("text"):
            bits.append(f"step={step.get('text')}")
        if bits:
            return "; ".join(bits)[:_SIDEBAND_PREVIEW_CAP]
    try:
        return json.dumps(payload, ensure_ascii=False)[:_SIDEBAND_PREVIEW_CAP]
    except (TypeError, ValueError):
        return str(payload)[:_SIDEBAND_PREVIEW_CAP]


def _is_control_ack_sideband(payload: dict) -> bool:
    """Check whether an event acknowledges this control, excluding interleaved tool-progress events."""
    return payload.get("type") != "progress"


class _HarnessHandle:
    """Subprocess handle, implements HarnessInterface. One handle per subprocess per session."""

    def __init__(
        self,
        entry: list[str],
        cwd: Path,
        env: dict[str, str],
        help_text: str,
        workspace_runtime=None,
        limits: RequestLimits | None = None,
    ) -> None:
        self._entry = entry
        self._cwd = cwd
        self._env = {**os.environ, **env}
        self._limits = limits or request_limits(self._env, fallback=_SEND_ABS_CAP)
        self._env.update(product_budget_environment(self._limits))
        self._workspace_runtime = workspace_runtime
        self._proc: subprocess.Popen[str] | None = None
        self._closed = False
        # Help text (HELP.md) for this harness version: capability contract facing users;
        # callers form expectations about "what it can do / what it lacks" based on this. Empty string if file missing.
        self.help_text = help_text
        # Inner harness process flow from most recent send ({kind,text} sequence): observation side-channel beyond protocol reply;
        # persona consumes only send's returned reply, never sees steps. Callers read immediately after send via getattr.
        self.last_steps: list[dict] = []
        # Progress bar output emitted in this round (Codex-style activity summary): fed to user agent during heartbeat waits;
        # Shares origin with steps but is not equivalent to the complete process flow. Pure progress and other sidebands are mapped here as much as possible.
        self.last_progress: list[dict] = []
        # Raw text of all non-reply sidebands in this round (progress/status/others); control() uses it to determine whether sideband-type control has responded.
        self.last_sideband: list[dict] = []
        # This round's stdout user-visible event stream (reply/progress/status/error/ack, etc.), preserved in observation order;
        # Does not infer request/reply pairing, only records what harness stdout itself said.
        self.last_visible_events: list[dict] = []
        self.visible_events: list[dict] = []
        self._usage_events: list[dict] = []
        # Heartbeat/wait continuation: process-level read thread puts stdout lines into queue; poll drains within timeout—
        # sidebands accumulate, reply provides soft wake-up (Spec-0036; not bound to write path).
        self._line_q: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._t0 = 0.0
        # Soft state: whether we are still waiting for a reply since the last write_message (for interrupt/abs-cap/try_reply).
        # Does not constrain writes or poll (Spec-0036).
        self._awaiting_reply = False
        self._request_id = ""
        self._request_started_at = ""
        self._execution_contract: dict | None = None
        self._task_id = uuid.uuid4().hex
        self._task_budget = TaskBudget(self._limits.request_seconds)
        self._task_deadline_utc: str | None = None
        self._pending_requests: dict[str, dict] = {}
        self._deadline_interrupt_sent: float | None = None
        raw_activity = self._env.get("AHE_BETA_HARNESS_MESSAGE_ACTIVITY_SECONDS")
        self._message_activity_seconds = float(raw_activity) if raw_activity else None
        if self._message_activity_seconds is not None and (
            not math.isfinite(self._message_activity_seconds) or self._message_activity_seconds <= 0
        ):
            raise ValueError(
                "AHE_BETA_HARNESS_MESSAGE_ACTIVITY_SECONDS must be positive finite seconds"
            )
        self.request_outcomes: list[dict[str, Any]] = []
        # Structured terminal state of the most recent completed request. Caller must be able to distinguish normal reply from
        # "terminal reply with timeout/crash text"; cannot rely on parsing human-readable text to guess.
        self.last_request_status = ""
        self._start()

    @property
    def request_budget_seconds(self) -> float | None:
        """The configured fallback, or the bound task budget after contract binding."""
        return self._task_budget.seconds

    @property
    def in_flight(self) -> bool:
        """Backward compatibility alias: whether we are still waiting for a reply since the last message write (soft state, does not block writes/reads)."""
        return self._awaiting_reply

    def _record_visible_event(self, event_type: str, text: str, raw: dict) -> None:
        event = {
            "type": event_type,
            "text": str(text or ""),
            "source": "harness_stdout",
            "observed_at": datetime.now(UTC).isoformat(),
            "raw": dict(raw),
        }
        self.last_visible_events.append(event)
        self.visible_events.append(event)

    def drain_visible_events(self) -> list[dict]:
        """Retrieve new stdout events visible in this round; no interpretation or pairing, only return in observation order."""
        events = list(self.last_visible_events)
        self.last_visible_events.clear()
        return events

    def drain_usage_events(self) -> list[dict]:
        # close/interrupt may leave a final usage line in the reader queue without
        # another poll. Harvest only usage frames and put every other item back.
        deferred: list[object] = []
        while True:
            try:
                item = self._line_q.get_nowait()
            except queue.Empty:
                break
            if item is _EOF:
                deferred.append(item)
                continue
            try:
                payload = json.loads(str(item))
            except (json.JSONDecodeError, TypeError):
                deferred.append(item)
                continue
            if isinstance(payload, dict) and (payload.get("type") == "usage" or "usage" in payload):
                self._ingest_sideband(payload)
            else:
                deferred.append(item)
        for item in deferred:
            self._line_q.put(item)
        events = list(self._usage_events)
        self._usage_events.clear()
        return events

    def _start(self) -> None:
        # Command not found / entry crashed → Popen raises error, propagated by launch (with entry info).
        self._proc = subprocess.Popen(
            self._entry,
            cwd=str(self._cwd),
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,  # Independent process group: on timeout/close, child processes spawned by harness are also reaped
        )
        self._line_q = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        """Continuously readline from process lifetime → queue; emit _EOF after reaching end of file and exit.

        When closing stream/closing pipe, readline may raise ValueError(I/O on closed file) or OSError—treat as EOF,
        prevent daemon read thread from raising uncaught exception (aligned with origin/main's fallback for single-line read threads).
        """
        stdout = self._proc.stdout if self._proc is not None else None
        if stdout is None:
            self._line_q.put(_EOF)
            return
        while True:
            try:
                line = stdout.readline()
            except (ValueError, OSError):
                self._line_q.put(_EOF)
                return
            if line == "":
                self._line_q.put(_EOF)
                return
            self._line_q.put(line)

    def _kill_group(self, sig: int) -> None:
        """Send signal to the entire harness process group (including its nexau/sandbox child processes); ignore if process is dead."""
        if self._proc is None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _write(self, obj: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def bind_execution_contract(self, contract: dict) -> None:
        """Spec-0084/T3: bind once before the first goal; never renew on follow-ups."""
        from ahe_beta.execution_contract import validate_execution_contract

        declaration = validate_execution_contract(contract)
        if self._execution_contract == declaration:
            return
        if (
            self._execution_contract is not None
            or self._task_budget.started_at is not None
            or self._pending_requests
        ):
            raise ValueError("Execution contract cannot change after task binding or dispatch")
        self._execution_contract = declaration
        self._task_id = declaration["task_id"]
        seconds = declaration["task_budget_seconds"]
        self._task_budget = TaskBudget(seconds)
        self._limits = RequestLimits(
            seconds,
            seconds + self._limits.grace_seconds if seconds is not None else float("inf"),
            self._limits.grace_seconds,
        )

    def _message_frame(self, message: str, message_id: str) -> dict:
        frame = {
            "type": "message",
            "text": message,
            "task_id": self._task_id,
            "message_id": message_id,
        }
        if self._execution_contract is not None:
            frame.update(
                contract_id=self._execution_contract["contract_id"],
                followup_input=self._execution_contract["followup_input"],
                task_budget_seconds=self._task_budget.seconds,
                remaining_budget_seconds=self._task_budget.remaining(),
                task_deadline_utc=self._task_deadline_utc,
                budget_source=self._execution_contract["budget_source"],
            )
        elif self._limits.request_seconds is not None:
            frame["budget_seconds"] = self._task_budget.remaining()
        if self._message_activity_seconds is not None:
            frame["message_activity_seconds"] = self._message_activity_seconds
        return frame

    def _interrupt_frame(self) -> dict:
        return {"type": "interrupt", "task_id": self._task_id, "message_id": self._request_id}

    def _shutdown_frame(self) -> dict:
        return {"type": "shutdown"}

    def write_message(self, message: str) -> None:
        """Write a user message to harness stdin through the unified entry point (Spec-0036).

        Initial and interleaved messages use the same path. The harness decides whether to block or
        queue them. Multiple consecutive writes are allowed.
        """
        if self._closed or self._proc is None:
            raise RuntimeError("Harness handle is closed; send is unavailable")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self.last_request_status = ""
        command = message.strip().split(maxsplit=1)[0].lower() if message.strip() else ""
        builtin = command in {"/help", "/exit", "/quit"}
        if not builtin:
            self._task_budget.start()
            if self._task_budget.expired():
                raise RuntimeError("Task budget is exhausted; new solving messages are not allowed")
            if self._task_budget.seconds is not None and self._task_deadline_utc is None:
                from datetime import timedelta

                self._task_deadline_utc = (
                    datetime.now(UTC) + timedelta(seconds=self._task_budget.remaining())
                ).isoformat()
        message_id = uuid.uuid4().hex
        now = time.monotonic()
        self._pending_requests[message_id] = {
            "started_at": datetime.now(UTC).isoformat(),
            "started_monotonic": now,
            "builtin": builtin,
            "activity_deadline": now + self._message_activity_seconds
            if self._message_activity_seconds is not None and not builtin
            else None,
        }
        if not self._request_id:
            self._request_id = message_id
            self._request_started_at = self._pending_requests[message_id]["started_at"]
            self._t0 = now
        self._awaiting_reply = True
        self._write(self._message_frame(message, message_id))

    def _finish_request(
        self,
        status: str,
        *,
        origin: str = "harness_reply",
        reason: str = "",
        message_id: str | None = None,
    ) -> None:
        identifier = message_id or self._request_id
        if not identifier:
            return
        record = self._pending_requests.pop(identifier, {})
        self.last_request_status = status
        self.request_outcomes.append(
            {
                "request_id": identifier,
                "message_id": identifier,
                "task_id": self._task_id,
                "contract_id": self._execution_contract["contract_id"]
                if self._execution_contract
                else None,
                "status": status,
                "termination_source": origin,
                "termination_reason": reason,
                "started_at": record.get("started_at", self._request_started_at),
                "finished_at": datetime.now(UTC).isoformat(),
                "request_budget_seconds": self._task_budget.seconds,
                "task_deadline_utc": self._task_deadline_utc,
                "remaining_budget_seconds": self._task_budget.remaining(),
                "infrastructure_limit_seconds": self._limits.outer_seconds
                if self._limits.outer_seconds != float("inf")
                else None,
                "termination_grace_seconds": self._limits.grace_seconds,
            }
        )
        self._request_id = next(iter(self._pending_requests), "")
        following = self._pending_requests.get(self._request_id, {})
        self._request_started_at = following.get("started_at", "")
        self._t0 = following.get("started_monotonic", self._t0)
        self._awaiting_reply = bool(self._pending_requests)
        if status in {"timed_out", "crashed"} and self._workspace_runtime is not None:
            self._workspace_runtime.invalidate(f"harness request {status}")

    def _accept_reply(self, payload: dict) -> bool:
        """Consume only replies belonging to a dispatched message in this task."""
        identifier = payload.get("message_id")
        if (
            self._execution_contract is not None
            or identifier is not None
            or payload.get("task_id") is not None
        ):
            if (
                not isinstance(identifier, str)
                or payload.get("task_id") != self._task_id
                or identifier not in self._pending_requests
            ):
                self._ingest_sideband({**payload, "type": "unmatched_reply"})
                return False
        else:
            identifier = self._request_id
        record = self._pending_requests.get(identifier, {})
        status = payload.get("status")
        reason = payload.get("termination_reason")
        if payload.get("kind") == "builtin_command" and record.get("builtin"):
            status, reason = "builtin_command", "builtin_command"
        elif (
            not isinstance(status, str)
            or status not in {"completed", "incomplete", "interrupted", "crashed", "timed_out"}
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            status, reason = "incomplete", "protocol_invalid_terminal"
        self._finish_request(status, reason=reason, message_id=identifier)
        # Unbound manual clients have no negotiated identity contract. Their unknown
        # replies are readable, but never inferred to be successful task completion.
        if self._execution_contract is None and payload.get("message_id") is None:
            self._pending_requests.clear()
            self._request_id = ""
            self._awaiting_reply = False
        steps = payload.get("steps")
        self.last_steps = steps if isinstance(steps, list) else []
        self._record_visible_event("reply", str(payload.get("text", "")), payload)
        return True

    def _check_deadlines(self) -> None:
        if not self._awaiting_reply:
            return
        now = time.monotonic()
        task_deadline = self._task_budget.deadline
        activity = self._pending_requests.get(self._request_id, {}).get("activity_deadline")
        deadlines = [value for value in (task_deadline, activity) if value is not None]
        if deadlines:
            active_deadline = min(deadlines)
            if now >= active_deadline and self._deadline_interrupt_sent != active_deadline:
                self._write(
                    {
                        **self._interrupt_frame(),
                        "reason": "task_budget_exhausted"
                        if task_deadline == active_deadline
                        else "message_activity_exhausted",
                    }
                )
                self._deadline_interrupt_sent = active_deadline
            expired = now >= active_deadline + self._limits.grace_seconds
        else:
            expired = self._t0 > 0 and now - self._t0 >= self._limits.outer_seconds
        if expired:
            self._kill_group(signal.SIGKILL)
            self._finish_request(
                "timed_out", origin="infrastructure", reason="termination_grace_exhausted"
            )
            self._pending_requests.clear()
            self._awaiting_reply = False
            raise RuntimeError(
                "harness task exceeded its infrastructure deadline (termination grace exhausted)"
            )

    def begin(self, message: str) -> None:
        """Deprecated alias of write_message (Spec-0036)."""
        self.write_message(message)

    def emit_message(self, message: str) -> None:
        """Deprecated alias of write_message (Spec-0036)."""
        self.write_message(message)

    def _ingest_sideband(self, payload: dict) -> None:
        """Accept any non-reply sideband: raw text goes into last_sideband and is mapped to last_progress where possible for wait conditions."""
        if payload.get("type") == "usage":
            self._usage_events.append(dict(payload))
            return
        self.last_sideband.append(payload)
        event_type = str(payload["type"])
        event_text = ""
        if isinstance(payload.get("text"), str):
            event_text = str(payload.get("text") or "")
        if not event_text:
            event_text = _sideband_preview(payload)
        self._record_visible_event(event_type, event_text, payload)
        if payload.get("type") == "progress":
            text = payload.get("text")
            if isinstance(text, str) and text:
                self.last_progress.append(
                    {"kind": str(payload.get("kind") or "progress"), "text": text}
                )
                return
        kind = "status" if payload["type"] == "status" else "sideband"
        self.last_progress.append({"kind": kind, "text": _sideband_preview(payload)})

    def _post_reply_drain(self) -> None:
        """Briefly accept sideband events immediately following terminal reply; do not wait for next terminal reply."""
        deadline = time.monotonic() + _POST_REPLY_DRAIN_SEC
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                item = self._line_q.get(timeout=min(0.02, remaining))
            except queue.Empty:
                # The stdout reader may enqueue a frame shortly after the reply.
                # Keep the bounded grace period instead of treating the first
                # temporarily empty queue as proof that no sideband follows.
                continue
            if item is _EOF:
                self._line_q.put(item)
                return
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                self._line_q.put(line)
                return
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("type"), str)
                or not payload["type"]
            ):
                self._line_q.put(line)
                return
            if payload.get("type") in {"reply", "error"}:
                self._line_q.put(line)
                return
            self._ingest_sideband(payload)

    def poll(self, timeout: float) -> tuple[str, object]:
        """Wait up to timeout seconds for the next type=reply (soft wake-up, Spec-0036).

        No write-path flag is required. Return ("reply", text) or ("pending", waited_sec).
        Record progress/status and other side-channel events while continuing to wait. Raise if the
        process exits without leaving a complete line in the queue. On an explicit task deadline,
        cancel first and allow a separate period for collecting final output before forcing a stop.
        New messages do not extend the deadline.
        """
        if self._closed or self._proc is None:
            raise RuntimeError("Harness handle is closed; poll is unavailable")
        t_poll0 = time.monotonic()
        deadline = t_poll0 + max(0.0, timeout)
        while True:
            self._check_deadlines()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                base = self._t0 if self._awaiting_reply and self._t0 > 0 else t_poll0
                return ("pending", time.monotonic() - base)
            try:
                item = self._line_q.get(timeout=min(_POLL_INTERVAL, remaining))
            except queue.Empty:
                if self._proc is not None and self._proc.poll() is not None:
                    # Process has exited: if queue is empty and still waiting for reply, determine crash; otherwise treat as no more output.
                    if self._awaiting_reply:
                        self._kill_group(signal.SIGKILL)
                        self._awaiting_reply = False
                        self._finish_request("crashed", origin="transport")
                        raise RuntimeError(
                            "Harness subprocess exited without returning a complete line (crash or orphaned process holding the pipe)"
                        ) from None
                    return ("pending", time.monotonic() - t_poll0)
                continue
            if item is _EOF:
                self._awaiting_reply = False
                self._finish_request("crashed", origin="transport")
                raise RuntimeError("Harness subprocess exited (stdout EOF)")
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                self._awaiting_reply = False
                self._finish_request("crashed", origin="protocol")
                raise RuntimeError(f"Harness protocol violation: {line!r} ({exc})") from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("type"), str)
                or not payload["type"]
            ):
                self._awaiting_reply = False
                self._finish_request("crashed", origin="protocol")
                raise RuntimeError(
                    f"Harness protocol violation: expected an object containing type, got {line!r}"
                )
            if payload.get("type") == "error":
                self._awaiting_reply = False
                self._finish_request("crashed", origin="harness_error")
                msg = payload.get("message") or payload.get("text") or payload
                self._record_visible_event("error", str(msg), payload)
                raise RuntimeError(f"harness error: {msg}")
            if payload.get("type") == "reply":
                if not self._accept_reply(payload):
                    continue
                text = str(payload.get("text", ""))
                self._post_reply_drain()
                return ("reply", text)
            self._ingest_sideband(payload)
            continue

    def try_reply(self) -> str | None:
        """Non-blocking: retrieve reply if already in stdout buffer (soft wake-up, does not require write flag).

        Call after heartbeat decision but before executing action: reply arriving during LLM thinking should not be swallowed by give_up/interrupt.
        Sideband lines are consumed into last_progress as usual; return None if queue is empty.
        """
        if self._closed or self._proc is None:
            return None
        while True:
            try:
                item = self._line_q.get_nowait()
            except queue.Empty:
                return None
            if item is _EOF:
                self._awaiting_reply = False
                self._finish_request("crashed", origin="transport")
                raise RuntimeError("Harness subprocess exited (stdout EOF)")
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                self._awaiting_reply = False
                self._finish_request("crashed", origin="protocol")
                raise RuntimeError(f"Harness protocol violation: {line!r} ({exc})") from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("type"), str)
                or not payload["type"]
            ):
                self._awaiting_reply = False
                self._finish_request("crashed", origin="protocol")
                raise RuntimeError(
                    f"Harness protocol violation: expected an object containing type, got {line!r}"
                )
            if payload.get("type") == "error":
                self._awaiting_reply = False
                self._finish_request("crashed", origin="harness_error")
                msg = payload.get("message") or payload.get("text") or payload
                self._record_visible_event("error", str(msg), payload)
                raise RuntimeError(f"harness error: {msg}")
            if payload.get("type") == "reply":
                if not self._accept_reply(payload):
                    continue
                text = str(payload.get("text", ""))
                self._post_reply_drain()
                return text
            self._ingest_sideband(payload)

    def control(self, name: str) -> str:
        """External channel: send control to harness (user-side main path is interrupt ≈ Ctrl+C).

        - interrupt (and similar terminal types): ultimately emit reply, return reply text.
        - If harness still emits sidebands for other names: return sideband preview.
        Does not require write path flag (Spec-0036); process must still be open.
        """
        if self._closed or self._proc is None:
            raise RuntimeError("Harness handle is closed; control messages are unavailable")
        before = len(self.last_sideband)
        self._write(self._interrupt_frame() if name == "interrupt" else {"type": name})
        # Control acknowledges existing work; it never renews a task deadline.
        while True:
            kind, val = self.poll(_POLL_INTERVAL)
            if kind == "reply":
                return val  # type: ignore[return-value]
            for payload in self.last_sideband[before:]:
                if _is_control_ack_sideband(payload):
                    return _sideband_preview(payload)

    def send(self, message: str) -> str:
        """Blocking version: write_message + wait for next reply (Spec-0036)."""
        self.write_message(message)
        while True:
            kind, val = self.poll(min(self._limits.outer_seconds, 60.0))
            if kind == "reply":
                return val  # type: ignore[return-value]

    def reset(self) -> None:
        if self._closed:
            raise RuntimeError("Harness handle is closed; reset is unavailable")
        self._terminate()
        self._pending_requests.clear()
        self._request_id = ""
        self._start()  # Restarting entry = starting a new round (reset semantics contained on launcher side)

    def shutdown(self) -> None:
        """End process per human-facing interface; send shutdown first, then fall back to process group reaping."""
        if not self._closed and self._proc is not None and self._proc.stdin is not None:
            try:
                self._write(self._shutdown_frame())
            except (BrokenPipeError, OSError, AssertionError):
                pass
        self.close()

    def close(self) -> None:
        self._terminate()
        self._closed = True  # Idempotent

    def _terminate(self) -> None:
        self._awaiting_reply = False
        if self._proc is None:
            return
        if (
            getattr(getattr(self, "observation_source", None), "expected", False)
            and self._proc.poll() is None
        ):
            try:
                self._write(self._shutdown_frame())
                self._proc.wait(timeout=1)
            except (BrokenPipeError, OSError, AssertionError, subprocess.TimeoutExpired):
                pass  # Busy/crashed processes still follow the existing bounded kill path.
        # Order: kill entire group first → wait/fall back to SIGKILL → join read thread → then close streams, set _proc to None.
        # readline gets EOF only when all write ends of pipes are closed; therefore join is placed after SIGKILL fallback;
        # _read_loop already catches (ValueError, OSError). Reverse-closing the stream races with in-flight read threads for stdout.
        self._kill_group(signal.SIGTERM)
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(signal.SIGKILL)
            self._proc.kill()
        if self._reader is not None:
            self._reader.join(timeout=5)
            self._reader = None
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    pass
        self._proc = None


class HarnessLauncher:
    """Retrieve a harness version by ref and launch it; return a HarnessInterface handle."""

    def __init__(self, harness_repo: str, runs_root: str | Path = "data/harness_runs") -> None:
        self._harness_repo = harness_repo
        self._runs_root = Path(runs_root)
        # Spec-0017/T5: after parallel segment a, all sessions in the same round with identical SHA → same checkout destination. The _checkout
        # check-then-extract must be intra-process mutually exclusive (primary thread does work, others hit cache).
        self._checkout_lock = threading.Lock()
        from ahe_beta.observations.publication import framework_version

        self._observation_framework_pin = framework_version()

    def launch(self, ref: str, workspace_dir: Workspace | None = None) -> HarnessInterface:
        sha = self._resolve_sha(ref=ref)
        dest = self._checkout(ref=sha)
        params = self._read_params(dest)
        entry = params["entry"]
        if not isinstance(entry, list) or not entry:
            raise ValueError(f"params.yaml entry must be a non-empty argv list: {entry!r}")
        argv = [str(a) for a in entry]
        runtime = as_runtime(workspace_dir) if workspace_dir is not None else None
        is_docker = isinstance(runtime, DockerWorkspaceRuntime)
        if argv[0] in ("python", "python3"):
            # Spec-0069/T3: task shell Python and Harness/NexAU use separate environments.
            argv[0] = (
                str(runtime.evidence.get("harness_python") or "python3")
                if is_docker
                else sys.executable
            )
        cwd = dest / params["cwd"] if params.get("cwd") else dest
        env = {str(k): str(v) for k, v in (params.get("env") or {}).items()}
        if isinstance(runtime, LocalWorkspaceRuntime) and runtime.environment:
            # Spec-0073/T3: tools inherit this session's HOME/cache/attempt identity,
            # overriding Harness defaults without changing the controller environment.
            env.update(runtime.environment)
        if runtime is not None and not is_docker and runtime.evidence.get("task_virtual_env"):
            # Spec-0069/T3: E2B's task shell inherits its relocated environment,
            # while the entry uses the controller's absolute NexAU interpreter.
            task_venv = str(runtime.evidence["task_virtual_env"])
            env["VIRTUAL_ENV"] = task_venv
            shell_path = (
                runtime.environment.get("PATH", os.environ.get("PATH", ""))
                if isinstance(runtime, LocalWorkspaceRuntime) and runtime.environment
                else os.environ.get("PATH", "")
            )
            env["PATH"] = task_venv + "/bin" + os.pathsep + shell_path
            if argv[0] == sys.executable and runtime.evidence.get("harness_python"):
                argv[0] = str(runtime.evidence["harness_python"])
        protocol = params.get("protocol", "stdio-jsonl-v1")
        if protocol != "stdio-jsonl-v1" or "interface" in params:
            raise ValueError("params.yaml must use the typed JSON Lines protocol")
        # A frozen checkout may still default to untyped output. Always select
        # the one supported contract; the current Seed ignores this variable.
        env["HARNESS_STDIO_PROTOCOL"] = "stdio-jsonl-v1"
        if runtime is not None:
            # Spec-0008/T1 v2: share the same workspace with the user agent—inject it into harness's SANDBOX_WORK_DIR;
            # harness entry reads it and uses it as bash working root (no longer creates its own harness_ws_* tmp); overrides same-name key in params.yaml.
            env["SANDBOX_WORK_DIR"] = runtime.cwd
        if os.environ.get("HARNESS_LLM_MAX_CONTEXT_TOKENS"):
            env["LLM_MAX_CONTEXT_TOKENS"] = os.environ["HARNESS_LLM_MAX_CONTEXT_TOKENS"]
        limits = request_limits({**os.environ, **env}, fallback=_SEND_ABS_CAP)
        env.update(product_budget_environment(limits))
        host_cwd = cwd
        host_env = env
        from ahe_beta.observations.publication import ObservationSource

        observation_id = uuid.uuid4().hex
        if is_docker:
            observation_dir = f"/tmp/ahe-beta-observations/{observation_id}"
        else:
            observation_parent = self._runs_root.parent / "observation-staging"
            observation_parent.mkdir(parents=True, exist_ok=True)
            observation_dir = tempfile.mkdtemp(prefix="run-", dir=observation_parent.resolve())
        env["HARNESS_OBSERVATION_DIR"] = observation_dir
        source = ObservationSource(
            directory=observation_dir,
            container_id=runtime.container_id if is_docker else None,
            version={
                "harness_sha": sha,
                "image_digest": runtime.image_digest if is_docker else None,
                "observation_framework_sha256": self._observation_framework_pin,
            },
            expected=params.get("observations") == "artifact-observations-v1",
        )
        if is_docker and source.expected:
            # Validate the actual producer user's destination before any interaction.
            check = runtime._exec(["mkdir", "-p", observation_dir], timeout=10)
            if check.returncode != 0:
                raise OSError("harness observation directory preflight failed")
            runtime.evidence["observation"] = {"status": "collecting", "retain_source": True}
        if is_docker:
            container_root = f"/opt/ahe-beta/harness/{dest.name}"
            runtime.stage_directory(dest, container_root)
            relative_cwd = cwd.relative_to(dest)
            container_cwd = str(Path(container_root) / relative_cwd)
            inherited = {
                key: value
                for key, value in os.environ.items()
                if key.startswith(("LLM_", "NEXAU_", "AHE_BETA_"))
                or key in {"NO_PROXY", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY"}
            }
            child_environment = {**inherited, **env}
            proxy_environment = runtime.evidence.get("proxy_environment")
            if proxy_environment:
                # Spec-0069/T3: host NO_PROXY contains direct model gateways; it
                # must not bypass the owned egress proxy inside an internal network.
                for key in (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "NO_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "no_proxy",
                ):
                    child_environment.pop(key, None)
                child_environment.update(proxy_environment)
            argv = runtime.popen_argv(argv, cwd=container_cwd, env=child_environment)
            # Environment/workdir are encoded in docker exec argv.  The docker client
            # itself runs from the immutable host checkout and needs only host env.
            host_cwd = dest
            host_env = {}
        handle = _HarnessHandle(
            entry=argv,
            cwd=host_cwd,
            env=host_env,
            help_text=self._read_help_text(dest),
            workspace_runtime=runtime if is_docker else None,
            limits=limits,
        )
        handle.observation_source = source
        return handle

    @staticmethod
    def _read_help_text(dest: Path) -> str:
        """Read the help text (HELP.md) of this harness version; return empty string if missing."""
        help_path = dest / "HELP.md"
        if not help_path.is_file():
            return ""
        return help_path.read_text(encoding="utf-8", errors="replace")

    def _resolve_sha(self, *, ref: str) -> str:
        """Resolve a ref (branch/tag/SHA) to a definitive commit SHA; raise RuntimeError for invalid ref."""
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to resolve ref {ref!r}: {result.stderr.decode(errors='replace')[:200]}"
            )
        return result.stdout.decode().strip()

    def _checkout(self, *, ref: str) -> Path:
        # Cache by commit SHA, not ref name: branches like release can change content, and when they do, fall into new directory,
        # never reuse stale checkout (once caused running old entry.py and harness silently returning no reply).
        sha = self._resolve_sha(ref=ref)
        dest = self._runs_root / f"{ref.replace('/', '_')}-{sha[:12]}"
        # Spec-0017/T5: parallel sessions with same SHA to same dest must hold lock throughout check-then-extract—without lock, multiple threads
        # pass the existence check then concurrently extractall to the same directory, causing params.yaml to be overwritten by two tar streams with duplicate keys/garbled bytes;
        # and while A is mid-extraction, B misidentifies "non-empty directory" as complete cache and reuses it (hit this in production).
        with self._checkout_lock:
            if dest.is_dir() and any(dest.iterdir()):
                return dest  # same ref, same SHA (identical content) → safe to reuse
            result = subprocess.run(
                ["git", "-C", self._harness_repo, "archive", "--format=tar", sha],
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"checkout {ref!r}@{sha[:12]} failed: "
                    f"{result.stderr.decode(errors='replace')[:200]}"
                )
            # Extract to unique temp directory then atomically rename to claim the slot: partially-extracted directory can never exist under dest name—if process
            # crashes mid-operation, only harmless *.tmp* orphans remain (don't match any dest name, don't pollute cache); under cross-process concurrency, the loser's
            # rename fails (dest already fully in place by the winner) → discard its tmp, reuse dest.
            self._runs_root.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(dir=self._runs_root, prefix=dest.name + ".tmp"))
            try:
                with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tf:
                    tf.extractall(tmp, filter="data")
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            try:
                tmp.rename(dest)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
                if not (dest.is_dir() and any(dest.iterdir())):
                    raise  # not "someone else already in place" but a true failure: propagate the error as-is
            return dest

    def _read_params(self, dest: Path) -> dict[str, Any]:
        params_path = dest / _PARAMS_FILE
        if not params_path.is_file():
            raise FileNotFoundError(f"Harness is missing {_PARAMS_FILE}: {params_path}")
        # Spec-0017/T5: ruamel's YAML instance is not thread-safe (parser internal state shared across calls), parallel launch
        # sharing a module-level singleton can scramble concurrent loads → create a fresh instance per parse (construction overhead is negligible).
        return dict(YAML(typ="safe").load(params_path))
