"""依赖供给：执行 WorkspaceSpec.setup 在工作区里备好依赖环境（spec-0009/T3）。

供给侧最后一环——SeedSource.provision 把文件落地后（orchestrator，launch 之前），
按 spec.setup 逐条在 workspace_dir 里执行（约定建 per-workspace `.venv` + pip 装入），
使工作区从「有文件」升级为「按其声明依赖可跑」。setup 为空即空操作（既有 fixture/
empty 场景零改动）。机制留在数据（命令）里：本模块只忠实执行 setup，不硬编码建 venv
逻辑，幂等亦交由 setup 命令/marker 判定。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shlex
import time
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.runtime import Workspace, as_runtime, utc_now

# 抛错时 stderr 截断上限（字符），避免超长日志灌爆异常信息。
_STDERR_CLIP = 4_000


class SetupError(RuntimeError):
    """setup 某命令非零退出或超时——消息附命令、returncode、截断 stderr 供诊断。"""


def prepare_task_environment(runtime: Workspace, params: dict) -> None:
    """Spec-0073/T3: rebuild at the final path; only uv's download cache is shared.

    Cache entries are published atomically by pinned uv, never used as editable
    source or a shared venv. Serializing each recipe also protects simultaneous
    cold installs. Installation copies files out of the cache explicitly.
    """
    workspace = as_runtime(runtime)
    for name in ("setup_script", "requirements_lock"):
        path = Path(params[name])
        if (
            path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != params[name + "_sha256"]
        ):
            raise SetupError(f"Frozen task preparation material changed: {name}")
    timeout = float(params.get("setup_timeout", 600))
    cache = Path(params["cache_root"]) / params["recipe_hash"]
    if cache.is_symlink() or cache.parent.is_symlink():
        raise SetupError("Linked task dependency cache")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = cache.parent / (params["recipe_hash"] + ".lock")
    if lock_path.is_symlink():
        raise SetupError("Linked task dependency cache lock")
    with lock_path.open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SetupError("Timed out waiting for task dependency cache lock") from None
                time.sleep(0.05)
        try:
            spec = WorkspaceSpec(setup=["bash " + shlex.quote(str(params["setup_script"]))])
            ensure_deps(workspace, spec, timeout=max(0.01, deadline - time.monotonic()))
            venv = Path(workspace.cwd, ".venv")
            if venv.is_symlink() or venv.resolve() != venv:
                raise SetupError(
                    "Task virtual environment must belong to its final session directory"
                )
            python = venv / "bin/python"
            if not python.is_file():
                raise SetupError("Task setup did not produce an isolated Python environment")
            probe = "import json,pathlib,sys;print(json.dumps([str(pathlib.Path(sys.prefix).resolve()),str(pathlib.Path(sys.base_prefix).resolve())]))"
            result = workspace.run(
                shlex.quote(str(python)) + " -I -c " + shlex.quote(probe),
                timeout=max(0.01, deadline - time.monotonic()),
            )
            try:
                prefix, base_prefix = json.loads(result.get("stdout", ""))
            except (ValueError, TypeError):
                raise SetupError(
                    "Task Python did not confirm its session-local virtual environment"
                ) from None
            if result.get("returncode") != 0 or prefix != str(venv) or prefix == base_prefix:
                raise SetupError(
                    "Task Python prefix differs from its final session virtual environment"
                )
            workspace.evidence["task_python_prefix"] = prefix
            workspace.evidence["setup_completed_at"] = utc_now()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
