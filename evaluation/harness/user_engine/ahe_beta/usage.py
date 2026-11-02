"""Best-effort, per-call LLM usage telemetry.

Raw events are the source of truth.  Observability failures are deliberately
swallowed so accounting can never take down the closed loop.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UsageContext:
    run_id: str | None = None
    round_no: int | None = None
    session_id: str | None = None
    instance_id: str | None = None
    persona_id: str | None = None
    task_id: str | None = None
    task_digest: str | None = None
    task_kind: str | None = None
    interaction_mode: str | None = None
    slot: int | None = None
    harness_sha: str | None = None
    attempt: int | None = None
    interaction_id: str | None = None
    turn_no: int | None = None
    agent_id: str | None = None
    role: str | None = None
    operation: str | None = None


_context: contextvars.ContextVar[UsageContext | None] = contextvars.ContextVar(
    "llm_usage_context", default=None
)
_default_run_id = os.environ.get("AHE_BETA_RUN_ID") or uuid.uuid4().hex


@dataclass
class TimeAccounting:
    """Separate active execution time from model-provider wait time."""

    enabled: bool
    started: float
    _lock: threading.Lock
    _provider_depth: int = 0
    _provider_started: float | None = None
    _provider_wait_seconds: float = 0.0
    _tool_depth: int = 0
    _request_starts: dict[str, float] = field(default_factory=dict)
    _carried_wall_seconds: float = 0.0
    _carried_active_seconds: float = 0.0
    _finished: float | None = None

    @classmethod
    def create(cls, enabled: bool, restored: dict | None = None) -> TimeAccounting:
        saved = restored or {}
        return cls(
            enabled=enabled,
            started=time.monotonic(),
            _lock=threading.Lock(),
            _provider_wait_seconds=float(saved.get("provider_wait_ms", 0)) / 1000,
            _carried_wall_seconds=float(saved.get("wall_elapsed_ms", 0)) / 1000,
            _carried_active_seconds=float(saved.get("active_elapsed_ms", 0)) / 1000,
        )

    def _settle(self, now: float) -> None:
        if self._provider_started is not None:
            self._provider_wait_seconds += max(0.0, now - self._provider_started)
        self._provider_started = now if self._provider_depth and not self._tool_depth else None

    def tool_started(self) -> None:
        with self._lock:
            self._tool_depth += 1
            self._settle(time.monotonic())

    def tool_finished(self) -> None:
        with self._lock:
            self._tool_depth = max(0, self._tool_depth - 1)
            self._settle(time.monotonic())

    def finish(self) -> None:
        with self._lock:
            if self._finished is None:
                self._finished = time.monotonic()

    def request_started(self, call_id: str) -> None:
        self.provider_started()
        with self._lock:
            self._request_starts[call_id] = time.monotonic()

    def request_finished(self, call_id: str) -> None:
        with self._lock:
            existed = self._request_starts.pop(call_id, None)
        if existed is not None:
            self.provider_finished()

    def provider_started(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._provider_depth += 1
            self._settle(time.monotonic())

    def provider_finished(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._provider_depth <= 0:
                return
            self._provider_depth -= 1
            self._settle(time.monotonic())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            now = self._finished if self._finished is not None else time.monotonic()
            provider = self._provider_wait_seconds
            if self._provider_started is not None:
                provider += max(0.0, now - self._provider_started)
            wall = self._carried_wall_seconds + max(0.0, now - self.started)
            active = max(self._carried_active_seconds, wall - provider)
            return {
                "wall_elapsed_ms": round(wall * 1000, 3),
                "active_elapsed_ms": round(active * 1000, 3),
                "provider_wait_ms": round(provider * 1000, 3),
                "provider_active": self._provider_depth > 0,
                "provider_only_wait": self._provider_depth > 0 and not self._tool_depth,
                "oldest_request_ms": round(
                    max((now - start for start in self._request_starts.values()), default=0) * 1000,
                    3,
                ),
            }

    def active_seconds(self) -> float:
        return float(self.snapshot()["active_elapsed_ms"] or 0) / 1000

    def wall_seconds(self) -> float:
        return float(self.snapshot()["wall_elapsed_ms"] or 0) / 1000


_time_accounting: contextvars.ContextVar[TimeAccounting | None] = contextvars.ContextVar(
    "llm_time_accounting", default=None
)


@contextlib.contextmanager
def bind_time_accounting(
    *, enabled: bool, restored: dict | None = None
) -> Iterator[TimeAccounting]:
    state = TimeAccounting.create(enabled=enabled, restored=restored)
    token = _time_accounting.set(state)
    try:
        yield state
    finally:
        _time_accounting.reset(token)


def current_time_accounting() -> TimeAccounting | None:
    return _time_accounting.get()


@contextlib.contextmanager
def provider_wait_scope() -> Iterator[None]:
    state = current_time_accounting()
    if state is not None:
        state.provider_started()
    try:
        yield
    finally:
        if state is not None:
            state.provider_finished()


@contextlib.contextmanager
def bind_usage_context(**values: object) -> Iterator[UsageContext]:
    """Overlay request attribution; ContextVar keeps concurrent sessions isolated."""
    current = _context.get() or UsageContext()
    allowed = {k: v for k, v in values.items() if k in UsageContext.__dataclass_fields__}
    token = _context.set(replace(current, **allowed))
    try:
        yield _context.get()
    finally:
        _context.reset(token)


def current_usage_context() -> UsageContext:
    ctx = _context.get() or UsageContext()
    return ctx if ctx.run_id else replace(ctx, run_id=_default_run_id)


def set_usage_context(**values: object) -> UsageContext:
    """Update the current logical scope until its enclosing bind exits."""
    current = _context.get() or UsageContext()
    allowed = {k: v for k, v in values.items() if k in UsageContext.__dataclass_fields__}
    updated = replace(current, **allowed)
    _context.set(updated)
    return updated


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            out = dump()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    return {}


def usage_fields(raw: object) -> dict[str, int | None]:
    """Normalize OpenAI, Anthropic and NexAU usage without inventing values."""
    u = _mapping(raw)
    details = _mapping(u.get("completion_tokens_details") or u.get("output_tokens_details"))
    prompt_details = _mapping(u.get("prompt_tokens_details") or u.get("input_tokens_details"))

    def integer(*keys: str) -> int | None:
        for key in keys:
            value = u.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return None

    input_tokens = integer("prompt_tokens", "input_tokens")
    output_tokens = integer("completion_tokens", "output_tokens")
    total_tokens = integer("total_tokens")
    cached = integer("cached_input_tokens", "cache_read_tokens", "cache_read_input_tokens")
    if cached is None:
        value = prompt_details.get("cached_tokens")
        cached = int(value) if isinstance(value, (int, float)) else None
    reasoning = integer("reasoning_tokens")
    if reasoning is None:
        value = details.get("reasoning_tokens")
        reasoning = int(value) if isinstance(value, (int, float)) else None
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "cached_input_tokens": cached,
        "total_tokens": total_tokens,
    }


class UsageStore:
    _lock = threading.Lock()

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, event: Mapping[str, object]) -> None:
        try:
            line = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
        except Exception:
            pass

    def events(self, **filters: object) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if all(v is None or row.get(k) == v for k, v in filters.items()):
                        out.append(row)
        except OSError:
            return []
        return out

    def summary(self, **filters: object) -> dict[str, object]:
        events = self.events(**filters)
        fields = (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cached_input_tokens",
            "total_tokens",
        )
        totals = {metric: sum(e.get(metric) or 0 for e in events) for metric in fields}
        unavailable = sum(1 for e in events if e.get("usage_source") == "unavailable")
        groups: dict[str, dict[str, dict[str, int]]] = {
            "by_role": {},
            "by_agent": {},
            "by_session": {},
            "by_instance": {},
            "by_interaction": {},
        }
        for event in events:
            for group, key in (
                ("by_role", "role"),
                ("by_agent", "agent_id"),
                ("by_session", "session_id"),
                ("by_instance", "instance_id"),
                ("by_interaction", "interaction_id"),
            ):
                name = str(event.get(key) or "unknown")
                bucket = groups[group].setdefault(
                    name,
                    {
                        **{metric: 0 for metric in fields},
                        "event_count": 0,
                        "unavailable_count": 0,
                    },
                )
                bucket["event_count"] += 1
                if event.get("usage_source") == "unavailable":
                    bucket["unavailable_count"] += 1
                for metric in fields:
                    bucket[metric] += event.get(metric) or 0
        return {"event_count": len(events), "unavailable_count": unavailable, **totals, **groups}


def default_usage_store() -> UsageStore:
    configured = os.environ.get("AHE_BETA_USAGE_PATH", "").strip()
    path = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[1] / "data" / "usage.jsonl"
    )
    return UsageStore(path)


def record_usage(
    *,
    usage: object = None,
    provider: str | None = None,
    model: str | None = None,
    latency_ms: float | None = None,
    success: bool = True,
    error: object = None,
    request_id: str | None = None,
    operation: str | None = None,
) -> None:
    try:
        ctx = current_usage_context()
        fields = usage_fields(usage)
        available = any(value is not None for value in fields.values())
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            **asdict(ctx),
            "operation": operation or ctx.operation,
            "provider": provider,
            "model": model,
            **fields,
            "latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
            "success": success,
            "error": type(error).__name__ if error is not None else None,
            "request_id": request_id,
            "usage_source": "reported" if available else "unavailable",
        }
        accounting = current_time_accounting()
        if accounting is not None and accounting.enabled:
            event["time_accounting"] = accounting.snapshot()
        default_usage_store().append(event)
    except Exception:
        pass


def monotonic_ms() -> float:
    return time.monotonic() * 1000
