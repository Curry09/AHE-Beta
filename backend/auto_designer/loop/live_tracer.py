"""StepTracer：把 nexau agent 运行中的过程流成看板可见的结构化事件。

nexau 在每次工具执行时发 TOOL span（name="Tool: {tool_name}"，inputs.parameters=入参），
每次模型调用时发 LLM span（end 时 outputs=完整响应）。本 tracer 订阅两类 span，重建
「assistant 发言 → 工具调用 → 工具结果」的完整过程流，经 on_event(kind, text) 回调写进
live 注册表的 log 时间线——dev/designer 的黑盒 agent.run 由此变成逐步可观测：

- LLM end   → kind="assistant"：模型这一步说了什么（全文，宽上限）
- TOOL start → kind="tool"：🔧 工具名 + 入参摘要
- TOOL end   → kind="tool_result"：工具输出摘要；失败则 kind="tool_error"（❌）

依赖 nexau，调用方（designer/triage/owner 等 agent driver）须在运行期懒加载本模块。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from nexau import BaseTracer, Span, SpanType

# 各类事件文本长度上限：工具入参/输出可能携带整文件内容，摘要后进时间线；
# assistant 是过程流主体（要完整对话），给宽上限只防极端失控。
_TOOL_TEXT_CAP = 200
_TOOL_RESULT_CAP = 500
_ASSISTANT_TEXT_CAP = 20_000

EventFn = Callable[[str, str], None]  # (kind, text)


def _compact_params(params: dict[str, Any]) -> str:
    """入参摘要：shell 类工具直接给 command（最可读），其余压成单行 JSON 后截断。"""
    for key in ("command", "cmd"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        return json.dumps(params, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(params)


def _assistant_text(outputs: Any) -> str:
    """从 LLM span 的 outputs 里提取 assistant 文本。

    兼容三种真实形态（见 nexau llm_caller）：
    - 流式聚合 payload：{"role": "assistant", "content": "..."}
    - OpenAI 完整响应：{"choices": [{"message": {"content": "..."}}]}
    - Anthropic 响应/聚合：{"content": [{"type": "text", "text": "..."}, ...]}
    提取不到一律返回 ""（不吐事件），绝不抛错。
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
    """工具输出摘要：字符串原样、其余压 JSON，超长截断。"""
    if outputs is None:
        return ""
    if isinstance(outputs, str):
        return outputs.strip()
    try:
        return json.dumps(outputs, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(outputs)


class StepTracer(BaseTracer):
    """把 TOOL/LLM span 转成 on_event 过程流回调的 tracer（观测投影，出错静默不拖垮 agent）。"""

    def __init__(self, on_event: EventFn) -> None:
        self._on_event = on_event

    def _emit(self, *, kind: str, text: str, cap: int) -> None:
        try:
            self._on_event(kind, text[:cap])
        except Exception:  # noqa: BLE001  观测层失败不影响 agent 主流程
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
