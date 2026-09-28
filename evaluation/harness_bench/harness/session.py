"""Persistent subprocess session with non-blocking progress/heartbeat polling."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from .adapters import HarnessAdapter
from .protocol import (
    HarnessEvent,
    HarnessReply,
    ProtocolError,
    parse_terminal_kind,
)


class HarnessSession:
    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path,
        adapter: HarnessAdapter,
        env: Mapping[str, str] | None = None,
        transcript_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self.command = tuple(str(item) for item in command)
        self.cwd = Path(cwd)
        self.adapter = adapter
        self.env = dict(env) if env is not None else None
        self.transcript_path = Path(transcript_path) if transcript_path else None
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.process: subprocess.Popen[str] | None = None
        self._events: queue.Queue[HarnessEvent | BaseException | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr: TextIO | None = None
        self._transcript: TextIO | None = None
        self._write_lock = threading.Lock()
        self._pending_events: list[HarnessEvent] = []
        self._request_started: float | None = None
        self._request_id: str | None = None
        self.last_progress: list[dict[str, Any]] = []
        self.last_usage: list[dict[str, Any]] = []

    def start(self) -> HarnessSession:
        if self.process is not None:
            return self
        self.cwd.mkdir(parents=True, exist_ok=True)
        if self.transcript_path:
            self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
            self._transcript = self.transcript_path.open("a", encoding="utf-8", buffering=1)
        if self.stderr_path:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr = self.stderr_path.open("a", encoding="utf-8", buffering=1)
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr or subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        return self

    def _record(self, direction: str, payload: object) -> None:
        if self._transcript is not None:
            self._transcript.write(
                json.dumps(
                    {"timestamp": time.time(), "direction": direction, "payload": payload},
                    ensure_ascii=False,
                )
                + "\n"
            )

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for raw in self.process.stdout:
                line = raw.rstrip("\r\n")
                try:
                    payload = json.loads(line)
                    event = HarnessEvent.parse(payload)
                except (json.JSONDecodeError, ProtocolError) as exc:
                    self._record("harness-invalid", {"line": line, "error": str(exc)})
                    self._events.put(exc)
                    continue
                self._record("harness", payload)
                self._events.put(event)
        except BaseException as exc:
            self._events.put(exc)
        finally:
            self._events.put(None)

    def write_message(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("message must be non-empty")
        self.start()
        assert self.process is not None and self.process.stdin is not None
        if self.process.poll() is not None:
            raise ProtocolError(f"harness exited with code {self.process.returncode}")
        request_id = uuid.uuid4().hex
        frame = {"type": "message", "request_id": request_id, "text": text}
        with self._write_lock:
            self._record("controller", frame)
            try:
                self.process.stdin.write(json.dumps(frame, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise ProtocolError("could not write to harness stdin") from exc
        if self._request_started is None:
            self._request_started = time.monotonic()
            self._request_id = request_id
        return request_id

    def _consume(self, event: HarnessEvent) -> HarnessReply | None:
        self._pending_events.append(event)
        if event.type == "progress":
            self.last_progress.append(dict(event.payload))
            return None
        if event.type == "usage":
            self.last_usage.append(dict(event.payload))
            return None
        if event.type == "error":
            raise ProtocolError(f"harness error event: {event.payload}")
        if event.type != "reply":
            return None
        text = event.payload.get("text", "")
        if not isinstance(text, str):
            raise ProtocolError("reply text must be a string")
        started = self._request_started or time.monotonic()
        reply = HarnessReply(
            text=text,
            terminal_kind=parse_terminal_kind(
                event,
                declared_timeout_prefixes=self.adapter.timeout_prefixes,
                declared_interrupt_prefixes=self.adapter.interrupt_prefixes,
            ),
            events=tuple(self._pending_events),
            elapsed_seconds=time.monotonic() - started,
            request_id=event.request_id or self._request_id,
        )
        self._pending_events = []
        self._request_started = None
        self._request_id = None
        return reply

    def poll(self, timeout: float) -> tuple[str, HarnessReply | float]:
        if timeout <= 0:
            raise ValueError("poll timeout must be positive")
        started = time.monotonic()
        deadline = started + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timer", time.monotonic() - started
            try:
                item = self._events.get(timeout=remaining)
            except queue.Empty:
                return "timer", time.monotonic() - started
            if item is None:
                code = self.process.poll() if self.process is not None else None
                raise ProtocolError(f"harness stdout closed before reply (exit={code})")
            if isinstance(item, BaseException):
                if isinstance(item, ProtocolError):
                    raise item
                raise ProtocolError("harness stdout reader failed") from item
            reply = self._consume(item)
            if reply is not None:
                return "reply", reply

    def try_reply(self) -> HarnessReply | None:
        while True:
            try:
                item = self._events.get_nowait()
            except queue.Empty:
                return None
            if item is None:
                code = self.process.poll() if self.process is not None else None
                raise ProtocolError(f"harness stdout closed before reply (exit={code})")
            if isinstance(item, BaseException):
                raise ProtocolError("harness stdout reader failed") from item
            reply = self._consume(item)
            if reply is not None:
                return reply

    def interrupt(self, timeout: float = 30.0) -> HarnessReply | None:
        self.start()
        assert self.process is not None and self.process.stdin is not None
        frame = {"type": "control", "control": "interrupt"}
        with self._write_lock:
            self._record("controller", frame)
            self.process.stdin.write(json.dumps(frame) + "\n")
            self.process.stdin.flush()
        kind, value = self.poll(timeout)
        return value if kind == "reply" else None

    def shutdown(self, grace_seconds: float = 10.0) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None and process.stdin is not None and not process.stdin.closed:
            try:
                frame = {"type": "shutdown"}
                self._record("controller", frame)
                process.stdin.write(json.dumps(frame) + "\n")
                process.stdin.flush()
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=grace_seconds)
        if self._reader is not None:
            self._reader.join(timeout=1)
        if self._stderr is not None:
            self._stderr.close()
        if self._transcript is not None:
            self._transcript.close()
        self.process = None

    close = shutdown

    def __enter__(self) -> HarnessSession:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.shutdown()
