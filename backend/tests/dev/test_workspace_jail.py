"""WorkspaceJailMiddleware 单测：文件工具/bash 越界（含读 trace）被拒、仓内操作放行。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("nexau")  # CI 无 nexau 时跳过本模块（对齐 test_live.py 惯例）

from nexau.archs.main_sub.execution.hooks import ToolCallParams  # noqa: E402

from auto_designer.dev.workspace_jail import (  # noqa: E402
    WorkspaceJailMiddleware,
    _escapes,
    _nexau_repo_root,
    _nexau_runtime_read_roots,
    _shell_offender,
)


class _FakeSandbox:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = str(work_dir)


def _params(work_dir: Path | None, tool: str, parameters: dict[str, Any]) -> ToolCallParams:
    sandbox = _FakeSandbox(work_dir) if work_dir is not None else None
    return ToolCallParams(
        agent_state=None,  # 中间件不用
        sandbox=sandbox,  # type: ignore[arg-type]
        tool_name=tool,
        parameters=parameters,
        tool_call_id="t1",
        execution_params={},
    )


def _run(mw: WorkspaceJailMiddleware, params: ToolCallParams) -> tuple[Any, bool]:
    """跑 wrap_tool_call；返回 (结果, call_next 是否被调用)。"""
    called = {"v": False}

    def call_next(p: ToolCallParams) -> str:  # noqa: ARG001
        called["v"] = True
        return "REAL_TOOL_RAN"

    return mw.wrap_tool_call(params, call_next), called["v"]


def _denied(result: Any) -> bool:
    return (
        isinstance(result, dict) and result.get("error", {}).get("type") == "WORKSPACE_JAIL_DENIED"
    )


def test_escapes_detects_out_of_workdir(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    assert _escapes(work, "entry.py") is False
    assert _escapes(work, "agents/main.md") is False
    assert _escapes(work, "foo/../bar") is False  # 仓内绕一圈仍在内
    assert _escapes(work, "../sessions/x.json") is True
    assert _escapes(work, "../../data/sessions/x.json") is True
    assert _escapes(work, "/etc/passwd") is True


def test_shell_offender_flags_trace_and_escape(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    roots = [work]
    # trace 目录名正则兜底
    assert _shell_offender(work, "cat ../../data/sessions/1.json", roots) is not None
    assert _shell_offender(work, "ls ../harness_runs", roots) is not None
    # 逐 token 越界扫描
    assert _shell_offender(work, "head /etc/hosts", roots) is not None
    # 仓内命令放行
    assert _shell_offender(work, "git log --oneline -5", roots) is None
    assert _shell_offender(work, "pytest -q && git status", roots) is None
    assert (
        _shell_offender(work, "grep sessions agents/main.md", roots) is None
    )  # sessions 作搜索词不误伤


def test_shell_offender_flags_heredoc_redirect_escape(tmp_path: Path) -> None:
    """heredoc 绕过洞回归：`cat > /仓外 <<EOF … EOF` 的重定向目标必须被抓，正文不误伤。"""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    roots = [work]
    outside = tmp_path / "developer_agent" / "MANUAL.md"
    # 越界重定向目标（含 heredoc）：旧实现整条放行、成绕过口；现在必须拒
    cmd_abs = f"cat > {outside} <<'EOF'\nsome harness content\nEOF"
    assert _shell_offender(work, cmd_abs, roots) is not None
    cmd_rel = "cat > ../../evil.md <<EOF\nx\nEOF"
    assert _shell_offender(work, cmd_rel, roots) is not None
    # 仓内重定向目标（含 heredoc）放行——写自己仓内文件合法
    cmd_in = "cat > MANUAL.md <<EOF\nharness manual body\nEOF"
    assert _shell_offender(work, cmd_in, roots) is None
    # heredoc 正文里出现 `../` / 绝对路径只是**内容**，不该误伤（重定向目标在仓内）
    cmd_body_noise = "cat > notes.md <<EOF\nsee ../../data/x and /etc/passwd\nEOF"
    assert _shell_offender(work, cmd_body_noise, roots) is None


def test_wrap_allows_nexau_bash_tool_results_read(tmp_path: Path) -> None:
    """边界补全：NexAU bash/tool 临时输出只读放行；写仍拒；轨迹仍拒。"""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    runtime_roots = _nexau_runtime_read_roots()
    assert runtime_roots, "应解析到至少一处 NexAU 运行时临时根"
    bash_root = runtime_roots[0]
    bash_root.mkdir(parents=True, exist_ok=True)
    artifact = bash_root / "deadbeef" / "stderr.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("err\n", encoding="utf-8")

    mw = WorkspaceJailMiddleware()
    ok, ran = _run(mw, _params(work, "read_file", {"file_path": str(artifact)}))
    assert ok == "REAL_TOOL_RAN" and ran is True

    # 写工具不能往临时目录写（可写范围仍只有 harness 仓）
    bad_w, bad_w_ran = _run(
        mw, _params(work, "write_file", {"file_path": str(artifact), "content": "x"})
    )
    assert _denied(bad_w) and bad_w_ran is False

    # shell 读临时输出放行；读 sessions 仍拒
    sh_ok, sh_ran = _run(
        mw, _params(work, "run_shell_command", {"command": f"head -1 {artifact}"})
    )
    assert sh_ok == "REAL_TOOL_RAN" and sh_ran is True
    sh_bad, sh_bad_ran = _run(
        mw, _params(work, "run_shell_command", {"command": "cat ../../data/sessions/1.json"})
    )
    assert _denied(sh_bad) and sh_bad_ran is False


def test_wrap_allows_nexau_read_denies_nexau_write(tmp_path: Path) -> None:
    """边界：NexAU 源码只读放行；写 NexAU / 读轨迹仍拒。"""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    nexau_root = _nexau_repo_root()
    if nexau_root is None:
        pytest.skip("环境无 nexau，跳过只读放行断言")
    mw = WorkspaceJailMiddleware()
    nexau_init = nexau_root / "nexau" / "__init__.py"
    assert nexau_init.is_file()
    ok, ran = _run(mw, _params(work, "read_file", {"file_path": str(nexau_init)}))
    assert ok == "REAL_TOOL_RAN" and ran is True
    bad, bad_ran = _run(
        mw, _params(work, "write_file", {"file_path": str(nexau_init), "content": "x"})
    )
    assert _denied(bad) and bad_ran is False
    # shell 读 NexAU 放行；读 trace 仍拒
    sh_ok, sh_ran = _run(
        mw, _params(work, "run_shell_command", {"command": f"head -5 {nexau_init}"})
    )
    assert sh_ok == "REAL_TOOL_RAN" and sh_ran is True


def test_wrap_denies_read_file_escape(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(work, "read_file", {"file_path": "../../data/sessions/1.json"}))
    assert _denied(result) and ran is False  # 拒绝且真工具没跑


def test_wrap_allows_in_repo_read(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(work, "read_file", {"file_path": "agents/main.md"}))
    assert result == "REAL_TOOL_RAN" and ran is True


def test_wrap_denies_shell_trace_read(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(
        mw, _params(work, "run_shell_command", {"command": "cat ../../data/sessions/1.json"})
    )
    assert _denied(result) and ran is False


def test_wrap_allows_in_repo_shell(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(
        mw, _params(work, "run_shell_command", {"command": "git add -A && git commit -m x"})
    )
    assert result == "REAL_TOOL_RAN" and ran is True


def test_wrap_denies_write_escape(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(work, "write_file", {"file_path": "../evil.py", "content": "x"}))
    assert _denied(result) and ran is False
    # 但 replace 的 new_string 里含 ../ 只是内容、不该误伤（file_path 合法）
    ok, ok_ran = _run(
        mw,
        _params(
            work, "replace", {"file_path": "entry.py", "old_string": "a", "new_string": "../x"}
        ),
    )
    assert ok == "REAL_TOOL_RAN" and ok_ran is True


def test_wrap_no_sandbox_allows(tmp_path: Path) -> None:
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(None, "read_file", {"file_path": "../../data/sessions/1.json"}))
    assert result == "REAL_TOOL_RAN" and ran is True  # 无 sandbox 无从判定，不改既有行为
