"""Write bounded, metadata-only diagnostics owned by this harness version.

The platform supplies a directory, not tracer hooks. This module may evolve with
the harness; OBSERVABILITY.md documents the current event semantics.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path


class Observer:
    """Keep diagnostic I/O off the agent thread and bound queue and disk usage."""

    def __init__(self, directory: str | None = None, max_bytes: int = 4_000_000) -> None:
        self.process_id = uuid.uuid4().hex
        self.root = Path(directory or os.environ.get("HARNESS_OBSERVATION_DIR", ""))
        self.enabled = bool(directory or os.environ.get("HARNESS_OBSERVATION_DIR"))
        self.limit = max_bytes
        self.dropped = 0
        self.error = False
        self.closed = False
        self.queue: queue.Queue = queue.Queue(maxsize=512)
        self.worker = None
        if not self.enabled:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            existing = list(self.root.glob("runtime-*.jsonl"))
            # A restarted process shares the same session budget, not a fresh allowance.
            self.limit = min(
                self.limit, max(0, 12_000_000 - sum(p.stat().st_size for p in existing))
            )
            if len(existing) >= 120:
                raise ValueError("observation process budget exhausted")
            self.path = self.root / f"runtime-{self.process_id}.jsonl"
            self.path.touch(exist_ok=False)
            self.active = self.root / f".active-{self.process_id}"
            self.active.touch(exist_ok=False)
            (self.root / "READING.md").write_text(
                Path(__file__).with_name("OBSERVABILITY.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self._manifest()
            self.worker = threading.Thread(target=self._write, daemon=True)
            self.worker.start()
            self.event("process_started")
            atexit.register(self.close)
        except (OSError, ValueError):
            self.enabled = False
            self.error = True
            try:
                self._manifest()
            except (OSError, ValueError):
                pass

    def event(self, event: str, **metadata: object) -> None:
        """Enqueue metadata only; callers must never pass prompts or tool payloads."""
        if not self.enabled or self.closed:
            return
        row = {"at": time.time(), "process_id": self.process_id, "event": event, **metadata}
        try:
            # No arbitrary object serialization: a bad diagnostic cannot alter a run.
            line = json.dumps(row, ensure_ascii=False) + "\n"
            if len(line.encode()) > 4096:
                self.dropped += 1
                return
            self.queue.put_nowait(line)
        except (TypeError, ValueError, queue.Full):
            self.dropped += 1

    def _write(self) -> None:
        written = 0
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                while True:
                    line = self.queue.get()
                    try:
                        if line is None:
                            break
                        size = len(line.encode())
                        if written + size > self.limit:
                            self.dropped += 1
                            continue
                        stream.write(line)
                        stream.flush()
                        written += size
                    finally:
                        self.queue.task_done()
        except OSError:
            self.error = True

    def _manifest(self) -> None:
        files = ["READING.md", *sorted(p.name for p in self.root.glob("runtime-*.jsonl"))]
        value = {
            "format": "artifact-observations-v1",
            "reading": "READING.md",
            "status": "partial"
            if list(self.root.glob(".active-*")) or self.error or self.dropped
            else "complete",
            "files": [{"path": path} for path in files],
            "dropped_events": self.dropped,
        }
        temp = self.root / f".manifest-{self.process_id}.tmp"
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.root / "manifest.json")

    def close(self) -> None:
        if not self.enabled or self.closed:
            return
        self.event("process_stopped", dropped_events=self.dropped)
        self.closed = True
        try:
            self.queue.put(None, timeout=0.1)
            self.worker.join(timeout=1)
            if not self.worker.is_alive() and not self.error and not self.dropped:
                self.active.unlink(missing_ok=True)
            self._manifest()
        except (OSError, queue.Full):
            self.error = True


observer = Observer()
