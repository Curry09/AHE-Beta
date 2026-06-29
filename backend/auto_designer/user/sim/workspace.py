"""seed 工作区落地（spec-0008/T1）。

把 SeedScenario.workspace 指向的 in-repo 基线项目 fixture（backend/seed_workspaces/<fixture>/project）
每局拷成一份全新隔离目录，作为内层 tool-using 用户 agent 的 sandbox cwd。

MVP 边界：仅本地 fixture + copytree（stdlib-only 场景，无第三方依赖）。WorkspaceSpec.setup 命令钩子
本轮仅占位、不执行；依赖供给（cached venv / pip）留作后续。与 harness 完全解耦：工作区只服务
用户侧自有核实，且不含 gold 测试（held-out 红线无关）。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec


def seed_workspaces_root() -> Path:
    """backend/seed_workspaces/ 的绝对路径（本文件位于 backend/auto_designer/user/sim/）。"""
    return Path(__file__).resolve().parents[3] / "seed_workspaces"


def materialize(spec: WorkspaceSpec, dest_root: str | None = None) -> str:
    """把 fixture 的 project/ 拷到一个全新隔离目录，返回该目录（项目根 = sandbox 的 cwd）绝对路径。

    每次调用得到互不干扰的新拷贝；dest_root 缺省用 tempfile.mkdtemp()。
    setup 钩子本轮不执行（占位）。
    """
    src = seed_workspaces_root() / spec.fixture / "project"
    if not src.is_dir():
        raise FileNotFoundError(f"seed 工作区 fixture 不存在：{spec.fixture}（找 {src}）")
    base = dest_root or tempfile.mkdtemp(prefix="sim_ws_")
    dest = Path(base) / spec.fixture
    shutil.copytree(src, dest)
    return str(dest.resolve())
