"""SeedSource 注册表 + local-fixture 实现（spec-0009/T1）。

覆盖：自动发现注册、kind 分派与未知 kind 报错、local-fixture 可跑+隔离+缺 fixture 报错、
WorkspaceSpec 的 kind/params 缺省与序列化向后兼容。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ahe_beta.models import WorkspaceSpec


def test_local_fixture_auto_registered() -> None:
    # 不手动 import sources.local_fixture，仅 import seed_source 即应触发自动发现注册。
    from ahe_beta.user.sim import seed_source

    assert "local-fixture" in seed_source.available_kinds()


def test_provision_dispatch_and_unknown_kind() -> None:
    from ahe_beta.user.sim import seed_source

    ws = seed_source.provision(WorkspaceSpec(fixture="billing-split"))
    assert Path(ws).is_dir()

    with pytest.raises(ValueError) as ei:
        seed_source.provision(WorkspaceSpec(kind="does-not-exist"))
    msg = str(ei.value)
    assert "does-not-exist" in msg
    assert "local-fixture" in msg  # 错误消息列出已注册 kind


def test_local_fixture_runnable_and_isolated() -> None:
    from ahe_beta.user.sim import seed_source

    spec = WorkspaceSpec(fixture="billing-split")
    a = seed_source.provision(spec)
    b = seed_source.provision(spec)
    assert a != b
    assert (Path(a) / "billing" / "core.py").is_file()

    run = subprocess.run([sys.executable, "billing/core.py"], cwd=a, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr

    (Path(a) / "billing" / "core.py").write_text("# clobbered\n")
    assert "clobbered" not in (Path(b) / "billing" / "core.py").read_text()


def test_local_fixture_errors() -> None:
    from ahe_beta.user.sim import seed_source

    with pytest.raises(FileNotFoundError):
        seed_source.provision(WorkspaceSpec(fixture="no-such-fixture"))
    with pytest.raises(ValueError):
        seed_source.provision(WorkspaceSpec(kind="local-fixture", fixture=""))


def test_workspace_spec_kind_params_defaults_and_roundtrip() -> None:
    spec = WorkspaceSpec(fixture="billing-split")
    assert spec.kind == "local-fixture"
    assert spec.params == {}
    # 默认 kind/空 params 不落键，保持 0008 旧序列化形状。
    assert spec.to_dict() == {"fixture": "billing-split", "setup": []}
    assert WorkspaceSpec.from_dict(spec.to_dict()) == spec

    # 旧 dict（无 kind/params）→ 缺省、行为不变。
    old = WorkspaceSpec.from_dict({"fixture": "billing-split"})
    assert old.kind == "local-fixture" and old.params == {}

    # 带 kind/params 往返一致。
    e = WorkspaceSpec(kind="empty", params={"doc": "hi"})
    assert e.to_dict()["kind"] == "empty"
    assert e.to_dict()["params"] == {"doc": "hi"}
    assert WorkspaceSpec.from_dict(e.to_dict()) == e
