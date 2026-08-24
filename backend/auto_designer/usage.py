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
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UsageContext:
    run_id: str | None = None
    round_no: int | None = None
    session_id: str | None = None
    instance_id: str | None = None
    interaction_id: str | None = None
    turn_no: int | None = None
    agent_id: str | None = None
    role: str | None = None
    operation: str | None = None


_context: contextvars.ContextVar[UsageContext | None] = contextvars.ContextVar(
    "llm_usage_context", default=None
)
_default_run_id = os.environ.get("AUTO_DESIGNER_RUN_ID") or uuid.uuid4().hex


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
        fields = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens", "total_tokens")
        totals = {field: sum(e.get(field) or 0 for e in events) for field in fields}
        unavailable = sum(1 for e in events if e.get("usage_source") == "unavailable")
        groups: dict[str, dict[str, dict[str, int]]] = {
            "by_role": {}, "by_agent": {}, "by_session": {}, "by_instance": {},
            "by_interaction": {},
        }
        for event in events:
            for group, key in (
                ("by_role", "role"), ("by_agent", "agent_id"),
                ("by_session", "session_id"), ("by_instance", "instance_id"),
                ("by_interaction", "interaction_id"),
            ):
                name = str(event.get(key) or "unknown")
                bucket = groups[group].setdefault(
                    name,
                    {
                        **{field: 0 for field in fields},
                        "event_count": 0,
                        "unavailable_count": 0,
                    },
                )
                bucket["event_count"] += 1
                if event.get("usage_source") == "unavailable":
                    bucket["unavailable_count"] += 1
                for field in fields:
                    bucket[field] += event.get(field) or 0
        return {"event_count": len(events), "unavailable_count": unavailable, **totals, **groups}


def default_usage_store() -> UsageStore:
    configured = os.environ.get("AUTO_DESIGNER_USAGE_PATH", "").strip()
    path = Path(configured) if configured else Path(__file__).resolve().parents[1] / "data" / "usage.jsonl"
    return UsageStore(path)


def record_usage(
    *, usage: object = None, provider: str | None = None, model: str | None = None,
    latency_ms: float | None = None, success: bool = True, error: object = None,
    request_id: str | None = None, operation: str | None = None,
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
        default_usage_store().append(event)
    except Exception:
        pass


def monotonic_ms() -> float:
    return time.monotonic() * 1000
