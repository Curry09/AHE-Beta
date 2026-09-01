"""harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。

按 git ref 把 harness 仓 checkout 到 data/harness_runs/<ref>/，起子进程跑其自带 entry，
按 stdio JSONL 协议适配为 send/reset/close（Spec-0036）：
  stdin  用户消息统一 write_message；外通道 interrupt/shutdown
  stdout progress/status 等旁路照记；type=reply 为软唤醒（poll 不绑写旗标）
控制名对 launcher 不透明（HELP.md 是能力真相源）。接收端放宽——未知旁路字段不报错。
harness 内部 1 或 N 个 nexau 如何编排对 launcher 不可见（黑盒）。
"""

from __future__ import annotations

import io
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from auto_designer.harness.interface import HarnessInterface
from auto_designer.user.sim.runtime import DockerWorkspaceRuntime, Workspace, as_runtime

_PARAMS_FILE = "params.yaml"

# 单轮回复的兜底机制。harness 自身不设整轮墙钟上限：「慢」是合法的长任务，
# 由外层 90s persona 心跳决定续等/打断，不按旧 240s deadline 盲杀。
# 真正要防的是「进程已死但孤儿子进程占着管道写端 → readline 永不 EOF」这种死锁：靠轮询 proc.poll()
# 精确识别（进程没了却没回完整行 → 立即上抛），而非靠计时。
_POLL_INTERVAL = 5.0
# 绝对上限：仅作最后基础设施兜底，防「进程还活着但真活锁」。
# 正常慢任务应先经多次 persona 心跳做出明确决策，不依赖此上限收敛。
_SEND_ABS_CAP = 1800.0
# 读线程 EOF / 进程退出时投进行队列的哨兵（与真实 stdout 行区分）。
_EOF = object()
_SIDEBAND_PREVIEW_CAP = 500
_POST_REPLY_DRAIN_SEC = 0.2


def _sideband_preview(payload: dict) -> str:
    """把旁路 JSON 压成短文本，供 control() 返回值与等待条展示。"""
    status = payload.get("status")
    if isinstance(status, dict):
        bits: list[str] = []
        for key in ("phase", "elapsed", "completed", "can_continue", "note"):
            if key in status and status[key] is not None:
                bits.append(f"{key}={status[key]}")
        step = status.get("current_step") or (status.get("progress") or {}).get("last_step")
        if isinstance(step, dict) and step.get("text"):
            bits.append(f"step={step.get('text')}")
        if bits:
            return "; ".join(bits)[:_SIDEBAND_PREVIEW_CAP]
    try:
        return json.dumps(payload, ensure_ascii=False)[:_SIDEBAND_PREVIEW_CAP]
    except (TypeError, ValueError):
        return str(payload)[:_SIDEBAND_PREVIEW_CAP]


def _is_control_ack_sideband(payload: dict) -> bool:
    """是否算「对本 control 的应答旁路」（排除夹杂的纯 progress 工具活动条）。"""
    if "status" in payload:
        return True
    # 除 progress 外还有其它键 → 未知旁路也认（协议放宽，不注册）
    return any(k != "progress" for k in payload)


