"""WorkspaceJailMiddleware unit test: file tools/bash cross-boundary (including trace reads) rejected, in-repository operations allowed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Skip this module when CI has no nexau (align with test_live.py convention)
pytest.importorskip("nexau")

from nexau.archs.main_sub.execution.hooks import ToolCallParams  # noqa: E402

from ahe_beta.guards.workspace_jail import (  # noqa: E402
    WorkspaceJailMiddleware,
    _escapes,
    _nexau_repo_root,
    _nexau_runtime_read_roots,
    _shell_offender,
)
from ahe_beta.usage import bind_usage_context  # noqa: E402


class _FakeSandbox:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = str(work_dir)


def _params(work_dir: Path | None, tool: str, parameters: dict[str, Any]) -> ToolCallParams:
    sandbox = _FakeSandbox(work_dir) if work_dir is not None else None
    return ToolCallParams(
        agent_state=None,  # Middleware not used
        sandbox=sandbox,  # type: ignore[arg-type]
        tool_name=tool,
        parameters=parameters,
        tool_call_id="t1",
        execution_params={},
    )


def _run(mw: WorkspaceJailMiddleware, params: ToolCallParams) -> tuple[Any, bool]:
    """Run wrap_tool_call; return (result, whether call_next was invoked)."""
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
    assert _escapes(work, "foo/../bar") is False  # Repository internal loop still stays inside
    assert _escapes(work, "../sessions/x.json") is True
    assert _escapes(work, "../../data/sessions/x.json") is True
    assert _escapes(work, "/etc/passwd") is True


def test_triager_cannot_read_generated_runtime_files(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    (work / ".openagents" / "worktrees").mkdir(parents=True)
    (work / "src").mkdir()
    middleware = WorkspaceJailMiddleware()
    with bind_usage_context(role="triager"):
        for tool, arguments in (
            ("read_file", {"file_path": str(work / ".openagents" / "vigil-queue.db")}),
            ("list_directory", {"dir_path": str(work / ".openagents" / "worktrees")}),
            ("search_file_content", {"pattern": "error", "dir_path": str(work / ".openagents")}),
            ("read_file", {"file_path": str(work / "src" / ".ruff_cache" / "entry")}),
        ):
            result, called = _run(middleware, _params(work, tool, arguments))
            assert _denied(result)
            assert not called
        result, called = _run(
            middleware, _params(work, "read_file", {"file_path": str(work / "src" / "main.py")})
        )
        assert result == "REAL_TOOL_RAN" and called
    result, called = _run(
        middleware,
        _params(work, "read_file", {"file_path": str(work / ".openagents" / "vigil-queue.db")}),
    )
    assert result == "REAL_TOOL_RAN" and called


def test_shell_offender_flags_trace_and_escape(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    roots = [work]
    # trace directory name regex fallback
    assert _shell_offender(work, "cat ../../data/sessions/1.json", roots) is not None
    assert _shell_offender(work, "ls ../harness_runs", roots) is not None
    assert _shell_offender(work, "ls ../../data/role_runs", roots) is not None
    # Token-by-token out-of-bounds scan
    assert _shell_offender(work, "head /etc/hosts", roots) is not None
    # In-repo command is allowed through
    assert _shell_offender(work, "git log --oneline -5", roots) is None
    assert _shell_offender(work, "pytest -q && git status", roots) is None
    assert (
        _shell_offender(work, "grep sessions agents/main.md", roots) is None
    )  # sessions used as a search term does not trigger a false positive


def test_shell_offender_flags_heredoc_redirect_escape(tmp_path: Path) -> None:
    """Regression test for the heredoc bypass hole: the redirect target of `cat > /outside-workspace <<EOF … EOF` must be caught; the body must not trigger a false positive."""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    roots = [work]
    outside = tmp_path / "developer_agent" / "HELP.md"
    # Out-of-bounds redirect target (including heredoc): the old implementation let the whole command through, creating a bypass hole; it must now be rejected
    cmd_abs = f"cat > {outside} <<'EOF'\nsome harness content\nEOF"
    assert _shell_offender(work, cmd_abs, roots) is not None
    cmd_rel = "cat > ../../evil.md <<EOF\nx\nEOF"
    assert _shell_offender(work, cmd_rel, roots) is not None
    # In-repo redirect target (including heredoc) is allowed — writing to files inside one's own repo is legitimate
    cmd_in = "cat > HELP.md <<EOF\nharness help body\nEOF"
    assert _shell_offender(work, cmd_in, roots) is None
    # `../` / absolute paths appearing in the heredoc body are just **content** and must not trigger a false positive (the redirect target is inside the repo)
    cmd_body_noise = "cat > notes.md <<EOF\nsee ../../data/x and /etc/passwd\nEOF"
    assert _shell_offender(work, cmd_body_noise, roots) is None


def test_wrap_allows_nexau_bash_tool_results_read(tmp_path: Path) -> None:
    """Boundary completion: NexAU bash/tool temp output is allowed for reads; writes are still rejected; trace is still rejected."""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    runtime_roots = _nexau_runtime_read_roots()
    assert runtime_roots, "Should resolve to at least one location NexAU Temporary runtime root"
    bash_root = runtime_roots[0]
    bash_root.mkdir(parents=True, exist_ok=True)
    artifact = bash_root / "deadbeef" / "stderr.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("err\n", encoding="utf-8")

    mw = WorkspaceJailMiddleware()
    ok, ran = _run(mw, _params(work, "read_file", {"file_path": str(artifact)}))
    assert ok == "REAL_TOOL_RAN" and ran is True

    # Write tools must not write to the temp directory (the writable scope is still only the harness repo)
    bad_w, bad_w_ran = _run(
        mw, _params(work, "write_file", {"file_path": str(artifact), "content": "x"})
    )
    assert _denied(bad_w) and bad_w_ran is False

    # Shell reading temp output is allowed; reading sessions is still rejected
    sh_ok, sh_ran = _run(mw, _params(work, "run_shell_command", {"command": f"head -1 {artifact}"}))
    assert sh_ok == "REAL_TOOL_RAN" and sh_ran is True
    sh_bad, sh_bad_ran = _run(
        mw, _params(work, "run_shell_command", {"command": "cat ../../data/sessions/1.json"})
    )
    assert _denied(sh_bad) and sh_bad_ran is False


def test_wrap_allows_nexau_read_denies_nexau_write(tmp_path: Path) -> None:
    """Boundary: NexAU source code is allowed for reads; writing to NexAU / reading trace is still rejected."""
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    nexau_root = _nexau_repo_root()
    if nexau_root is None:
        pytest.skip("Environment lacks nexau，Skip the read only approval assertion")
    mw = WorkspaceJailMiddleware()
    nexau_init = nexau_root / "nexau" / "__init__.py"
    assert nexau_init.is_file()
    ok, ran = _run(mw, _params(work, "read_file", {"file_path": str(nexau_init)}))
    assert ok == "REAL_TOOL_RAN" and ran is True
    bad, bad_ran = _run(
        mw, _params(work, "write_file", {"file_path": str(nexau_init), "content": "x"})
    )
    assert _denied(bad) and bad_ran is False
    # Shell reading NexAU is allowed; reading trace is still rejected
    sh_ok, sh_ran = _run(
        mw, _params(work, "run_shell_command", {"command": f"head -5 {nexau_init}"})
    )
    assert sh_ok == "REAL_TOOL_RAN" and sh_ran is True


def test_wrap_denies_read_file_escape(tmp_path: Path) -> None:
    work = (tmp_path / "harness_repo").resolve()
    work.mkdir()
    mw = WorkspaceJailMiddleware()
    result, ran = _run(mw, _params(work, "read_file", {"file_path": "../../data/sessions/1.json"}))
    assert _denied(result) and ran is False  # Rejected, and the real tool never ran
    result, ran = _run(mw, _params(work, "read_file", {"file_path": "../../data/role_runs/x.json"}))
    assert _denied(result) and ran is False


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
    # But ../ inside the replace's new_string is just content and must not trigger a false positive (file_path is legitimate)
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
    # Without a sandbox there is no basis to decide; do not change existing behavior
    assert result == "REAL_TOOL_RAN" and ran is True
