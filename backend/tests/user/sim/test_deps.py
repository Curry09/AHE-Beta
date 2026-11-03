# spec-0009/T3: dependency provisioning (ensure_deps executes setup); Sandbox shares only cwd/ambient env.
"""Offline unit tests — setup uses stdlib-only commands like mkdir/echo to simulate "environment preparation", not actually running pip."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.deps import SetupError, ensure_deps
from ahe_beta.user.sim.sandbox import Sandbox


def test_empty_setup_is_noop(tmp_path: Path) -> None:
    """Empty setup → no-op, no .venv created (existing fixture/empty scenarios have zero regression)."""
    ensure_deps(str(tmp_path), WorkspaceSpec(fixture="x"))  # setup defaults to []
    assert not (tmp_path / ".venv").exists()


def test_setup_runs_commands_in_workspace_cwd(tmp_path: Path) -> None:
    """setup commands execute sequentially with workspace_dir as cwd (simulating .venv directory creation + marker deposition)."""
    spec = WorkspaceSpec(fixture="x", setup=["mkdir -p .venv/bin", "echo ok > marker.txt"])
    ensure_deps(str(tmp_path), spec)
    assert (tmp_path / ".venv" / "bin").is_dir()
    assert (tmp_path / "marker.txt").read_text().strip() == "ok"


def test_setup_failure_raises_with_diagnostics(tmp_path: Path) -> None:
    """Non-zero exit of any command → SetupError, message includes that command and stderr."""
    spec = WorkspaceSpec(fixture="x", setup=["echo boom 1>&2; exit 3"])
    with pytest.raises(SetupError) as ei:
        ensure_deps(str(tmp_path), spec)
    msg = str(ei.value)
    assert "exit 3" in msg  # Include the failed command
    assert "boom" in msg  # Include stderr


def test_setup_idempotent_reentry(tmp_path: Path) -> None:
    """Idempotent commands (mkdir -p) do not error on repeated invocation — allowing for cross-session re-entry."""
    spec = WorkspaceSpec(fixture="x", setup=["mkdir -p .venv/bin"])
    ensure_deps(str(tmp_path), spec)
    ensure_deps(str(tmp_path), spec)  # Do not raise
    assert (tmp_path / ".venv" / "bin").is_dir()


@pytest.mark.parametrize("ambient_venv", [None, "/test-parent-venv"])
def test_sandbox_does_not_inject_venv_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ambient_venv: str | None
) -> None:
    """Workspace containing .venv/bin does not automatically modify VIRTUAL_ENV/PATH; environment selection requires explicit commands."""
    # uv run / activated shells supply VIRTUAL_ENV; inheritance is part of the contract.
    if ambient_venv is None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    else:
        monkeypatch.setenv("VIRTUAL_ENV", ambient_venv)
    ambient_path = os.environ["PATH"]
    bindir = tmp_path / ".venv" / "bin"
    bindir.mkdir(parents=True)
    fake_python = bindir / "python"
    fake_python.write_text("#!/bin/sh\necho fake-venv-python\n", encoding="utf-8")
    fake_python.chmod(0o755)

    sb = Sandbox(workspace=str(tmp_path))
    assert sb.run('printf "%s" "$VIRTUAL_ENV"')["stdout"] == (ambient_venv or "")
    assert sb.run('printf "%s" "$PATH"')["stdout"] == ambient_path
    assert str(bindir.resolve()) not in ambient_path.split(os.pathsep)

    explicit = sb.run(".venv/bin/python")
    assert explicit["stdout"].strip() == "fake-venv-python"


def test_sandbox_no_venv_does_not_inject(tmp_path: Path) -> None:
    """No .venv → do not inject (env returns None, degrading to inherited ambient)."""
    sb = Sandbox(workspace=str(tmp_path))
    assert sb._env() is None
    bindir = str((tmp_path / ".venv" / "bin").resolve())
    assert bindir not in sb.run("echo $PATH")["stdout"]
