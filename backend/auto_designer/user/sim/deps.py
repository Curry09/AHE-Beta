"""依赖供给：执行 WorkspaceSpec.setup 在工作区里备好依赖环境（spec-0009/T3）。

供给侧最后一环——SeedSource.provision 把文件落地后（orchestrator，launch 之前），
按 spec.setup 逐条在 workspace_dir 里执行（约定建 per-workspace `.venv` + pip 装入），
使工作区从「有文件」升级为「按其声明依赖可跑」。setup 为空即空操作（既有 fixture/
empty 场景零改动）。机制留在数据（命令）里：本模块只忠实执行 setup，不硬编码建 venv
逻辑，幂等亦交由 setup 命令/marker 判定。
"""

from __future__ import annotations

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.runtime import Workspace, as_runtime

# 抛错时 stderr 截断上限（字符），避免超长日志灌爆异常信息。
_STDERR_CLIP = 4_000


class SetupError(RuntimeError):
    """setup 某命令非零退出或超时——消息附命令、returncode、截断 stderr 供诊断。"""


def ensure_deps(workspace_dir: Workspace, spec: WorkspaceSpec, *, timeout: float = 600.0) -> None:
    """按 spec.setup 在 workspace_dir 里备好依赖；setup 空则空操作。

    以 workspace_dir 为 cwd 逐条 subprocess 执行 setup 命令（shell=True，捕获输出），
    非零退出或超时抛 SetupError（附命令 + stderr）。约定 setup 自建 `.venv` 并 pip
    装入依赖——本函数不硬编码 venv 逻辑，只忠实执行；消费侧 Sandbox 再探测 `.venv`。
    """
    if not spec.setup:
        return
    runtime = as_runtime(workspace_dir)
    for cmd in spec.setup:
        result = runtime.run(cmd, timeout=timeout)
        if result.get("status") == "timed_out":
            raise SetupError(
                f"setup 命令超时（>{timeout}s）：{cmd!r}\n"
                f"stderr: {str(result.get('stderr') or '')[:_STDERR_CLIP]}"
            )
        if result.get("returncode") != 0:
            raise SetupError(
                f"setup 命令失败（rc={result.get('returncode')}）：{cmd!r}\n"
                f"stderr: {str(result.get('stderr') or '')[:_STDERR_CLIP]}"
            )
