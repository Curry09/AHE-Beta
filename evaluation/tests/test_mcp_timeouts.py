"""A slow official ARE wait must finish before its transport deadlines."""

import asyncio
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.benchmarks.harbor_index.support import mcp_stdio_client
from evaluation.benchmarks.harbor_index.support.are_sidecar import AreSidecar
from evaluation.benchmarks.harbor_index.support.mcp_timeouts import transport_timeouts


def test_shell_wait_receives_response_after_old_300_second_boundary(tmp_path, monkeypatch, capsys):
    from evaluation.benchmarks.harbor_index.support import mcp_timeouts

    root = tmp_path / "mailbox"
    (root / "requests").mkdir(parents=True)
    (root / "responses").mkdir()
    clock = [0.0]
    original_path = Path
    monkeypatch.setattr(
        "pathlib.Path", lambda value: root if value == "/opt/harbor-mcp" else original_path(value)
    )
    monkeypatch.setattr("time.monotonic", lambda: clock[0])

    def sleep(seconds):
        clock[0] += seconds
        if clock[0] > 301:
            request = next((root / "requests").glob("*.json"))
            (root / "responses" / request.name).write_text(
                json.dumps({"isError": False, "content": [{"type": "text", "text": "completed"}]})
            )

    monkeypatch.setattr("time.sleep", sleep)
    monkeypatch.setitem(sys.modules, "mcp_timeouts", mcp_timeouts)
    monkeypatch.setattr(
        sys, "argv", ["client.py", "are_wait_for_notification", '{"timeout_seconds":300}']
    )
    script = original_path(mcp_stdio_client.__file__).with_name("mcp_shell_client.py")
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(script), run_name="__main__")
    assert stopped.value.code == 0
    assert json.loads(capsys.readouterr().out)["content"][0]["text"] == "completed"
    assert clock[0] > 300
    request = json.loads(next((root / "requests").glob("*.json")).read_text())
    assert request == {"tool": "are_wait_for_notification", "arguments": {"timeout_seconds": 300}}


def test_sidecar_and_stdio_allow_official_wait_safety_cap(monkeypatch):
    args = {"timeout_seconds": 300}
    call, mailbox, stdio = transport_timeouts("are_wait_for_notification", args)
    assert 4 * 300 < call < mailbox < stdio
    sidecar = AreSidecar(SimpleNamespace())
    sidecar.child = SimpleNamespace(
        exec=AsyncMock(
            return_value=SimpleNamespace(return_code=0, stdout='{"isError":false}', stderr="")
        )
    )
    response = asyncio.run(sidecar.call({"tool": "are_wait_for_notification", "arguments": args}))
    assert response == {"isError": False}
    assert sidecar.child.exec.await_args.kwargs["timeout_sec"] == call
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stdout='{"isError":false,"content":[]}')

    monkeypatch.setattr(mcp_stdio_client.subprocess, "run", run)
    assert mcp_stdio_client.forward("are_wait_for_notification", args)["isError"] is False
    assert calls[0]["timeout"] == stdio


def test_task_cancellation_still_interrupts_inflight_mcp_call():
    async def exercise():
        started = asyncio.Event()

        async def exec_command(*args, **kwargs):
            started.set()
            await asyncio.Future()

        sidecar = AreSidecar(SimpleNamespace())
        sidecar.child = SimpleNamespace(exec=exec_command)
        call = asyncio.create_task(
            sidecar.call(
                {"tool": "are_wait_for_notification", "arguments": {"timeout_seconds": 300}}
            )
        )
        await started.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

    asyncio.run(exercise())


def test_mcp_transport_loss_preserves_artifacts_but_invalidates_trial(tmp_path):
    async def exercise():
        sidecar = AreSidecar(SimpleNamespace())
        sidecar.failure = "TimeoutException"
        sidecar.child = SimpleNamespace()
        sidecar._io = AsyncMock(return_value=b"retained official event log")
        with pytest.raises(RuntimeError, match="MCP transport infrastructure failed"):
            await sidecar.collect()
        # Event log and provenance are both collected before invalidation.
        assert sidecar._io.await_count == 4

    asyncio.run(exercise())


@pytest.mark.parametrize("verdict", ["PASSED", "FAILED"])
def test_swt_score_requires_completed_official_parser(tmp_path, verdict):
    from evaluation.benchmarks.harbor_index.grading import grade_issues

    (tmp_path / "test-stdout.txt").write_text("Official tests completed")
    (tmp_path / "parser_output.txt").write_text(
        "SWTBench results starts here\n" + verdict + "\nSWTBench results ends here\n"
    )
    assert (
        grade_issues(
            "swtbenchverified-test-runserver-zero-address",
            {"reward": int(verdict == "PASSED")},
            tmp_path,
        )
        == []
    )
    (tmp_path / "parser_output.txt").write_text("ModuleNotFoundError: No module named 'unidiff'")
    assert grade_issues("swtbenchverified-test-runserver-zero-address", {"reward": 0}, tmp_path)


def test_empty_candidate_patch_remains_a_legitimate_swt_zero(tmp_path):
    from evaluation.benchmarks.harbor_index.grading import grade_issues

    (tmp_path / "test-stdout.txt").write_text(
        "ERROR: empty /tmp/agent.patch (agent wrote no test changes)"
    )
    assert (
        grade_issues("swtbenchverified-test-runserver-zero-address", {"reward": 0}, tmp_path) == []
    )
