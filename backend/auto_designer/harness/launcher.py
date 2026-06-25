"""harness launcher（spec-0003/T1）：把某版 harness 程序接成 spec-0001 的 HarnessInterface。

按 git ref 把 harness 仓 checkout 到 data/harness_runs/<ref>/，起子进程跑其自带 entry，
按逐轮 stdio JSONL 协议（stdin {"message": str} → stdout {"reply": str}）适配为 send/reset/close。
harness 内部 1 或 N 个 nexau 如何编排对 launcher 不可见（黑盒）。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from auto_designer.harness.interface import HarnessInterface

_PARAMS_FILE = "params.yaml"
_yaml = YAML(typ="safe")


class _HarnessHandle:
    """子进程句柄，实现 HarnessInterface。一句柄一子进程一会话。"""

    def __init__(self, entry: list[str], cwd: Path, env: dict[str, str]) -> None:
        self._entry = entry
        self._cwd = cwd
        self._env = {**os.environ, **env}
        self._proc: subprocess.Popen[str] | None = None
        self._closed = False
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
        )

    def send(self, message: str) -> str:
        if self._closed or self._proc is None:
            raise RuntimeError("harness 句柄已关闭，不可再 send")
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(json.dumps({"message": message}, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if line == "":  # EOF：子进程提前退出
            raise RuntimeError("harness 子进程已退出（stdout EOF）")
        try:
            payload = json.loads(line)
            return payload["reply"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError(f"harness 协议违例：{line!r}（{exc}）") from exc

    def reset(self) -> None:
        if self._closed:
            raise RuntimeError("harness 句柄已关闭，不可 reset")
        self._terminate()
        self._start()  # 重启 entry = 开新一局（复位语义收在 launcher 一侧）

    def close(self) -> None:
        self._terminate()
        self._closed = True  # 幂等

    def _terminate(self) -> None:
        if self._proc is None:
            return
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None:
                stream.close()
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None


class HarnessLauncher:
    """按 ref 取出某版 harness 并启动，返回 HarnessInterface 句柄。"""

    def __init__(self, harness_repo: str, runs_root: str | Path = "data/harness_runs") -> None:
        self._harness_repo = harness_repo
        self._runs_root = Path(runs_root)

    def launch(self, ref: str) -> HarnessInterface:
        dest = self._checkout(ref)
        params = self._read_params(dest)
        entry = params["entry"]
        if not isinstance(entry, list) or not entry:
            raise ValueError(f"params.yaml 的 entry 须为非空 argv 列表：{entry!r}")
        argv = [str(a) for a in entry]
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable  # 用 launcher 的解释器跑 harness（其 venv 才有 nexau 等依赖）
        cwd = dest / params["cwd"] if params.get("cwd") else dest
        env = {str(k): str(v) for k, v in (params.get("env") or {}).items()}
        return _HarnessHandle(entry=argv, cwd=cwd, env=env)

    def _checkout(self, ref: str) -> Path:
        dest = self._runs_root / ref
        if dest.is_dir() and any(dest.iterdir()):
            return dest  # 同 ref 已取出 → 复用（幂等）
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "archive", "--format=tar", ref],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"checkout ref {ref!r} 失败：{result.stderr.decode(errors='replace')[:200]}"
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
