"""SeedSource registry + local-fixture implementation (spec-0009/T1).

Coverage: automatic discovery and registration, kind dispatch and error on unknown kind, local-fixture can run + isolate + error on missing fixture,
WorkspaceSpec kind/params defaults and serialization backward compatible.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ahe_beta.models import WorkspaceSpec


def test_local_fixture_auto_registered() -> None:
    # Do not manually import sources.local_fixture; importing seed_source alone should trigger automatic discovery and registration.
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
    assert "local-fixture" in msg  # Error message lists registered kinds


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
    # Default kind/empty params not included in keys, preserving old 0008 serialization shape.
    assert spec.to_dict() == {"fixture": "billing-split", "setup": []}
    assert WorkspaceSpec.from_dict(spec.to_dict()) == spec

    # Old dict (no kind/params) → defaults, behavior unchanged.
    old = WorkspaceSpec.from_dict({"fixture": "billing-split"})
    assert old.kind == "local-fixture" and old.params == {}

    # With kind/params, round-trip consistency.
    e = WorkspaceSpec(kind="empty", params={"doc": "hi"})
    assert e.to_dict()["kind"] == "empty"
    assert e.to_dict()["params"] == {"doc": "hi"}
    assert WorkspaceSpec.from_dict(e.to_dict()) == e