class _HarnessHandle:
    """子进程句柄，实现 HarnessInterface。一句柄一子进程一会话。"""

    def __init__(
        self,
        entry: list[str],
        cwd: Path,
        env: dict[str, str],
        help_text: str,
        protocol: str = "legacy",
        workspace_runtime=None,
    ) -> None:
        self._entry = entry
        self._cwd = cwd
        self._env = {**os.environ, **env}
        self._protocol = protocol
        self._workspace_runtime = workspace_runtime
        self._proc: subprocess.Popen[str] | None = None
        self._closed = False
        # 该版本 harness 的帮助文本（HELP.md）：面向用户的能力契约，
        # 调用方据此形成对本工具"能干嘛/缺什么"的预期。缺文件则为空串。
        self.help_text = help_text
        # 最近一次 send 的 harness 内层过程流（{kind,text} 序列）：协议 reply 之外的观测旁路，
        # persona 只吃 send 返回的 reply、看不到 steps。调用方 send 后立即 getattr 读取。
        self.last_steps: list[dict] = []
        # 本轮进行中已吐出的进度条（Codex 式活动摘要）：等待心跳时喂给用户 agent；
        # 与 steps 同源压缩，但不等于完整过程流。纯 progress 与其它旁路都会尽量映到这里。
        self.last_progress: list[dict] = []
        # 本轮全部非 reply 旁路原文（progress/status/其它）；control() 用它判断旁路型控制已响应。
        self.last_sideband: list[dict] = []
        # 本轮 stdout 用户可见事件流（reply/progress/status/error/ack 等），按观察顺序保留；
        # 不做 request/reply 配对推断，只记录 harness stdout 自身说了什么。
        self.last_visible_events: list[dict] = []
        self.visible_events: list[dict] = []
        self._usage_events: list[dict] = []
        # 心跳/续等：进程级读线程把 stdout 行丢进队列；poll 在超时内 drain——
        # 旁路累积，reply 为软唤醒（Spec-0036；不绑写路径）。
        self._line_q: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._t0 = 0.0
        # 软状态：自上次 write_message 起是否仍在等一条 reply（供 interrupt/abs-cap/try_reply）。
        # 不约束写、不约束 poll（Spec-0036）。
        self._awaiting_reply = False
        self._request_id = ""
        self._request_started_at = ""
        self.request_outcomes: list[dict[str, Any]] = []
        # 最近一笔已结束请求的结构化终态。调用方必须能区分正常 reply 与
        # "带 timeout/crash 文本的终局 reply"，不能再靠解析人类可见文本猜测。
        self.last_request_status = ""
        self._start()

    @property
    def in_flight(self) -> bool:
        """兼容旧名：是否自上次写消息起仍在等 reply（软状态，不挡写/读）。"""
        return self._awaiting_reply

    def _record_visible_event(self, event_type: str, text: str, raw: dict) -> None:
        event = {
            "type": event_type,
            "text": str(text or ""),
            "source": "harness_stdout",
            "observed_at": datetime.now(UTC).isoformat(),
            "raw": dict(raw),
        }
        self.last_visible_events.append(event)
        self.visible_events.append(event)

    def drain_visible_events(self) -> list[dict]:
        """取出本轮新 stdout 可见事件；不解释、不配对，只按观察顺序返回。"""
        events = list(self.last_visible_events)
        self.last_visible_events.clear()
        return events

    def drain_usage_events(self) -> list[dict]:
        # close/interrupt may leave a final usage line in the reader queue without
        # another poll. Harvest only usage frames and put every other item back.
        deferred: list[object] = []
        while True:
            try:
                item = self._line_q.get_nowait()
            except queue.Empty:
                break
            if item is _EOF:
                deferred.append(item)
                continue
            try:
                payload = json.loads(str(item))
            except (json.JSONDecodeError, TypeError):
                deferred.append(item)
                continue
            if isinstance(payload, dict) and (payload.get("type") == "usage" or "usage" in payload):
                self._ingest_sideband(payload)
            else:
                deferred.append(item)
        for item in deferred:
            self._line_q.put(item)
        events = list(self._usage_events)
        self._usage_events.clear()
        return events

    def _start(self) -> None:
        # 命令不存在 / entry 崩溃 → Popen 抛错，由 launch 上抛（附 entry 信息）。
        self._proc = subprocess.Popen(
            self._entry,
            cwd=str(self._cwd),
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,  # 独立进程组：超时/关闭时连 harness 起的子进程一并回收
        )
        self._line_q = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        """进程存活期间持续 readline → 队列；EOF 投 _EOF 后退出。

        关流/断管时 readline 可能抛 ValueError(I/O on closed file) 或 OSError——视为 EOF，
        不让 daemon 读线程抛未捕获异常（对齐 origin/main 对单行读线程的兜底）。
        """
        stdout = self._proc.stdout if self._proc is not None else None
        if stdout is None:
            self._line_q.put(_EOF)
            return
        while True:
            try:
                line = stdout.readline()
            except (ValueError, OSError):
                self._line_q.put(_EOF)
                return
            if line == "":
                self._line_q.put(_EOF)
                return
            self._line_q.put(line)

    def _kill_group(self, sig: int) -> None:
        """给 harness 整个进程组发信号（含其 nexau/sandbox 子进程）；进程已亡则忽略。"""
        if self._proc is None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _write(self, obj: dict) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _message_frame(self, message: str) -> dict:
        if self._protocol == "stdio-jsonl-v1":
            return {"type": "message", "text": message}
        return {"message": message}

    def _interrupt_frame(self) -> dict:
        if self._protocol == "stdio-jsonl-v1":
            return {"type": "interrupt"}
        return {"control": "interrupt"}

    def _shutdown_frame(self) -> dict:
        if self._protocol == "stdio-jsonl-v1":
            return {"type": "shutdown"}
        return {"control": "shutdown"}

    def write_message(self, message: str) -> None:
        """统一写入口（Spec-0036）：向 harness stdin 写入一条用户消息。

        不区分「正式轮次 / 加塞」；堵/排队由 harness 决定。可连续多次调用。
        """
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可再 send")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self.last_request_status = ""
        self._write(self._message_frame(message))
        self._t0 = time.monotonic()
        self._awaiting_reply = True
        self._request_id = uuid.uuid4().hex
        self._request_started_at = datetime.now(UTC).isoformat()

    def _finish_request(self, status: str) -> None:
        if not self._request_id:
            return
        self.last_request_status = status
        self.request_outcomes.append(
            {
                "request_id": self._request_id,
                "status": status,
                "started_at": self._request_started_at,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        self._request_id = ""
        self._request_started_at = ""
        if status in {"timed_out", "crashed"} and self._workspace_runtime is not None:
            self._workspace_runtime.invalidate(f"harness request {status}")

    def begin(self, message: str) -> None:
        """Deprecated alias of write_message（Spec-0036）。"""
        self.write_message(message)

    def emit_message(self, message: str) -> None:
        """Deprecated alias of write_message（Spec-0036）。"""
        self.write_message(message)

    def _ingest_sideband(self, payload: dict) -> None:
        """收下任意非 reply 旁路：原文进 last_sideband，并尽量映到 last_progress 供等待条。"""
        if payload.get("type") == "usage" or "usage" in payload:
            raw = (
                payload.get("usage")
                if "usage" in payload and payload.get("type") != "usage"
                else payload
            )
            if isinstance(raw, dict):
                self._usage_events.append(dict(raw))
            return
        self.last_sideband.append(payload)
        event_type = str(payload.get("type") or ("status" if "status" in payload else "sideband"))
        event_text = ""
        if isinstance(payload.get("text"), str):
            event_text = str(payload.get("text") or "")
        elif isinstance(payload.get("progress"), dict):
            event_text = str((payload.get("progress") or {}).get("text") or "")
        if not event_text:
            event_text = _sideband_preview(payload)
        self._record_visible_event(event_type, event_text, payload)
        if payload.get("type") == "progress":
            text = payload.get("text")
            if isinstance(text, str) and text:
                self.last_progress.append(
                    {"kind": str(payload.get("kind") or "progress"), "text": text}
                )
                return
        if "progress" in payload:
            prog = payload.get("progress")
            if isinstance(prog, dict) and prog:
                self.last_progress.append(prog)
                return
        kind = "status" if "status" in payload else "sideband"
        self.last_progress.append({"kind": kind, "text": _sideband_preview(payload)})

    def _post_reply_drain(self) -> None:
        """短暂收下紧跟终态 reply 的旁路事件；不等待下一条终态 reply。"""
        deadline = time.monotonic() + _POST_REPLY_DRAIN_SEC
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                item = self._line_q.get(timeout=min(0.02, remaining))
            except queue.Empty:
                # The stdout reader may enqueue a frame shortly after the reply.
                # Keep the bounded grace period instead of treating the first
                # temporarily empty queue as proof that no sideband follows.
                continue
            if item is _EOF:
                self._line_q.put(item)
                return
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                self._line_q.put(line)
                return
            if not isinstance(payload, dict):
                self._line_q.put(line)
                return
            if payload.get("type") in {"reply", "error"} or "reply" in payload:
                self._line_q.put(line)
                return
            self._ingest_sideband(payload)

    def poll(self, timeout: float) -> tuple[str, object]:
        """在 timeout 秒内等下一条 type=reply（软唤醒，Spec-0036）。

        不要求写路径旗标。返回 ("reply", text) 或 ("pending", waited_sec)。
        progress/status 等旁路照记并继续等。进程已死却无完整行则上抛；
        自上次 write 起的极宽松绝对上限仅在仍 awaiting_reply 时防活锁。
        """
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可 poll")
        t_poll0 = time.monotonic()
        deadline = t_poll0 + max(0.0, timeout)
        while True:
            if self._awaiting_reply and self._t0 > 0:
                waited_abs = time.monotonic() - self._t0
                if waited_abs >= _SEND_ABS_CAP:
                    self._kill_group(signal.SIGKILL)
                    self._awaiting_reply = False
                    self._finish_request("timed_out")
                    raise RuntimeError(
                        f"harness 单轮回复超绝对上限 >{_SEND_ABS_CAP:.0f}s（疑似活锁，已杀进程组）"
                    )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                base = self._t0 if self._awaiting_reply and self._t0 > 0 else t_poll0
                return ("pending", time.monotonic() - base)
            try:
                item = self._line_q.get(timeout=min(_POLL_INTERVAL, remaining))
            except queue.Empty:
                if self._proc is not None and self._proc.poll() is not None:
                    # 进程已退出：若队列已空且仍在等 reply，判崩溃；否则当作无更多输出。
                    if self._awaiting_reply:
                        self._kill_group(signal.SIGKILL)
                        self._awaiting_reply = False
                        self._finish_request("crashed")
                        raise RuntimeError(
                            "harness 子进程已退出但未回完整行（崩溃/孤儿占管道）"
                        ) from None
                    return ("pending", time.monotonic() - t_poll0)
                continue
            if item is _EOF:
                self._awaiting_reply = False
                self._finish_request("crashed")
                raise RuntimeError("harness 子进程已退出（stdout EOF）")
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                self._awaiting_reply = False
                raise RuntimeError(f"harness 协议违例：{line!r}（{exc}）") from exc
            if not isinstance(payload, dict):
                self._awaiting_reply = False
                raise RuntimeError(f"harness 协议违例：非对象 {line!r}")
            if payload.get("type") == "error":
                self._awaiting_reply = False
                self._finish_request("crashed")
                msg = payload.get("message") or payload.get("text") or payload
                self._record_visible_event("error", str(msg), payload)
                raise RuntimeError(f"harness error: {msg}")
            if payload.get("type") == "reply":
                self._awaiting_reply = False
                status = str(payload.get("status") or "completed")
                self._finish_request(status)
                steps = payload.get("steps")
                self.last_steps = steps if isinstance(steps, list) else []
                text = str(payload.get("text", ""))
                self._record_visible_event("reply", text, payload)
                self._post_reply_drain()
                return ("reply", text)
            if "reply" in payload:
                self._awaiting_reply = False
                self._finish_request(str(payload.get("status") or "completed"))
                steps = payload.get("steps")
                self.last_steps = steps if isinstance(steps, list) else []
                text = str(payload["reply"])
                self._record_visible_event("reply", text, payload)
                self._post_reply_drain()
                return ("reply", text)
            self._ingest_sideband(payload)
            continue

    def try_reply(self) -> str | None:
        """非阻塞：若 reply 已在 stdout 缓冲中则取出（软唤醒，不要求写旗标）。

        供心跳决策之后、执行动作之前调用：LLM 思考期间到的 reply 不应再被 give_up/interrupt 吞掉。
        旁路行照常吞进 last_progress；队列空则返回 None。
        """
        if self._closed or self._proc is None:
            return None
        while True:
            try:
                item = self._line_q.get_nowait()
            except queue.Empty:
                return None
            if item is _EOF:
                self._awaiting_reply = False
                self._finish_request("crashed")
                raise RuntimeError("harness 子进程已退出（stdout EOF）")
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                self._awaiting_reply = False
                raise RuntimeError(f"harness 协议违例：{line!r}（{exc}）") from exc
            if not isinstance(payload, dict):
                self._awaiting_reply = False
                raise RuntimeError(f"harness 协议违例：非对象 {line!r}")
            if payload.get("type") == "error":
                self._awaiting_reply = False
                self._finish_request("crashed")
                msg = payload.get("message") or payload.get("text") or payload
                self._record_visible_event("error", str(msg), payload)
                raise RuntimeError(f"harness error: {msg}")
            if payload.get("type") == "reply":
                self._awaiting_reply = False
                self._finish_request(str(payload.get("status") or "completed"))
                steps = payload.get("steps")
                self.last_steps = steps if isinstance(steps, list) else []
                text = str(payload.get("text", ""))
                self._record_visible_event("reply", text, payload)
                self._post_reply_drain()
                return text
            if "reply" in payload:
                self._awaiting_reply = False
                self._finish_request(str(payload.get("status") or "completed"))
                steps = payload.get("steps")
                self.last_steps = steps if isinstance(steps, list) else []
                text = str(payload["reply"])
                self._record_visible_event("reply", text, payload)
                self._post_reply_drain()
                return text
            self._ingest_sideband(payload)

    def control(self, name: str) -> str:
        """外通道：向 harness 发控制（用户侧主路径是 interrupt ≈ Ctrl+C）。

        - interrupt（及同类终结型）：最终吐 reply，返回 reply 文本。
        - 若 harness 仍对其它名吐旁路 ack：返回旁路预览（兼容旧 wire）。
        不要求写路径旗标（Spec-0036）；进程须仍打开。
        """
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可发控制消息")
        before = len(self.last_sideband)
        self._write(self._interrupt_frame() if name == "interrupt" else {"control": name})
        self._t0 = time.monotonic()
        self._awaiting_reply = True
        while True:
            kind, val = self.poll(_POLL_INTERVAL)
            if kind == "reply":
                return val  # type: ignore[return-value]
            for payload in self.last_sideband[before:]:
                if _is_control_ack_sideband(payload):
                    return _sideband_preview(payload)

    def send(self, message: str) -> str:
        """阻塞版：write_message + 等到下一条 reply（Spec-0036）。"""
        self.write_message(message)
        while True:
            kind, val = self.poll(_SEND_ABS_CAP)
            if kind == "reply":
                return val  # type: ignore[return-value]

    def reset(self) -> None:
        if self._closed:
            raise RuntimeError("harness 句柄已关闭，不可 reset")
        self._terminate()
        self._start()  # 重启 entry = 开新一局（复位语义收在 launcher 一侧）

    def shutdown(self) -> None:
        """按 human-facing interface 结束进程；v1 先发 shutdown，随后兜底回收进程组。"""
        if not self._closed and self._proc is not None and self._proc.stdin is not None:
            try:
                self._write(self._shutdown_frame())
            except (BrokenPipeError, OSError, AssertionError):
                pass
        self.close()

    def close(self) -> None:
        self._terminate()
        self._closed = True  # 幂等

    def _terminate(self) -> None:
        self._awaiting_reply = False
        if self._proc is None:
            return
        # 顺序：先杀整组 → wait/兜底 SIGKILL → join 读线程 → 再关流、置空 _proc。
        # readline 得 EOF 的前提是管道写端都关闭，故 join 放在 SIGKILL 兜底之后；
        # _read_loop 已兜 (ValueError, OSError)。反序关流会与在途读线程抢 stdout。
        self._kill_group(signal.SIGTERM)
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(signal.SIGKILL)
            self._proc.kill()
        if self._reader is not None:
            self._reader.join(timeout=5)
            self._reader = None
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    pass
        self._proc = None


class HarnessLauncher:
    """按 ref 取出某版 harness 并启动，返回 HarnessInterface 句柄。"""

    def __init__(self, harness_repo: str, runs_root: str | Path = "data/harness_runs") -> None:
        self._harness_repo = harness_repo
        self._runs_root = Path(runs_root)
        # Spec-0017/T5：a 段并行后同轮所有会话同 SHA → 同一 checkout dest，_checkout 的
        # check-then-extract 必须进程内互斥（首线程干活，其余命中缓存）。
        self._checkout_lock = threading.Lock()

    def launch(self, ref: str, workspace_dir: Workspace | None = None) -> HarnessInterface:
        dest = self._checkout(ref=ref)
        params = self._read_params(dest)
        entry = params["entry"]
        if not isinstance(entry, list) or not entry:
            raise ValueError(f"params.yaml 的 entry 须为非空 argv 列表：{entry!r}")
        argv = [str(a) for a in entry]
        runtime = as_runtime(workspace_dir) if workspace_dir is not None else None
        is_docker = isinstance(runtime, DockerWorkspaceRuntime)
        if argv[0] in ("python", "python3"):
            argv[0] = "python3" if is_docker else sys.executable
        cwd = dest / params["cwd"] if params.get("cwd") else dest
        env = {str(k): str(v) for k, v in (params.get("env") or {}).items()}
        protocol = str(params.get("protocol") or params.get("interface") or "legacy")
        if protocol not in ("legacy", "stdio-jsonl-v1"):
            raise ValueError(f"params.yaml 的 protocol/interface 不支持：{protocol!r}")
        if protocol == "stdio-jsonl-v1":
            env.setdefault("HARNESS_STDIO_PROTOCOL", protocol)
        if runtime is not None:
            # Spec-0008/T1 v2：与用户 agent 共享同一工作区——把它注入 harness 的 SANDBOX_WORK_DIR，
            # harness entry 读到即以它当 bash 工作根（不再自建 harness_ws_* tmp）；覆盖 params.yaml 同名键。
            env["SANDBOX_WORK_DIR"] = runtime.cwd
        host_cwd = cwd
        host_env = env
        if is_docker:
            container_root = f"/opt/auto-designer/harness/{dest.name}"
            runtime.stage_directory(dest, container_root)
            relative_cwd = cwd.relative_to(dest)
            container_cwd = str(Path(container_root) / relative_cwd)
            inherited = {
                key: value
                for key, value in os.environ.items()
                if key.startswith(("LLM_", "NEXAU_", "AUTO_DESIGNER_"))
                or key in {"NO_PROXY", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY"}
            }
            argv = runtime.popen_argv(argv, cwd=container_cwd, env={**inherited, **env})
            # Environment/workdir are encoded in docker exec argv.  The docker client
            # itself runs from the immutable host checkout and needs only host env.
            host_cwd = dest
            host_env = {}
        return _HarnessHandle(
            entry=argv,
            cwd=host_cwd,
            env=host_env,
            help_text=self._read_help_text(dest),
            protocol=protocol,
            workspace_runtime=runtime if is_docker else None,
        )

    @staticmethod
    def _read_help_text(dest: Path) -> str:
        """读该版本 harness 的帮助文本（HELP.md）；缺失即空串。"""
        help_path = dest / "HELP.md"
        if not help_path.is_file():
            return ""
        return help_path.read_text(encoding="utf-8", errors="replace")

    def _resolve_sha(self, *, ref: str) -> str:
        """把 ref（分支/tag/SHA）解析成确定的 commit SHA；非法 ref 抛 RuntimeError。"""
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"解析 ref {ref!r} 失败：{result.stderr.decode(errors='replace')[:200]}"
            )
        return result.stdout.decode().strip()

    def _checkout(self, *, ref: str) -> Path:
        # 按 commit SHA 而非 ref 名缓存：release 这类会变的分支，内容一变就落到新目录，
        # 绝不复用陈旧 checkout（曾导致跑的是旧 entry.py、harness 静默空回复）。
        sha = self._resolve_sha(ref=ref)
        dest = self._runs_root / f"{ref.replace('/', '_')}-{sha[:12]}"
        # Spec-0017/T5：并行会话同 SHA 同 dest，check-then-extract 全程持锁——无锁时多线程同时
        # 通过存在性检查后并发 extractall 同一目录，params.yaml 被两条 tar 流叠写出重复键/乱字节；
        # 且 A 半解压时 B 会把「非空目录」误判为完整缓存复用（生产实跑踩中）。
        with self._checkout_lock:
            if dest.is_dir() and any(dest.iterdir()):
                return dest  # 同 ref 同 SHA（内容一致）→ 安全复用
            result = subprocess.run(
                ["git", "-C", self._harness_repo, "archive", "--format=tar", sha],
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"checkout {ref!r}@{sha[:12]} 失败："
                    f"{result.stderr.decode(errors='replace')[:200]}"
                )
            # 解压到唯一临时目录后原子 rename 占位：半解压目录绝不可能以 dest 之名存在——进程
            # 中途崩溃只留无害 *.tmp* 孤儿（不匹配任何 dest 名，不污染缓存）；跨进程并发时输者
            # rename 失败（dest 已被赢者完整就位）→ 弃自己的 tmp、复用 dest。
            self._runs_root.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(dir=self._runs_root, prefix=dest.name + ".tmp"))
            try:
                with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tf:
                    tf.extractall(tmp, filter="data")
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            try:
                tmp.rename(dest)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
                if not (dest.is_dir() and any(dest.iterdir())):
                    raise  # 不是「别人已就位」而是真失败：如实上抛
            return dest

    def _read_params(self, dest: Path) -> dict[str, Any]:
        params_path = dest / _PARAMS_FILE
        if not params_path.is_file():
            raise FileNotFoundError(f"harness 缺 {_PARAMS_FILE}：{params_path}")
        # Spec-0017/T5：ruamel 的 YAML 实例非线程安全（解析器内部状态跨调用共享），并行 launch
        # 下共享模块级单例会被并发 load 互相搅乱 → 每次解析新建实例（构造开销微不足道）。
        return dict(YAML(typ="safe").load(params_path))
