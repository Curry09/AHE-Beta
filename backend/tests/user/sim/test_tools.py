"""Inner atomic tools and sandbox (spec-0008/T2).

Use real tempdir + small commands, do not mock subprocess. Coverage: three atomic tools, path escape prevention, timeout/non-zero code, real fixture (billing-split) execution, tool_stack D1 gating, web_search placeholder."""

from __future__ import annotations

import os
import sys

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from ahe_beta.user.sim.sandbox import Sandbox
from ahe_beta.user.sim.tools import (
    read_file,
    run_shell,
    tool_stack,
    web_search,
    write_file,
)
from ahe_beta.user.sim.workspace import materialize


def _persona(d1: D1Eval) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="p",
            d1=d1,
            d2=D2Domain(),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


# --------------------------------------------------------------------------
# Atomic tools
# --------------------------------------------------------------------------
def test_write_read_run_roundtrip() -> None:
    sb = Sandbox()
    try:
        assert write_file(sb, "a/b.txt", "hello")["ok"]
        r = read_file(sb, "a/b.txt")
        assert r["ok"] and r["content"] == "hello"
        run = run_shell(sb, "echo hi")
        assert run["ok"] and run["returncode"] == 0 and "hi" in run["stdout"]
    finally:
        sb.cleanup()


def test_path_escape_rejected() -> None:
    sb = Sandbox()
    try:
        assert read_file(sb, "../../etc/passwd")["ok"] is False
        assert write_file(sb, "/tmp/evil.txt", "x")["ok"] is False
    finally:
        sb.cleanup()


def test_run_shell_timeout_and_nonzero() -> None:
    sb = Sandbox()
    try:
        slow = run_shell(sb, f'{sys.executable} -c "import time; time.sleep(5)"', timeout=0.5)
        assert slow["ok"] is False and slow["error"] == "timeout"
        bad = run_shell(sb, "exit 3")
        assert bad["ok"] is True and bad["returncode"] == 3
    finally:
        sb.cleanup()


def test_sandbox_runs_real_fixture() -> None:
    ws = materialize(WorkspaceSpec(fixture="billing-split"))
    sb = Sandbox(workspace=ws)
    assert sb.cwd == ws.cwd  # External workspace as cwd
    run = run_shell(sb, f"{sys.executable} billing/core.py")
    assert run["ok"] and run["returncode"] == 0, run
    # External workspace not deleted by cleanup
    sb.cleanup()
    assert read_file(sb, "billing/core.py")["ok"]


def test_empty_sandbox_cleans_up_itself() -> None:
    sb = Sandbox()
    cwd = sb.cwd
    assert os.path.isdir(cwd)
    sb.cleanup()
    assert not os.path.isdir(cwd)


def test_sandbox_does_not_auto_activate_workspace_venv(tmp_path) -> None:
    bindir = tmp_path / ".venv" / "bin"
    bindir.mkdir(parents=True)
    fake_python = bindir / "python"
    fake_python.write_text("#!/bin/sh\necho fake-venv-python\n", encoding="utf-8")
    fake_python.chmod(0o755)

    sb = Sandbox(workspace=str(tmp_path))
    run = run_shell(sb, "python3 - <<'PY'\nimport sys\nprint(sys.executable)\nPY")
    assert run["ok"] and run["returncode"] == 0
    assert "fake-venv-python" not in run["stdout"]
    assert str(bindir) not in (run["stdout"] + run["stderr"])


# --------------------------------------------------------------------------
# D1 gating + placeholder
# --------------------------------------------------------------------------
def test_tool_stack_gating() -> None:
    def names(d1: D1Eval) -> list[str]:
        return [t.name for t in tool_stack(_persona(d1))]

    assert names(D1Eval.BLIND) == []
    assert names(D1Eval.SHALLOW) == ["read_file", "run_shell", "report_issue"]
    assert "write_file" in names(D1Eval.COMPETENT)
    assert "write_file" in names(D1Eval.EXPERT)
    assert "report_issue" in names(D1Eval.COMPETENT)
    assert "report_issue" in names(D1Eval.EXPERT)
    # shallow cannot obtain write_file (cannot write test suite); report_issue not bound to validation capability, shallow has it too
    assert "write_file" not in names(D1Eval.SHALLOW)


def test_web_search_placeholder() -> None:
    r = web_search("anything")
    assert r["ok"] is False and r["error"] == "not_implemented"
