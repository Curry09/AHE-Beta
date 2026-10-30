"""Terminal coding assistant runtime.

The process reads one JSON object per line from stdin and writes JSON objects to stdout.
It builds a NexAU Agent from this directory's agent.yaml and uses SANDBOX_WORK_DIR as
the workspace for shell commands. The internal agent topology is an implementation detail.

Project guidance: LLM_* environment variables configure the model endpoint. The process keeps
with a stable session_id; a hard interrupt recovery may rebuild the internal agent_id
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
# 空回复 / 网关毛刺用 _RUN_RETRIES 退避重试（同实例，不换 session）。
# Spec-0084/T3: an explicit task deadline bounds all attempts; unknown means undeclared.
_RUN_RETRIES = 4
# 打断（type:interrupt）后等待 nexau 优雅停止（保留 session/history）的宽限秒数：
# executor.force_stop() 只置位中断信号，run 会在下一个检查点安全退出。超过宽限仍没退，
# 说明这次没赶上优雅停止 → 换新 agent_id 重建避自锁，并显式回灌 history。
_INTERRUPT_GRACE = 15.0
# 打断时回给用户的定型回复：明确"已中止、未完成、会话上下文保留"，让用户据此决定下一步。
_INTERRUPT_REPLY = (
    "[interrupted] 已按你的要求停止当前处理，这一步没有完成。"
    "会话上下文已保留——你可以直接给出修改后的要求或下一条指示，我会接着当前进度继续。"
)
_HARNESS_USER_ID = "harness_user"

# 内部分发：message 首词匹配 slash（如 /help /exit /quit）；其余走 agent。
_HELP_PATH = _HERE / "HELP.md"
_EXIT_COMMANDS = frozenset({"/exit", "/quit"})
_EXIT_REPLY = (
    "[exited] Session closed at your request. Send a new message in a new session to start again."
)


class _Interrupted(Exception):
    """收到用户打断：中止当前这轮 agent.run。rebuild=True 表示没赶上优雅停止、需重建 agent 避自锁。"""

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
    """按 message 正文识别内置 slash 功能；返回 (reply, should_exit) 或 None。

    功能识别在 harness 内部、通道仍是 message。仅认首词精确匹配（大小写不敏感）。
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
    """线程安全地请求 nexau 优雅停止当前 run（置 stop_signal + shutdown_event，保留 history）。

    成功置位返回 True；nexau 版本不含该原语或置位失败返回 False（调用方回退到重建 agent）。"""
    try:
        executor = getattr(agent, "executor", None)
        if executor is not None and hasattr(executor, "force_stop"):
            executor.force_stop()
            return True
    except Exception:  # noqa: BLE001  打断是尽力而为，失败绝不炸 harness
        pass
    return False


# 内层过程流各类文本上限：工具入参/输出可能带整文件内容，摘要后进时间线；
# assistant 是过程主体，给宽上限只防极端失控。
_TOOL_TEXT_CAP = 200
_TOOL_RESULT_CAP = 500
_ASSISTANT_TEXT_CAP = 20_000
# stdout 写锁：tracer 线程吐 progress、主线程吐终态 reply，必须互斥防行交错。
_stdout_lock = threading.Lock()


def _wire_out(event_type: str, **payload) -> dict:
    """Encode a process event as one typed JSON object."""
    return {"type": event_type, **payload}


