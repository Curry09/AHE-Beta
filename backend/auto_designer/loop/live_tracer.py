"""StepTracer：把 nexau agent 运行中的每个工具调用流成看板可见的步骤。

nexau 在每次工具执行时发 TOOL span（name="Tool: {tool_name}"，inputs.parameters=入参）。
本 tracer 只订阅 TOOL span：start 时吐一条「🔧 工具名: 入参摘要」，失败结束时补一条「❌ …」，
经 on_step 回调写进 live 注册表的 log 时间线——dev/designer 的黑盒 agent.run 由此变成逐步可观测。
LLM/AGENT span 不吐（噪声大；agent 最终报告已走 detail）。

依赖 nexau，调用方（agentic_developer/designer）须在运行期懒加载本模块。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from nexau import BaseTracer, Span, SpanType

# 单条步骤文本长度上限：工具入参可能携带整文件内容，摘要后进时间线。
_STEP_TEXT_CAP = 200

StepFn = Callable[[str], None]


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


class StepTracer(BaseTracer):
    """把 TOOL span 转成 on_step 步骤回调的 tracer（观测投影，出错静默不拖垮 agent）。"""

    def __init__(self, on_step: StepFn) -> None:
        self._on_step = on_step

    def _emit(self, *, text: str) -> None:
        try:
            self._on_step(text[:_STEP_TEXT_CAP])
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
            self._emit(text=f"🔧 {tool}: {summary}" if summary else f"🔧 {tool}")
        return span

    def end_span(
        self,
        span: Span,
        outputs: Any = None,
        error: Exception | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if span.type == SpanType.TOOL and error is not None:
            tool = span.name.removeprefix("Tool: ")
            self._emit(text=f"❌ {tool}: {error}")
