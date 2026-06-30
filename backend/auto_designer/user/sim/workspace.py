"""seed 工作区落地（spec-0008/T1 → spec-0009/T1）。

0008/T1 在此用本地 copytree 把 fixture 拷成隔离目录；0009/T1 把该机制抽到可插拔的
`SeedSource` 注册表（见 seed_source.py + sources/local_fixture.py）。本模块退化为：
  - `seed_workspaces_root()`：fixture 资产根的共用 helper（local-fixture 源复用）；
  - `materialize()`：委托注册表 `provision` 的兼容壳，使 0008 调用点（loop/sim_user）零改动。
"""

from __future__ import annotations

from pathlib import Path

from auto_designer.models import WorkspaceSpec


def seed_workspaces_root() -> Path:
    """backend/seed_workspaces/ 的绝对路径（本文件位于 backend/auto_designer/user/sim/）。"""
    return Path(__file__).resolve().parents[3] / "seed_workspaces"


def materialize(spec: WorkspaceSpec, dest_root: str | None = None) -> str:
    """兼容壳：按 spec.kind 委托可插拔 SeedSource 注册表，返回隔离工作区目录绝对路径。

    延迟 import 打破潜在环：seed_source 自动发现会 import local_fixture，而后者依赖本模块的
    seed_workspaces_root；本模块顶层故不 import seed_source。
    """
    from auto_designer.user.sim.seed_source import provision

    return provision(spec, dest_root)
