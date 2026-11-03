"""StepTracer: transform nexau agent runtime process flow into structured events visible on the dashboard.

nexau emits a TOOL span on each tool execution (name="Tool: {tool_name}", inputs.parameters=input args),
and an LLM span on each model call (outputs=full response at end). This tracer subscribes to both span types,
reconstructing the complete process flow "assistant utterance → tool invocation → tool result", passing it via
on_event(kind, text) callback to write into the log timeline in the live registry—the black-box agent.run
of dev/architect thus becomes incrementally observable:

- LLM end   → kind="assistant": what the model said in this step (full text, high limit)
- TOOL start → kind="tool": 🔧 tool name + input summary
- TOOL end   → kind="tool_result": tool output summary; on failure kind="tool_error" (❌)

Depends on nexau; callers (architect/triage/owner agent drivers, etc.) must lazily load this module at runtime.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from nexau import BaseTracer, Span, SpanType

from ahe_beta.usage import (
    bind_usage_context,
    current_time_accounting,
    provider_wait_scope,
    record_usage,
)

# Length limits for event text: tool inputs/outputs may carry entire file contents, summarized into timeline;
# assistant is the main process flow (requires complete dialogue), given a high limit only against extreme runaway.
_TOOL_TEXT_CAP = 200
_TOOL_RESULT_CAP = 500
_ASSISTANT_TEXT_CAP = 20_000

EventFn = Callable[[str, str], None]  # (kind, text)


def _compact_params(params: dict[str, Any]) -> str:
    """Input summary: shell-class tools pass command directly (most readable), others compressed to single-line JSON then truncated."""
    for key in ("command", "cmd"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        return json.dumps(params, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(params)


def _assistant_text(outputs: Any) -> str:
    """Extract assistant text from LLM span outputs.

    Compatible with three real forms (see nexau llm_caller):
    - streamed aggregated payload: {"role": "assistant", "content": "..."}
    - OpenAI complete response: {"choices": [{"message": {"content": "..."}}]}
    - Anthropic response/aggregate: {"content": [{"type": "text", "text": "..."}, ...]}
    Return "" if extraction fails (suppress event), never raise.
    """
    if not isinstance(outputs, dict):
        return ""
    content = outputs.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):  # Anthropic content blocks
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    choices = outputs.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        msg = choices[0].get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"].strip()
    return ""


def _compact_outputs(outputs: Any) -> str:
    """Tool output summary: strings unchanged, others compressed to JSON, truncated if too long."""
    if outputs is None:
        return ""
    if isinstance(outputs, str):
        return outputs.strip()
    try:
        return json.dumps(outputs, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(outputs)


class StepTracer(BaseTracer):
    """Transform TOOL/LLM spans into on_event process flow callback tracer (observation projection, fail silently without breaking agent)."""

    def __init__(self, on_event: EventFn) -> None:
        self._on_event = on_event
        self._agent_id: str | None = None
        self._provider_scopes: dict[int, object] = {}

    def set_session_id(self, session_id: str) -> None:
        # NexAU creates one canonical session per Agent instance; use it as the
        # stable execution-level agent identifier when the orchestrator has no id.
        self._agent_id = session_id

    def _emit(self, *, kind: str, text: str, cap: int) -> None:
        try:
            self._on_event(kind, text[:cap])
        except Exception:  # noqa: BLE001  observation layer failure does not affect agent main flow
            pass

    def start_span(
        self,
        name: str,
        span_type: SpanType,
        inputs: dict[str, Any] | None = None,
        parent_span: Span | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        span = Span(id="", name=name, type=span_type)
        if span_type == SpanType.LLM and current_time_accounting() is not None:
            scope = provider_wait_scope()
            scope.__enter__()
            self._provider_scopes[id(span)] = scope
        if span_type == SpanType.TOOL:
            tool = name.removeprefix("Tool: ")
            params = (inputs or {}).get("parameters") or {}
            summary = _compact_params(params) if isinstance(params, dict) else str(params)
            self._emit(
                kind="tool",
                text=f"🔧 {tool}: {summary}" if summary else f"🔧 {tool}",
                cap=_TOOL_TEXT_CAP,
            )
        return span

    def end_span(
        self,
        span: Span,
        outputs: Any = None,
        error: Exception | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        scope = self._provider_scopes.pop(id(span), None)
        if scope is not None:
            scope.__exit__(None, None, None)
        if span.type == SpanType.LLM:
            payload = outputs if isinstance(outputs, dict) else {}
            usage = payload.get("usage") or payload.get("usageMetadata")
            with bind_usage_context(agent_id=self._agent_id):
                record_usage(
                    usage=usage,
                    provider="nexau",
                    model=payload.get("model") or payload.get("modelVersion"),
                    latency_ms=max(0.0, (time.time() - span.start_time) * 1000),
                    success=error is None,
                    error=error,
                    request_id=payload.get("id") or payload.get("request_id"),
                    operation=span.name,
                )
        if span.type == SpanType.TOOL:
            tool = span.name.removeprefix("Tool: ")
            if error is not None:
                self._emit(kind="tool_error", text=f"❌ {tool}: {error}", cap=_TOOL_TEXT_CAP)
            else:
                summary = _compact_outputs(outputs)
                if summary:
                    self._emit(kind="tool_result", text=summary, cap=_TOOL_RESULT_CAP)
        elif span.type == SpanType.LLM and error is None:
            text = _assistant_text(outputs)
            if text:
                self._emit(kind="assistant", text=text, cap=_ASSISTANT_TEXT_CAP)
