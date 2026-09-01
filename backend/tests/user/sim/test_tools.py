"""内层原子工具与 sandbox（spec-0008/T2）。

用真实 tempdir + 小命令，不 mock subprocess。覆盖三原子工具、路径防逃逸、超时/非零码、
真实 fixture（billing-split）执行、tool_stack 的 D1 门控、web_search 占位。
"""

from __future__ import annotations

import os
import sys

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from auto_designer.user.sim.sandbox import Sandbox
from auto_designer.user.sim.tools import (
    read_file,
    run_shell,
    tool_stack,
    web_search,
    write_file,
)
from auto_designer.user.sim.workspace import materialize


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
# 原子工具
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
    assert sb.cwd == ws  # 外部工作区当 cwd
    run = run_shell(sb, f"{sys.executable} billing/core.py")
    assert run["ok"] and run["returncode"] == 0, run
    # 外部 workspace 不被 cleanup 删除
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
# D1 门控 + 占位
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
    # shallow 拿不到 write_file（写不出测试套件）；report_issue 不绑核实能力，shallow 也有
    assert "write_file" not in names(D1Eval.SHALLOW)


def test_web_search_placeholder() -> None:
    r = web_search("anything")
    assert r["ok"] is False and r["error"] == "not_implemented"
