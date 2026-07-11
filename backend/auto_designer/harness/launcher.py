"""harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。

按 git ref 把 harness 仓 checkout 到 data/harness_runs/<ref>/，起子进程跑其自带 entry，
按逐轮 stdio JSONL 协议（stdin {"message": str} → stdout {"reply": str}）适配为 send/reset/close。
harness 内部 1 或 N 个 nexau 如何编排对 launcher 不可见（黑盒）。
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from auto_designer.harness.interface import HarnessInterface

_PARAMS_FILE = "params.yaml"
_yaml = YAML(typ="safe")

# 单轮回复的兜底机制。注意：harness 自身对每轮已有上界（v0 模板 _CALL_TIMEOUT×_RUN_RETRIES ≈ 16min
# 后必回 [harness error]），所以「慢」是合法的长任务，绝不能按墙钟盲杀（会误杀真长任务）。
# 真正要防的是「进程已死但孤儿子进程占着管道写端 → readline 永不 EOF」这种死锁：靠轮询 proc.poll()
# 精确识别（进程没了却没回完整行 → 立即上抛），而非靠计时。
_POLL_INTERVAL = 5.0
# 绝对上限：仅作最后兜底，防「进程还活着但真活锁」（如被改坏、自身上界被移除的 harness 无限空转）。
# 设得远高于 harness 自身 ~16min 的上界，正常长任务绝不会触达。
_SEND_ABS_CAP = 1800.0


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
        # 心跳/续等状态（begin 起、poll 续、reply/异常止）：一轮 send 拆成"起线程读一行 + 分片轮询"，
        # 让调用方能在等待中途拿回控制权（心跳唤醒），而在途读线程保留、计算不丢。
        self._reader: threading.Thread | None = None
        self._box: dict[str, str] = {}
        self._t0 = 0.0
        self._inflight = False
        self._start()

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

    def _read_one(self) -> None:
        self._box["line"] = self._proc.stdout.readline()  # type: ignore[union-attr]

    def begin(self, message: str) -> None:
        """启动一轮 send（写入 message + 起后台读一行线程），不阻塞等待。配合 poll 使用。"""
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可再 send")
        if self._inflight:
            raise RuntimeError("上一轮 send 尚未收完回复，不可并发 begin")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self.last_steps = []  # 清上一轮，protocol 违例/无 steps 时保持空
        self._box = {}
        self._write({"message": message})
        self._reader = threading.Thread(target=self._read_one, daemon=True)
        self._reader.start()
        self._t0 = time.monotonic()
        self._inflight = True

    def poll(self, timeout: float) -> tuple[str, object]:
        """在 timeout 秒内等当前这轮回复。

        返回 ("reply", reply_text) 若已收到；("pending", waited_sec) 若仍在跑（在途读线程保留、
        计算不丢，可再次 poll 续等）。进程还活着就是合法长任务、绝不按墙钟盲杀；只有「进程已退出却
        没回完整行」（崩溃留孤儿占管道，readline 收不到 EOF）才判死锁上抛；另设极宽松绝对上限防真活锁。"""
        if not self._inflight or self._reader is None:
            raise RuntimeError("没有进行中的 send，不可 poll")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            self._reader.join(min(_POLL_INTERVAL, remaining) if remaining > 0 else 0.0)
            if not self._reader.is_alive():
                return ("reply", self._finish_inflight())
            waited = time.monotonic() - self._t0
            if self._proc.poll() is not None:  # type: ignore[union-attr]
                self._kill_group(signal.SIGKILL)
                self._inflight = False
                raise RuntimeError("harness 子进程已退出但未回完整行（崩溃/孤儿占管道）")
            if waited >= _SEND_ABS_CAP:
                self._kill_group(signal.SIGKILL)
                self._inflight = False
                raise RuntimeError(
                    f"harness 单轮回复超绝对上限 >{_SEND_ABS_CAP:.0f}s（疑似活锁，已杀进程组）"
                )
            if time.monotonic() >= deadline:
                return ("pending", waited)

    def _finish_inflight(self) -> str:
        self._inflight = False
        line = self._box.get("line", "")
        if line == "":  # EOF：子进程提前退出
            raise RuntimeError("harness 子进程已退出（stdout EOF）")
        try:
            payload = json.loads(line)
            reply = payload["reply"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(f"harness 协议违例：{line!r}（{exc}）") from exc
        # steps 为可选观测旁路：老 harness / 无内层过程时缺省，不作协议硬约束。
        steps = payload.get("steps")
        self.last_steps = steps if isinstance(steps, list) else []
        return reply

    def control(self, name: str) -> str:
        """向 harness 发一条控制消息（旁路，name 对本类不透明）并返回它据此吐出的本轮回复。

        必须在某轮 send 进行中（begin 后、reply 前）调用——控制作用于正在跑的这一轮。控制会促使
        harness 结束当前轮并吐一行 reply（如打断→"[interrupted]…"），此处等到收完并返回。"""
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可发控制消息")
        if not self._inflight:
            raise RuntimeError("没有进行中的 send，控制消息无处作用")
        self._write({"control": name})
        while True:
            kind, val = self.poll(_SEND_ABS_CAP)
            if kind == "reply":
                return val  # type: ignore[return-value]

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
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    pass  # 子进程已崩时管道可能已断，关闭报错无妨
        self._kill_group(signal.SIGTERM)  # 先礼：连子进程一起收
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_group(signal.SIGKILL)  # 后兵：强杀整组，杜绝孤儿
            self._proc.kill()
        self._proc = None


class HarnessLauncher:
    """按 ref 取出某版 harness 并启动，返回 HarnessInterface 句柄。"""

    def __init__(self, harness_repo: str, runs_root: str | Path = "data/harness_runs") -> None:
        self._harness_repo = harness_repo
        self._runs_root = Path(runs_root)

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
        if dest.is_dir() and any(dest.iterdir()):
            return dest  # 同 ref 同 SHA（内容一致）→ 安全复用
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "archive", "--format=tar", sha],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"checkout {ref!r}@{sha[:12]} 失败：{result.stderr.decode(errors='replace')[:200]}"
            )
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as tf:
            tf.extractall(dest, filter="data")
        return dest

    def _read_params(self, dest: Path) -> dict[str, Any]:
        params_path = dest / _PARAMS_FILE
        if not params_path.is_file():
            raise FileNotFoundError(f"harness 缺 {_PARAMS_FILE}：{params_path}")
        return dict(_yaml.load(params_path))
