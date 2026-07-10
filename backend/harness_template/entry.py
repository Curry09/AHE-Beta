"""harness v0 入口（spec-0003/T1 种子）：单个 nexau 的逐轮 stdio JSONL 服务。

被进化对象。launcher 把它当黑盒可启动程序：从 stdin 逐行读 {"message": str}，
向 stdout 逐行写 {"reply": str}（JSONL，一读一写严格配对）。内部如何编排（这里是单 nexau，
将来可演化为多 nexau）对 launcher 不可见——开发者 agent 后续就是在改本仓内容。

真实运行：按本目录 agent.yaml（最简「只有 bash」的工具型 agent，系统提示 = agents/main.md，
LLM_* 走 ${env}）构造单个 nexau Agent，单实例维护多轮 history。bash 在一个每会话工作区
（SANDBOX_WORK_DIR）里执行，作为「用户项目」根目录。需要 nexau 可 import 且
LLM_MODEL/LLM_BASE_URL/LLM_API_KEY 已注入。
"""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RUN_RETRIES = 4
# 单次 agent.run 硬超时（秒）：nexau 自身的 llm_config.timeout 实测不生效，故在此层用线程兜底，
# 卡住即放弃该次（daemon 线程丢弃，不阻塞进程），保证 harness 永远在 bounded 时间内回一行。
_CALL_TIMEOUT = 240
# 打断（control:interrupt）后等待 nexau 优雅停止（保留 session/history）的宽限秒数：
# executor.force_stop() 只置位中断信号，run 会在下一个检查点安全退出。超过宽限仍没退，
# 说明这次没赶上优雅停止 → 丢弃该 agent 实例重建，避开被放弃线程仍持 nexau 锁导致的自锁。
_INTERRUPT_GRACE = 15.0
# 打断时回给用户的定型回复：明确"已中止、未完成、会话上下文保留"，让用户据此决定下一步。
_INTERRUPT_REPLY = (
    "[interrupted] 已按你的要求停止当前处理，这一步没有完成。"
    "会话上下文已保留——你可以直接给出修改后的要求或下一条指示，我会接着当前进度继续。"
)


class _Interrupted(Exception):
    """收到用户打断：中止当前这轮 agent.run。rebuild=True 表示没赶上优雅停止、需重建 agent 避自锁。"""

    def __init__(self, *, rebuild: bool) -> None:
        super().__init__("interrupted by user")
        self.rebuild = rebuild


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
# 内层过程流各类文本上限（对齐 auto_designer StepTracer）：工具入参/输出可能带整文件内容，
# 摘要后进时间线；assistant 是过程主体，给宽上限只防极端失控。
_TOOL_TEXT_CAP = 200
_TOOL_RESULT_CAP = 500
_ASSISTANT_TEXT_CAP = 20_000


def _run_supervised(agent, message, timeout, ctrl_q):
    """跑一次 agent.run，同时守望硬超时与用户打断（control 队列）。

    - 正常完成：返回结果。
    - 硬超时：raise TimeoutError（daemon 线程被放弃，caller 重建避自锁）。
    - 收到 interrupt：force_stop 优雅停止（保留 session）→ raise _Interrupted(rebuild=False)；
      若宽限内没停下 → _Interrupted(rebuild=True)，由 caller 重建避自锁。
    ctrl_q 为 None（无打断能力的调用场景）时退化为纯超时行为。"""
    box: dict = {}

    def target():
        try:
            box["out"] = agent.run(message=message)
        except Exception as exc:  # noqa: BLE001  透传给调用方判定/重试
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    deadline = time.monotonic() + timeout
    while t.is_alive():
        # 小步轮询：既要能及时响应打断，又要能掐硬超时。
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
        if time.monotonic() >= deadline:
            raise TimeoutError(f"agent.run 超时 >{timeout}s")
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


