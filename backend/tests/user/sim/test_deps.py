# spec-0009/T3：依赖供给（ensure_deps 执行 setup）+ Sandbox 探测 .venv 注入 PATH。
"""无网络单测——setup 用 mkdir/echo 等 stdlib-only 命令模拟「备环境」，不真跑 pip。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.deps import SetupError, ensure_deps
from auto_designer.user.sim.sandbox import Sandbox


def test_empty_setup_is_noop(tmp_path: Path) -> None:
    """setup 为空 → 空操作、不建 .venv（既有 fixture/empty 场景零回归）。"""
    ensure_deps(str(tmp_path), WorkspaceSpec(fixture="x"))  # setup 缺省 []
    assert not (tmp_path / ".venv").exists()


def test_setup_runs_commands_in_workspace_cwd(tmp_path: Path) -> None:
    """setup 逐条在 workspace_dir 为 cwd 执行（模拟建 .venv 目录 + 落 marker）。"""
    spec = WorkspaceSpec(fixture="x", setup=["mkdir -p .venv/bin", "echo ok > marker.txt"])
    ensure_deps(str(tmp_path), spec)
    assert (tmp_path / ".venv" / "bin").is_dir()
    assert (tmp_path / "marker.txt").read_text().strip() == "ok"


def test_setup_failure_raises_with_diagnostics(tmp_path: Path) -> None:
    """某命令非零退出 → SetupError，消息含该命令与 stderr。"""
    spec = WorkspaceSpec(fixture="x", setup=["echo boom 1>&2; exit 3"])
    with pytest.raises(SetupError) as ei:
        ensure_deps(str(tmp_path), spec)
    msg = str(ei.value)
    assert "exit 3" in msg  # 附出错命令
    assert "boom" in msg  # 附 stderr


def test_setup_idempotent_reentry(tmp_path: Path) -> None:
    """幂等命令（mkdir -p）重复调不报错——为跨局重入留门。"""
    spec = WorkspaceSpec(fixture="x", setup=["mkdir -p .venv/bin"])
    ensure_deps(str(tmp_path), spec)
    ensure_deps(str(tmp_path), spec)  # 不抛
    assert (tmp_path / ".venv" / "bin").is_dir()


def test_sandbox_injects_venv_when_present(tmp_path: Path) -> None:
    """工作区含 .venv/bin → run 注入 VIRTUAL_ENV 且 PATH 前置该 bin。"""
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    sb = Sandbox(workspace=str(tmp_path))
    venv = str((tmp_path / ".venv").resolve())
    bindir = str((tmp_path / ".venv" / "bin").resolve())

    assert sb.run("echo $VIRTUAL_ENV")["stdout"].strip() == venv
    assert sb.run("echo $PATH")["stdout"].strip().split(":", 1)[0] == bindir


def test_sandbox_no_venv_does_not_inject(tmp_path: Path) -> None:
    """无 .venv → 不注入（_env 返回 None，退化为继承宿主 ambient）。"""
    sb = Sandbox(workspace=str(tmp_path))
    assert sb._env() is None
    bindir = str((tmp_path / ".venv" / "bin").resolve())
    assert bindir not in sb.run("echo $PATH")["stdout"]
