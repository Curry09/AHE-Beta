"""Persistent stdio-jsonl-v1 client for the frozen harness.

This module has no Harbor or tau2 imports so it can be used by both benchmark
stacks and unit-tested without installing either framework.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


class HarnessProtocolError(RuntimeError):
    """The harness exited or emitted an invalid terminal event."""


@dataclass(frozen=True)
class HarnessReply:
    text: str
    events: tuple[dict[str, Any], ...]
    elapsed_seconds: float


class HarnessStdioSession:
    """Own one persistent harness process and exchange complete user turns."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path,
        env: Mapping[str, str] | None = None,
        transcript_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self._command = [str(item) for item in command]
        self._cwd = Path(cwd)
        self._env = dict(env) if env is not None else None
        self._transcript_path = Path(transcript_path) if transcript_path else None
        self._stderr_path = Path(stderr_path) if stderr_path else None
        self._process: subprocess.Popen[str] | None = None
        self._events: queue.Queue[dict[str, Any] | BaseException | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._stderr_handle: TextIO | None = None
        self._transcript_handle: TextIO | None = None
        self._request_lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> HarnessStdioSession:
        if self._process is not None:
            return self
        self._cwd.mkdir(parents=True, exist_ok=True)
        if self._transcript_path:
            self._transcript_path.parent.mkdir(parents=True, exist_ok=True)
            self._transcript_handle = self._transcript_path.open("a", encoding="utf-8", buffering=1)
        if self._stderr_path:
            self._stderr_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_handle = self._stderr_path.open("a", encoding="utf-8", buffering=1)
        stderr: int | TextIO = self._stderr_handle or subprocess.DEVNULL
        self._process = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        return self

    def _record(self, direction: str, payload: Any) -> None:
        if self._transcript_handle is None:
            return
        row = {
            "timestamp": time.time(),
            "direction": direction,
            "payload": payload,
        }
        self._transcript_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            for raw in self._process.stdout:
                line = raw.rstrip("\r\n")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    self._record("harness-non-json", line)
                    continue
                if not isinstance(event, dict):
                    self._record("harness-non-object", event)
                    continue
                self._record("harness", event)
                self._events.put(event)
        except BaseException as exc:  # propagate reader failures to request()
            self._events.put(exc)
        finally:
            self._events.put(None)

    def request(self, text: str, *, timeout: float = 1800.0) -> HarnessReply:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("message text must be a non-empty string")
        with self._request_lock:
            self.start()
            assert self._process is not None and self._process.stdin is not None
            if self._process.poll() is not None:
                raise HarnessProtocolError(
                    f"harness already exited with code {self._process.returncode}"
                )
            request = {"type": "message", "text": text}
            self._record("controller", request)
            try:
                self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise HarnessProtocolError("could not write to harness stdin") from exc

            started = time.monotonic()
            deadline = started + timeout
            seen: list[dict[str, Any]] = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"harness did not reply within {timeout:.1f}s")
                try:
                    item = self._events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError(f"harness did not reply within {timeout:.1f}s") from exc
                if item is None:
                    code = self._process.poll()
                    raise HarnessProtocolError(f"harness stdout closed before reply (exit={code})")
                if isinstance(item, BaseException):
                    raise HarnessProtocolError("harness stdout reader failed") from item
                seen.append(item)
                event_type = item.get("type")
                # Usage frames legitimately carry ``"error": null``. Only a
                # v1 error frame or a non-empty legacy error payload is fatal.
                if event_type == "error" or (event_type is None and item.get("error") is not None):
                    raise HarnessProtocolError(f"harness error event: {item}")
                if event_type == "reply":
                    reply_text = item.get("text", "")
                elif "reply" in item:  # legacy protocol compatibility
                    reply_text = item.get("reply", "")
                else:
                    continue
                if not isinstance(reply_text, str):
                    raise HarnessProtocolError("reply text is not a string")
                return HarnessReply(
                    text=reply_text,
                    events=tuple(seen),
                    elapsed_seconds=time.monotonic() - started,
                )

    def close(self, *, grace_seconds: float = 10.0) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()  # EOF is the harness's clean shutdown signal.
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
        if self._stderr_handle is not None:
            self._stderr_handle.close()
        if self._transcript_handle is not None:
            self._transcript_handle.close()
        self._process = None

    def __enter__(self) -> HarnessStdioSession:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def harness_environment(
    *,
    work_dir: str | Path,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the minimal environment needed by frozen harness v0."""

    env = dict(parent if parent is not None else os.environ)
    env["SANDBOX_WORK_DIR"] = str(work_dir)
    env["HARNESS_STDIO_PROTOCOL"] = "stdio-jsonl-v1"
    env["PYTHONUNBUFFERED"] = "1"
    if model:
        env["LLM_MODEL"] = model
    if base_url:
        env["LLM_BASE_URL"] = base_url
    if api_key:
        env["LLM_API_KEY"] = api_key
    return env
