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
import os
import queue
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# 空回复 / 网关毛刺用 _RUN_RETRIES 退避重试（同实例，不换 session）。
# agent.run 没有整轮墙钟上限；慢任务由外层 90s persona 心跳观测并决定续等/打断。
_RUN_RETRIES = 4
# 打断（control:interrupt）后等待 nexau 优雅停止（保留 session/history）的宽限秒数：
# executor.force_stop() 只置位中断信号，run 会在下一个检查点安全退出。超过宽限仍没退，
# 说明这次没赶上优雅停止 → 换新 agent_id 重建避自锁，并显式回灌 history。
_INTERRUPT_GRACE = 15.0
# 打断时回给用户的定型回复：明确"已中止、未完成、会话上下文保留"，让用户据此决定下一步。
_INTERRUPT_REPLY = (
    "[interrupted] 已按你的要求停止当前处理，这一步没有完成。"
    "会话上下文已保留——你可以直接给出修改后的要求或下一条指示，我会接着当前进度继续。"
)
_HARNESS_USER_ID = "harness_user"
_V1 = "stdio-jsonl-v1"
_OUTPUT_PROTOCOL = os.environ.get("HARNESS_STDIO_PROTOCOL", "legacy")

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
    """输出帧：目标 stdio-jsonl-v1 或 legacy wire。"""
    if _OUTPUT_PROTOCOL == _V1:
        return {"type": event_type, **payload}
    if event_type == "progress":
        return {"progress": {"kind": payload.get("kind"), "text": payload.get("text")}}
    if event_type == "reply":
        out = {"reply": payload.get("text", "")}
        if payload.get("steps"):
            out["steps"] = payload["steps"]
        return out
    if event_type == "error":
        return {"error": payload}
    return {event_type: payload}


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


def _run_supervised(agent, message, ctrl_q):
    """跑一次 agent.run，同时守望用户打断（control 队列）。

    - 正常完成：返回结果。
    - 收到 interrupt：force_stop 优雅停止（保留 session）→ raise _Interrupted(rebuild=False)；
      若宽限内没停下 → _Interrupted(rebuild=True)，由 caller 重建避自锁并回灌 history。
    工作线程只是为了让主线程持续处理 interrupt，不再用 deadline 放弃正在运行的请求。
    ctrl_q 为 None 时等到 agent.run 自身返回。"""
    box: dict = {}

    def target():
        try:
            box["out"] = agent.run(message=message)
        except Exception as exc:  # noqa: BLE001  透传给调用方判定/重试
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    while t.is_alive():
        # 小步轮询只为及时响应打断；长任务由 persona 心跳决定是否续等。
        t.join(0.5)
        if not t.is_alive():
            break
        if ctrl_q is not None:
            try:
                ctrl = ctrl_q.get_nowait()
            except queue.Empty:
                ctrl = None
            if isinstance(ctrl, dict) and ctrl.get("control") == "interrupt":
                stopped = _force_stop(agent)
                if stopped:
                    t.join(_INTERRUPT_GRACE)  # 等它在下一个检查点优雅退出
                raise _Interrupted(rebuild=not stopped or t.is_alive())
    if "err" in box:
        raise box["err"]
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


def _build_agent(collector, session_id, agent_id):
    """按本目录 agent.yaml 构造工具型 nexau Agent（只挂 bash + complete_task）。

    session_id 进程内固定；agent_id 标识锁键——rebuild 时必须换新 agent_id 避自锁。
    挂 collector 作 tracer：内层每步收进 collector.steps，经协议 steps 提供给调用方。
    """
    from nexau import Agent, AgentConfig

    cfg = AgentConfig.from_yaml(config_path=_HERE / "agent.yaml")
    cfg.resolved_tracer = collector  # 内层过程流 → collector.steps（诊断用，不影响回复）
    return Agent(
        config=cfg,
        session_id=session_id,
        agent_id=agent_id,
        user_id=_HARNESS_USER_ID,
    )


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
            span = Span(id="", name=name, type=span_type)
            if span_type == SpanType.TOOL:
                tool = name.removeprefix("Tool: ")
                params = (inputs or {}).get("parameters") or {}
                summary = _compact_params(params) if isinstance(params, dict) else str(params)
                self._add(
                    "tool", f"🔧 {tool}: {summary}" if summary else f"🔧 {tool}", _TOOL_TEXT_CAP
                )
            return span

        def end_span(self, span, outputs=None, error=None, attributes=None):
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


