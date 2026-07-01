"""empty SeedSource（spec-0009/T2）。

覆盖：可加性硬证据（不 import empty 模块、仅 import seed_source 即注册）、空目录隔离落地、
可选需求文档写入与 doc_name 覆盖、kind=empty 的序列化往返。
"""

from __future__ import annotations

from pathlib import Path

from auto_designer.models import WorkspaceSpec


def test_empty_auto_registered_without_importing_module() -> None:
    # 可加性硬证据：本测试不 import sources.empty，仅 import seed_source，empty 即在注册表。
    from auto_designer.user.sim import seed_source

    assert "empty" in seed_source.available_kinds()


def test_empty_provisions_empty_isolated_dir() -> None:
    from auto_designer.user.sim import seed_source

    a = seed_source.provision(WorkspaceSpec(kind="empty"))
    b = seed_source.provision(WorkspaceSpec(kind="empty"))
    assert a != b
    assert Path(a).is_dir()
    assert not any(Path(a).iterdir())  # 无 doc 时为纯空目录


def test_empty_writes_doc_and_doc_name_override() -> None:
    from auto_designer.user.sim import seed_source

    ws = seed_source.provision(WorkspaceSpec(kind="empty", params={"doc": "build X"}))
    assert (Path(ws) / "SPEC.md").read_text() == "build X"

    ws2 = seed_source.provision(
        WorkspaceSpec(kind="empty", params={"doc": "y", "doc_name": "REQUIREMENTS.md"})
    )
    assert (Path(ws2) / "REQUIREMENTS.md").read_text() == "y"


def test_empty_spec_roundtrip() -> None:
    e = WorkspaceSpec(kind="empty", params={"doc": "d"})
    assert WorkspaceSpec.from_dict(e.to_dict()) == e