def _build_agent(collector):
    """按本目录 agent.yaml 构造工具型 nexau Agent（只挂 bash + complete_task）。

    挂 collector 作 tracer：把内层每步（模型发言/工具调用/结果）收进 collector.steps，
    供 harness 经协议 steps 字段吐给观测层。"""
    from nexau import Agent, AgentConfig

    cfg = AgentConfig.from_yaml(config_path=_HERE / "agent.yaml")
    cfg.resolved_tracer = collector  # 内层过程流 → collector.steps（观测用，不影响回复）
    return Agent(config=cfg)


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

    镜像 auto_designer 的 StepTracer：LLM end→assistant，TOOL start→tool，
    TOOL end→tool_result/tool_error。每次 agent.run 前 reset()，run 后读 steps —— 即该轮
    harness 内层迭代的完整过程；经协议 steps 字段吐给观测层（persona 只吃 reply，看不到 steps）。
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

        def reset(self):
            self.steps = []

        def _add(self, kind, text, cap):
            try:
                t = (text or "")[:cap]
                if t:
                    self.steps.append({"kind": kind, "text": t})
            except Exception:  # noqa: BLE001  观测层失败不影响 agent
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
    """返回 (live_agent, reply)：超时/打断重试前视情重建 agent，避开被放弃线程仍持的 nexau 锁。

    `_run_supervised` 超时时只能 raise，那个 daemon 线程杀不掉、仍持有该 (session, agent)
    的 nexau 锁并持续心跳续期 → 同 agent 重试必撞 "already locked by holder=<pid>"（自锁）。
    故超时分支换用 `rebuild()` 起一个新 agent（新 session/新锁键）再试；代价是丢该实例多轮
    history（但卡死那次本就没拿到回复，可接受）。502/空回复时线程已结束、锁已释放，保持同 agent。

    打断（_Interrupted）：立即回定型的 [interrupted] 回复、不再重试；rebuild 为真时先重建 agent
    （没赶上优雅停止），为假时保持同 agent —— 优雅停止已保留 history，用户下一条可接着聊。
    """
    last = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = _run_supervised(agent, message, _CALL_TIMEOUT, ctrl_q)  # 硬超时 + 可打断
            text = out if isinstance(out, str) else (out[0] if out else "")  # 工具型返回 result 串
            if text and text.strip():  # 非空才算成功
                return agent, text
            last = "empty reply"  # 空回复（网关 200+空内容不抛异常）视为失败，不得静默返回
        except _Interrupted as it:  # 用户打断：不重试，保留/重建后回定型回复
            if it.rebuild:
                agent = rebuild()
            return agent, _INTERRUPT_REPLY
        except TimeoutError as exc:  # 线程被放弃仍持锁 → 重建避自锁
            last = exc
            agent = rebuild()
        except Exception as exc:  # 网关 502 等 → 同 agent 退避重试（线程已结束、锁已释放）
            last = exc
        if attempt < _RUN_RETRIES - 1:  # 末次不再睡
            time.sleep(1.5 * (attempt + 1))
    return agent, f"[harness error] {last}"


_EOF = object()  # stdin 读线程读到 EOF 时投递的哨兵


def _stdin_reader(msg_q: queue.Queue, ctrl_q: queue.Queue) -> None:
    """后台逐行读 stdin，按类型分发：{"message":..} → msg_q，{"control":..} → ctrl_q。

    独立线程读，才能在某轮 agent.run 阻塞进行中仍收到 {"control":"interrupt"} 并即时打断
    （主线程正忙于该轮、无法自己读 stdin）。非法行/无 message 的行静默跳过；EOF 投 _EOF 收尾。"""
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
        if "control" in obj:
            ctrl_q.put(obj)
        elif "message" in obj:
            msg_q.put(obj["message"])
    msg_q.put(_EOF)


def main() -> None:
    _setup_workspace()  # 先就位 SANDBOX_WORK_DIR，供 agent 的 local sandbox 读取
    collector = _make_step_collector()  # 跨轮/跨重建复用同一实例，逐轮 reset
    agent = _build_agent(collector)  # 单实例，history 由 nexau 自身跨轮维护
    msg_q: queue.Queue = queue.Queue()
    ctrl_q: queue.Queue = queue.Queue()
    threading.Thread(target=_stdin_reader, args=(msg_q, ctrl_q), daemon=True).start()
    while True:
        message = msg_q.get()
        if message is _EOF:  # stdin 关闭：正常收尾退出
            break
        while not ctrl_q.empty():  # 丢弃上一轮遗留的过期 control，避免误打断本轮
            ctrl_q.get_nowait()
        collector.reset()  # 只收本轮内层过程
        agent, raw = _reply(agent, message, lambda: _build_agent(collector), ctrl_q)
        reply = _unwrap_reply(raw)  # 拆信封：用户只看最终答案
        payload: dict = {"reply": reply}
        steps = list(collector.steps)  # 完整内层迭代 → 观测层（persona 不吃）
        if steps:
            payload["steps"] = steps
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
