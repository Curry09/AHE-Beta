"""local-fixture SeedSource（spec-0009/T1）。

承接 0008/T1 原 workspace.materialize 的语义：把 in-repo 基线项目 fixture
（backend/seed_workspaces/<fixture>/project）每局 copytree 成一份全新隔离目录。
作为注册表的首个、默认实现（kind="local-fixture"），保证 0008 行为与既有 fixture 不变。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register
from auto_designer.user.sim.workspace import seed_workspaces_root


@register("local-fixture")
class LocalFixtureSource:
    kind = "local-fixture"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        if not spec.fixture:
            raise ValueError("local-fixture 源需要非空 spec.fixture")
        src = seed_workspaces_root() / spec.fixture / "project"
        if not src.is_dir():
            raise FileNotFoundError(f"seed 工作区 fixture 不存在：{spec.fixture}（找 {src}）")
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_")
        dest = Path(base) / spec.fixture
        shutil.copytree(src, dest)
        return str(dest.resolve())
