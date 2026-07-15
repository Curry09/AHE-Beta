"""harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。

按 git ref 把 harness 仓 checkout 到 data/harness_runs/<ref>/，起子进程跑其自带 entry，
按逐轮 stdio JSONL 协议适配为 send/reset/close：
  stdin  {"message": str} | {"control": str}
  stdout 可选多行旁路（任意非 reply 的 JSON 对象：progress / status / 其它）→
         最后一行 {"reply": str, "steps"?: [...]} 结束本轮
控制名对 launcher 不透明（手册是能力真相源）：终结型 control（如 interrupt）最终吐 reply；
旁路型（如 status/peek）只吐非 reply 行、本轮继续。接收端放宽——未知旁路字段不报错。
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
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from auto_designer.harness.interface import HarnessInterface

_PARAMS_FILE = "params.yaml"

# 单轮回复的兜底机制。注意：harness 自身对每轮已有上界（v0 模板 _CALL_TIMEOUT×_RUN_RETRIES ≈ 16min
# 后必回 [harness error]），所以「慢」是合法的长任务，绝不能按墙钟盲杀（会误杀真长任务）。
# 真正要防的是「进程已死但孤儿子进程占着管道写端 → readline 永不 EOF」这种死锁：靠轮询 proc.poll()
# 精确识别（进程没了却没回完整行 → 立即上抛），而非靠计时。
_POLL_INTERVAL = 5.0
# 绝对上限：仅作最后兜底，防「进程还活着但真活锁」（如被改坏、自身上界被移除的 harness 无限空转）。
# 设得远高于 harness 自身 ~16min 的上界，正常长任务绝不会触达。
_SEND_ABS_CAP = 1800.0
# 读线程 EOF / 进程退出时投进行队列的哨兵（与真实 stdout 行区分）。
_EOF = object()
_SIDEBAND_PREVIEW_CAP = 500


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

    def __init__(self, entry: list[str], cwd: Path, env: dict[str, str], manual: str) -> None:
        self._entry = entry
        self._cwd = cwd
        self._env = {**os.environ, **env}
        self._proc: subprocess.Popen[str] | None = None
        self._closed = False
        # 该版本 harness 的用户手册（MANUAL.md 全文，checkout 时读入）：面向用户的能力契约，
        # 用户 agent 据此形成对本工具"能干嘛/缺什么"的预期。缺文件则为空串。
        self.manual = manual
        # 最近一次 send 的 harness 内层过程流（{kind,text} 序列）：协议 reply 之外的观测旁路，
        # persona 只吃 send 返回的 reply、看不到 steps。调用方 send 后立即 getattr 读取。
        self.last_steps: list[dict] = []
        # 本轮进行中已吐出的进度条（Codex 式活动摘要）：等待心跳时喂给用户 agent；
        # 与 steps 同源压缩，但不等于完整过程流。纯 progress 与其它旁路都会尽量映到这里。
        self.last_progress: list[dict] = []
        # 本轮全部非 reply 旁路原文（progress/status/其它）；control() 用它判断旁路型控制已响应。
        self.last_sideband: list[dict] = []
        # 心跳/续等：进程级读线程把 stdout 行丢进队列；poll 在超时内 drain——
        # 旁路累积，reply 行结束本轮。
        self._line_q: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._t0 = 0.0
        self._inflight = False
        self._start()

    @property
    def in_flight(self) -> bool:
        """本轮 send 是否仍在进行（尚无终态 reply）。旁路型 control 之后仍为 True。"""
        return self._inflight

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

    def begin(self, message: str) -> None:
        """启动一轮 send（写入 message），不阻塞等待。配合 poll 使用。"""
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可再 send")
        if self._inflight:
            raise RuntimeError("上一轮 send 尚未收完回复，不可并发 begin")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self.last_steps = []
        self.last_progress = []
        self.last_sideband = []
        self._write({"message": message})
        self._t0 = time.monotonic()
        self._inflight = True

    def _ingest_sideband(self, payload: dict) -> None:
        """收下任意非 reply 旁路：原文进 last_sideband，并尽量映到 last_progress 供等待条。"""
        self.last_sideband.append(payload)
        if "progress" in payload:
            prog = payload.get("progress")
            if isinstance(prog, dict) and prog:
                self.last_progress.append(prog)
                return
        kind = "status" if "status" in payload else "sideband"
        self.last_progress.append({"kind": kind, "text": _sideband_preview(payload)})

    def poll(self, timeout: float) -> tuple[str, object]:
        """在 timeout 秒内等当前这轮回复。

        返回 ("reply", reply_text) 若已收到；("pending", waited_sec) 若仍在跑（旁路行会先
        累积进 last_sideband / last_progress）。进程还活着就是合法长任务、绝不按墙钟盲杀；只有
        「进程已退出却没回完整 reply」（崩溃留孤儿占管道）才判死锁上抛；另设极宽松绝对上限防真活锁。"""
        if not self._inflight:
            raise RuntimeError("没有进行中的 send，不可 poll")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            waited = time.monotonic() - self._t0
            if waited >= _SEND_ABS_CAP:
                self._kill_group(signal.SIGKILL)
                self._inflight = False
                raise RuntimeError(
                    f"harness 单轮回复超绝对上限 >{_SEND_ABS_CAP:.0f}s（疑似活锁，已杀进程组）"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ("pending", waited)
            try:
                item = self._line_q.get(timeout=min(_POLL_INTERVAL, remaining))
            except queue.Empty:
                if self._proc is not None and self._proc.poll() is not None:
                    self._kill_group(signal.SIGKILL)
                    self._inflight = False
                    raise RuntimeError(
                        "harness 子进程已退出但未回完整行（崩溃/孤儿占管道）"
                    ) from None
                continue
            if item is _EOF:
                self._inflight = False
                raise RuntimeError("harness 子进程已退出（stdout EOF）")
            line = str(item)
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                self._inflight = False
                raise RuntimeError(f"harness 协议违例：{line!r}（{exc}）") from exc
            if not isinstance(payload, dict):
                self._inflight = False
                raise RuntimeError(f"harness 协议违例：非对象 {line!r}")
            if "reply" in payload:
                self._inflight = False
                steps = payload.get("steps")
                self.last_steps = steps if isinstance(steps, list) else []
                return ("reply", payload["reply"])
            # 任意非 reply JSON 旁路（progress / status / 未来字段）——放宽接收，不报错。
            self._ingest_sideband(payload)
            continue

    def control(self, name: str) -> str:
        """向 harness 发一条控制（name 不透明）并返回它对此的可见响应。

        必须在某轮 send 进行中（begin 后、reply 前）。两种合法形状：
        - 终结型（如 interrupt）：最终吐 reply，本轮结束，返回 reply 文本；
        - 旁路型（如 status/peek）：吐非纯 progress 的旁路（如 status），本轮继续，返回该旁路预览。
        发 control 后仍可能夹杂工具 progress——那些不算对本控制的应答，继续等。"""
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可发控制消息")
        if not self._inflight:
            raise RuntimeError("没有进行中的 send，控制消息无处作用")
        before = len(self.last_sideband)
        self._write({"control": name})
        while True:
            kind, val = self.poll(_POLL_INTERVAL)
            if kind == "reply":
                return val  # type: ignore[return-value]
            for payload in self.last_sideband[before:]:
                if _is_control_ack_sideband(payload):
                    return _sideband_preview(payload)

    def send(self, message: str) -> str:
        """阻塞版：begin + 等到收完整段回复（供不需要心跳的调用方 / 向后兼容）。"""
        self.begin(message)
        while True:
            kind, val = self.poll(_SEND_ABS_CAP)
            if kind == "reply":
                return val  # type: ignore[return-value]

    def reset(self) -> None:
        if self._closed:
            raise RuntimeError("harness 句柄已关闭，不可 reset")
        self._terminate()
        self._start()  # 重启 entry = 开新一局（复位语义收在 launcher 一侧）

    def close(self) -> None:
        self._terminate()
        self._closed = True  # 幂等

    def _terminate(self) -> None:
        self._inflight = False  # 复位/关闭时作废在途轮，之后可重新 begin
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

    def launch(self, ref: str, workspace_dir: str | None = None) -> HarnessInterface:
        dest = self._checkout(ref=ref)
        params = self._read_params(dest)
        entry = params["entry"]
        if not isinstance(entry, list) or not entry:
            raise ValueError(f"params.yaml 的 entry 须为非空 argv 列表：{entry!r}")
        argv = [str(a) for a in entry]
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable  # 用 launcher 的解释器跑 harness（其 venv 才有 nexau 等依赖）
        cwd = dest / params["cwd"] if params.get("cwd") else dest
        env = {str(k): str(v) for k, v in (params.get("env") or {}).items()}
        if workspace_dir is not None:
            # Spec-0008/T1 v2：与用户 agent 共享同一工作区——把它注入 harness 的 SANDBOX_WORK_DIR，
            # harness entry 读到即以它当 bash 工作根（不再自建 harness_ws_* tmp）；覆盖 params.yaml 同名键。
            env["SANDBOX_WORK_DIR"] = str(workspace_dir)
        return _HarnessHandle(entry=argv, cwd=cwd, env=env, manual=self._read_manual(dest))

    @staticmethod
    def _read_manual(dest: Path) -> str:
        """读该版本 harness 的用户手册（MANUAL.md，位于 checkout 根）。缺失即空串（老版本无手册）。"""
        manual_path = dest / "MANUAL.md"
        if not manual_path.is_file():
            return ""
        return manual_path.read_text(encoding="utf-8", errors="replace")

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