def _emit_progress(*, kind: str, text: str) -> None:
    """向用户侧吐一条 Codex 式活动摘要（终态 reply 之前的旁路行）。

    只发 tool / tool_error——短、可扫；assistant 全文不进进度条（那是内部诊断流）。
    失败一律静默：进度丢了不该拖垮 agent。
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
    """向用户侧吐 harness 自身的可见状态；只描述正在做什么，不做 request/reply 配对。"""
    try:
        line = json.dumps(_wire_out("status", text=text), ensure_ascii=False)
        with _stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass


def _emit_usage(**payload) -> None:
    """逐调用机器观测旁路；绝不携带 prompt/response 正文。"""
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
    """每会话建一个干净工作区作 bash 的「项目根目录」，写入 SANDBOX_WORK_DIR（nexau local sandbox 读它）。"""
    ws = os.environ.get("SANDBOX_WORK_DIR")
    if not ws:
        ws = tempfile.mkdtemp(prefix="harness_ws_")
        os.environ["SANDBOX_WORK_DIR"] = ws
    return ws


def _snapshot_history(agent) -> list:
    """从 live agent 取出可回灌的 history 快照；失败则空列表（rebuild 仍换锁，只是无记忆可接）。"""
    try:
        hist = getattr(agent, "history", None)
        if hist is None:
            return []
        return list(hist)
    except Exception:  # noqa: BLE001  快照失败不得挡住 rebuild 避锁
        return []


def _restore_history(agent, messages) -> None:
    """把快照种进新 agent，使下一轮 run 带着旧上下文（换了 agent_id 后存储 key 不同，必须显式回灌）。"""
    if not messages:
        return
    try:
        agent.history = list(messages)
    except Exception:  # noqa: BLE001  回灌失败不炸进程；表现为记忆缺口，由上层体感暴露
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
    """按本目录 agent.yaml 构造工具型 nexau Agent（只挂 bash + complete_task）。

    session_id 进程内固定；agent_id 标识锁键——rebuild 时必须换新 agent_id 避自锁。
    挂 collector 作 tracer：内层每步收进 collector.steps，经协议 steps 提供给调用方。
    """
    from nexau import Agent, AgentConfig
    from nexau.archs.main_sub.execution.hooks import MiddlewareManager

    cfg = AgentConfig.from_yaml(config_path=_HERE / "agent.yaml")
    if raw_limit := os.environ.get("LLM_MAX_CONTEXT_TOKENS"):
        input_limit = int(raw_limit)
        if input_limit <= 0:
            raise ValueError("LLM_MAX_CONTEXT_TOKENS must be positive")
        cfg.max_context_tokens = input_limit
    cfg.resolved_tracer = collector  # 内层过程流 → collector.steps（诊断用，不影响回复）
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
    """拆 complete_task 信封 → 给用户看的最终答案。

    工具型 agent 收尾常把整个信封（{"success":…, "status":"TASK_COMPLETED",
    "output":{"result":…}}）当字符串返回，甚至双层 JSON 编码。用户只该看 result 本身，
    不是协议元数据。至多解两层，取 output.result（或顶层 result）；非信封/解不出则原样返回。
    """
    s: object = text
    for _ in range(2):  # 至多双层解码
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
            break  # 是 dict 但不含 result：保底原文
        s = dec  # 解出来仍是 str（双层编码），再解一层
    return text


def _make_step_collector():
    """构造把 nexau span 收成 {kind,text} 过程流的 tracer（自包含，只依赖 nexau）。

    LLM end→assistant，TOOL start→tool，TOOL end→tool_result/tool_error。每次
    agent.run 前 reset()，run 后读 steps —— 即该轮 harness 内层迭代的完整过程；
    经协议 steps 字段提供给调用方。用户可见答案仍只来自 reply。
    收集失败一律静默，绝不拖垮 agent 主流程。
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
                    _emit_progress(kind=kind, text=t)  # 等待中可见的活动条（旁路）
            except Exception:  # noqa: BLE001  诊断流失败不影响 agent
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
    """返回 (live_agent, reply, terminal_status)。

    hard interrupt 可调用 `rebuild()` 换新 agent_id 并回灌 history（见 META_SPEC.md）。
    空回复 / 502 等同实例退避重试。优雅打断保持同实例；强打断才 rebuild。
    """
    last = None
    agent._harness_termination_reason = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = _run_supervised(agent, message, ctrl_q, deadline=deadline, message_id=message_id)
            text = out if isinstance(out, str) else (out[0] if out else "")  # 工具型返回 result 串
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
            last = "empty reply"  # 空回复（网关 200+空内容不抛异常）视为失败，不得静默返回
        except _BudgetExhausted as exhausted:
            if exhausted.rebuild:
                agent = rebuild(agent)
            agent._harness_termination_reason = exhausted.reason
            return (
                agent,
                f"[incomplete: {exhausted.reason}] Task activity stopped at its declared limit.",
                "incomplete",
            )
        except _Interrupted as it:  # 用户打断：不重试，保留/重建后回定型回复
            if it.rebuild:
                agent = rebuild(agent)
            return agent, _INTERRUPT_REPLY, "interrupted"
        except Exception as exc:  # 网关 502 等 → 同 agent 退避重试（线程已结束、锁已释放）
            last = exc
            if _is_context_overflow(exc):
                agent._harness_termination_reason = "context_overflow"
                observer.event("context_overflow", outer_attempt=attempt + 1, retry_suppressed=True)
                return (
                    agent,
                    "[incomplete: context_overflow] The model rejected the context capacity; partial work is retained.",
                    "incomplete",
                )
        if attempt < _RUN_RETRIES - 1:  # 末次不再睡
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
    _setup_workspace()  # 先就位 SANDBOX_WORK_DIR，供 agent 的 local sandbox 读取
    collector = _make_step_collector()  # 跨轮/跨重建复用同一实例，逐轮 reset
    # 进程级会话：session_id 固定；rebuild 只换 agent_id + 回灌 history（见 META_SPEC.md）。
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
        if item is _EOF:  # stdin 关闭：正常收尾退出
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
        # slash 内部分发：/help 回 reply 后继续；/exit|/quit 回 reply 后结束进程。
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
        collector.reset()  # 只收本轮内层过程
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
        reply = _unwrap_reply(raw)  # 拆信封：用户只看最终答案
        steps = list(collector.steps)  # 完整内层迭代 → 诊断元数据；用户答案只看 reply
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
        with _stdout_lock:  # 与 progress 旁路互斥，保证终态行完整
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
