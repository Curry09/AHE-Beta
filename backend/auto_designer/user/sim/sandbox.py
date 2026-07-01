"""内层用户 agent 的最小执行 sandbox（spec-0008/T2）。

以一个工作目录为 cwd（来自 0008/T1 materialize，或缺省新建空 tempdir），提供受限的
shell 执行与路径解析。所有路径相对 cwd 解析、禁止逃逸子树。

非安全 sandbox：仅最小隔离（cwd 限定 + 超时），不抗恶意代码（不做 Docker/seccomp）。
威胁模型是「用户在自己机器上跑助手提议的代码」，与生产沙箱不同；强隔离留后续。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# run_shell 输出截断上限（字符），防一次跑出超大输出灌爆 prompt。
_MAX_OUTPUT = 20_000


class Sandbox:
    """一个工作目录 + 受限执行。workspace 缺省时自建空 tempdir 并在 cleanup 时删除。"""

    def __init__(self, workspace: str | None = None) -> None:
        self._owns_tmp = workspace is None
        base = workspace or tempfile.mkdtemp(prefix="sim_sandbox_")
        self.cwd = str(Path(base).resolve())

    def resolve(self, path: str) -> str:
        """把相对 path 解析到 cwd 子树内的绝对路径；逃逸（.. / 绝对路径）即拒。"""
        base = Path(self.cwd).resolve()
        target = (base / path).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"path escapes sandbox: {path!r}")
        return str(target)

    def _env(self) -> dict[str, str] | None:
        """spec-0009/T3：工作区带 `.venv` 时返回注入 VIRTUAL_ENV + PATH 前置的环境。

        <cwd>/.venv/bin 存在则让 python/pytest 解析到该 venv（对内层 LLM 透明——照常
        run_shell("pytest ...") 即命中）；无 `.venv` 返回 None（继承宿主，退化为今天的
        ambient 行为，对 0008 既有场景零改动）。
        """
        bindir = Path(self.cwd) / ".venv" / "bin"
        if not bindir.is_dir():
            return None
        env = dict(os.environ)
        env["VIRTUAL_ENV"] = str(bindir.parent)
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
        env.pop("PYTHONHOME", None)  # venv 与 PYTHONHOME 互斥，清掉以免污染解析
        return env

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        """在 cwd 下跑一条 shell 命令。返回 {ok, stdout, stderr, returncode}；超时 ok=False。

        工作区带 `.venv` 时（spec-0009/T3）注入其 PATH/VIRTUAL_ENV，使命令命中该 venv。
        """
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._env(),
            )
        except subprocess.TimeoutExpired as e:
            return {
                "ok": False,
                "error": "timeout",
                "stdout": (e.stdout or "")[:_MAX_OUTPUT] if isinstance(e.stdout, str) else "",
                "stderr": (e.stderr or "")[:_MAX_OUTPUT] if isinstance(e.stderr, str) else "",
                "returncode": None,
            }
        return {
            "ok": True,
            "stdout": proc.stdout[:_MAX_OUTPUT],
            "stderr": proc.stderr[:_MAX_OUTPUT],
            "returncode": proc.returncode,
        }

    def cleanup(self) -> None:
        """只清理自建的 tempdir；外部传入的 workspace 不动（归调用方/0008-T1 管理）。"""
        if self._owns_tmp:
            shutil.rmtree(self.cwd, ignore_errors=True)
