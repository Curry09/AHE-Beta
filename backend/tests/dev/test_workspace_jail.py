"""WorkspaceJailMiddleware 单测：文件工具/bash 越界（含读 trace）被拒、仓内操作放行。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nexau.archs.main_sub.execution.hooks import ToolCallParams

from auto_designer.dev.workspace_jail import (
    WorkspaceJailMiddleware,
    _escapes,
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
    return isinstance(result, dict) and result.get("error", {}).get("type") == "WORKSPACE_JAIL_DENIED"


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
    # trace 目录名正则兜底
    assert _shell_offender(work, "cat ../../data/sessions/1.json") is not None
    assert _shell_offender(work, "ls ../harness_runs") is not None
    # 逐 token 越界扫描
    assert _shell_offender(work, "head /etc/hosts") is not None
    # 仓内命令放行
    assert _shell_offender(work, "git log --oneline -5") is None
    assert _shell_offender(work, "pytest -q && git status") is None
    assert _shell_offender(work, "grep sessions agents/main.md") is None  # sessions 作搜索词不误伤


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
    result, ran = _run(mw, _params(work, "run_shell_command", {"command": "git add -A && git commit -m x"}))
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
        _params(work, "replace", {"file_path": "entry.py", "old_string": "a", "new_string": "../x"}),
    )
    assert ok == "REAL_TOOL_RAN" and ok_ran is True


def test_wrap_no_sandbox_allows(tmp_path: Path) -> None:
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(None, "read_file", {"file_path": "../../data/sessions/1.json"}))
    assert result == "REAL_TOOL_RAN" and ran is True  # 无 sandbox 无从判定，不改既有行为
