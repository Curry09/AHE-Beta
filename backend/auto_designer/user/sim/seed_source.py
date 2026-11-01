"""可插拔的种子工作区供给接缝（spec-0009/T1）。

把 0008/T1 写死在 workspace.materialize 里的「本地 copytree」一条路，抽象为按
`WorkspaceSpec.kind` 注册分派的 `SeedSource`：供给侧可独立演进，消费港口
（SeedScenario.description + 被 Sandbox 当 cwd 的工作区目录）保持冻结。

注册机制：各 source 实现以 `@register("<kind>")` 自注册到模块级 `_REGISTRY`；本模块在
import 期遍历 `sources/` 子包逐一 import，触发自注册——故「新增一个源 = 在 sources/ 落一个
模块」，无需改本文件（spec-0009/T2 的 empty 源即据此接入）。

非目标（留下游 spec）：依赖供给/环境构建、容器化「可运行句柄」运行时、git@commit 取数、
Oracle 客观判分。本组港口保持「目录 + 本地 shell」不变。
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Protocol

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.runtime import Workspace


class SeedSource(Protocol):
    """供给一个隔离工作区目录的实现协议。

    `kind` 为注册键；`provision` 据 spec 落地一个全新隔离目录并返回其绝对路径
    （供 Sandbox 当 cwd）。每次调用须互不污染。
    """

    kind: str

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace: ...


_REGISTRY: dict[str, SeedSource] = {}


def register(kind: str):
    """类装饰器：实例化该 source 并以 `kind` 注册到 `_REGISTRY`。"""

    def deco(source_cls):
        _REGISTRY[kind] = source_cls()
        return source_cls

    return deco


def available_kinds() -> list[str]:
    """已注册的全部 kind（排序，供错误消息与自检）。"""
    return sorted(_REGISTRY)


def get_source(kind: str) -> SeedSource:
    """按 kind 取 source；未注册抛 ValueError 并列出已注册 kind。"""
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise ValueError(f"未知 seed source kind={kind!r}；已注册：{available_kinds()}") from None


def provision(spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace:
    """顶层分派：本地源返回目录，容器源返回显式生命周期的 runtime。"""
    return get_source(spec.kind).provision(spec, dest_root)


def resume_collection(
    *, binding: dict, expected_provenance: dict, spec: WorkspaceSpec
) -> Workspace:
    """Dispatch recovery through the same frozen source registry, without provisioning an Actor."""
    resume = getattr(get_source(binding.get("kind")), "resume_collection", None)
    if not callable(resume):
        raise ValueError("This workspace source has no completed-Actor collection recovery")
    if binding["kind"] != spec.kind:
        raise ValueError("Collection recovery source differs from its frozen workspace")
    return resume(binding=binding, expected_provenance=expected_provenance, spec=spec)


def release_collection(*, binding: dict, expected_provenance: dict, spec: WorkspaceSpec) -> None:
    """Release only a source's already-frozen original resources."""
    release = getattr(get_source(binding.get("kind")), "release_collection", None)
    if not callable(release):
        raise ValueError("This workspace source has no frozen collection release capability")
    if binding["kind"] != spec.kind:
        raise ValueError("Collection release source differs from its frozen workspace")
    release(binding=binding, expected_provenance=expected_provenance, spec=spec)


def _discover() -> None:
    """import 期遍历 sources/ 子包逐一 import，触发各 source 的 @register 自注册。"""
    from auto_designer.user.sim import sources as _sources_pkg

    for mod in pkgutil.iter_modules(_sources_pkg.__path__):
        importlib.import_module(f"{_sources_pkg.__name__}.{mod.name}")


_discover()