def _reply(agent, message: str, rebuild, ctrl_q=None):
    """返回 (live_agent, reply, terminal_status)。

    hard interrupt 可调用 `rebuild()` 换新 agent_id 并回灌 history（见 META_SPEC.md）。
    空回复 / 502 等同实例退避重试。优雅打断保持同实例；强打断才 rebuild。
    """
    last = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = _run_supervised(agent, message, ctrl_q)  # 无整轮超时，但可由 persona 打断
            text = out if isinstance(out, str) else (out[0] if out else "")  # 工具型返回 result 串
            if text and text.strip():  # 非空才算成功
                return agent, text, "completed"
            last = "empty reply"  # 空回复（网关 200+空内容不抛异常）视为失败，不得静默返回
        except _Interrupted as it:  # 用户打断：不重试，保留/重建后回定型回复
            if it.rebuild:
                agent = rebuild(agent)
            return agent, _INTERRUPT_REPLY, "interrupted"
        except Exception as exc:  # 网关 502 等 → 同 agent 退避重试（线程已结束、锁已释放）
            last = exc
        if attempt < _RUN_RETRIES - 1:  # 末次不再睡
            time.sleep(1.5 * (attempt + 1))
    return agent, f"[harness error] {last}", "crashed"


_EOF = object()  # stdin 读线程读到 EOF 时投递的哨兵


def _stdin_reader(msg_q: queue.Queue, ctrl_q: queue.Queue, busy: threading.Event) -> None:
    """后台逐行读 stdin，按类型分发：{"message":..} → msg_q，{"control":..} → ctrl_q。

    独立线程读，才能在某轮 agent.run 阻塞进行中仍收到 {"control":"interrupt"} 并即时打断
    （主线程正忙于该轮、无法自己读 stdin）。busy 时收到新 message 会先输出 queued 状态，
    让用户知道输入没有被静默吞掉，而是等待当前处理结束后进入队列。非法行/无 message 的行静默跳过；EOF 投 _EOF 收尾。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        typ = obj.get("type")
        if typ == "shutdown":
            msg_q.put(_EOF)
            return
        if typ == "interrupt":
            ctrl_q.put({"control": "interrupt"})
        elif typ == "message" and isinstance(obj.get("text"), str):
            was_queued = busy.is_set()
            if was_queued:
                _emit_status(
                    "[queued] I am still working on the previous request; "
                    "this message has been queued and will be handled after the current response."
                )
            msg_q.put({"text": obj["text"], "queued": was_queued})
        elif "control" in obj:
            ctrl_q.put(obj)
        elif "message" in obj:
            was_queued = busy.is_set()
            if was_queued:
                _emit_status(
                    "[queued] I am still working on the previous request; "
                    "this message has been queued and will be handled after the current response."
                )
            msg_q.put({"text": obj["message"], "queued": was_queued})
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
        return fresh

    agent = _build_agent(collector, session_id, "harness")
    msg_q: queue.Queue = queue.Queue()
    ctrl_q: queue.Queue = queue.Queue()
    busy = threading.Event()
    threading.Thread(target=_stdin_reader, args=(msg_q, ctrl_q, busy), daemon=True).start()
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
        while not ctrl_q.empty():  # 丢弃上一轮遗留的过期 control，避免误打断本轮
            ctrl_q.get_nowait()
        # slash 内部分发：/help 回 reply 后继续；/exit|/quit 回 reply 后结束进程。
        slash = _slash_command(message)
        if slash is not None:
            slash_reply, should_exit = slash
            with _stdout_lock:
                sys.stdout.write(
                    json.dumps(_wire_out("reply", text=slash_reply), ensure_ascii=False) + "\n"
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
            agent, raw, terminal_status = _reply(agent, message, rebuild, ctrl_q)
        finally:
            busy.clear()
        history_snapshot = _snapshot_history(agent) or history_snapshot
        reply = _unwrap_reply(raw)  # 拆信封：用户只看最终答案
        steps = list(collector.steps)  # 完整内层迭代 → 诊断元数据；用户答案只看 reply
        payload = _wire_out("reply", text=reply, steps=steps, status=terminal_status)
        with _stdout_lock:  # 与 progress 旁路互斥，保证终态行完整
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
