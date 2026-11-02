"""内层用户 agent 的最小执行 sandbox（spec-0008/T2）。

以一个工作目录为 cwd（来自 0008/T1 materialize，或缺省新建空 tempdir），提供受限的
shell 执行与路径解析。所有路径相对 cwd 解析、禁止逃逸子树。

非安全 sandbox：仅最小隔离（cwd 限定 + 超时），不抗恶意代码（不做 Docker/seccomp）。
威胁模型是「用户在自己机器上跑助手提议的代码」，与生产沙箱不同；强隔离留后续。
"""

from __future__ import annotations

from ahe_beta.user.sim.runtime import Workspace, as_runtime, make_empty_runtime

# run_shell 输出截断上限（字符），防一次跑出超大输出灌爆 prompt。
_MAX_OUTPUT = 20_000


class Sandbox:
    """一个工作目录 + 受限执行。workspace 缺省时自建空 tempdir 并在 cleanup 时删除。"""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self._runtime = make_empty_runtime() if workspace is None else as_runtime(workspace)
        self._owns_tmp = workspace is None
        self.cwd = self._runtime.cwd

    def resolve(self, path: str) -> str:
        """把相对 path 解析到 cwd 子树内的绝对路径；逃逸（.. / 绝对路径）即拒。"""
        return self._runtime.resolve(path)

    def read_text(self, path: str) -> str:
        return self._runtime.read_text(path)

    def write_text(self, path: str, content: str) -> str:
        return self._runtime.write_text(path, content)

    def list_files(self, path: str = ".") -> list[str]:
        return self._runtime.list_files(path)

    def read_diff(self) -> str:
        return self._runtime.read_diff()

    def _env(self) -> dict[str, str] | None:
        """返回私有工具执行环境。

        保持与 harness shell 的默认环境一致：只共享 cwd，不自动激活 workspace 下的
        `.venv`。如果 harness 创建或使用了某个虚拟环境，它应通过显式命令（例如
        `.venv/bin/python -m pytest ...`）体现，用户私有工具也用同样命令复现。
        """
        return None

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        """在 cwd 下跑一条 shell 命令。返回 {ok, stdout, stderr, returncode}；超时 ok=False。

        命令继承宿主环境并只切换 cwd；不隐式选择/激活 workspace `.venv`。
        """
        return self._runtime.run(cmd, timeout=timeout)

    def cleanup(self) -> None:
        """只清理自建的 tempdir；外部传入的 workspace 不动（归调用方/0008-T1 管理）。"""
        if self._owns_tmp:
            self._runtime.close()
