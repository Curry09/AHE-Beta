"""Driver streams survive task failure and remote collection failure."""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext

from evaluation.harness.agent import FrozenHarnessAgent


@pytest.fixture
def agent(tmp_path):
    paths = [tmp_path / name for name in ("harness", "wheel", "lock", "python")]
    for path in paths:
        path.write_bytes(b"frozen")
    sha = hashlib.sha256(b"frozen").hexdigest()
    return FrozenHarnessAgent(
        archive=str(paths[0]),
        archive_sha256=sha,
        revision="test",
        runtime_wheel=str(paths[1]),
        runtime_sha256=sha,
        runtime_lock=str(paths[2]),
        runtime_lock_sha256=sha,
        python_archive=str(paths[3]),
        python_sha256=sha,
        workdir="auto",
        request_timeout_sec=30,
        logs_dir=tmp_path,
        model_name="openai/example",
        extra_env={"LLM_API_KEY": "test-api-secret", "LLM_BASE_URL": "https://example.com"},
    )


@pytest.mark.parametrize("return_code", [0, 1, 42])
def test_driver_streams_are_saved_before_snapshot_or_nonzero_error(agent, tmp_path, return_code):
    result = ExecResult(
        stdout="transport heartbeat\ntest-api-secret\n",
        stderr="HarnessProtocolError: stdout closed (exit=42) test-api-secret\n",
        return_code=return_code,
    )

    async def snapshot(*args, **kwargs):
        assert (tmp_path / "harness-driver-stdout.log").exists()
        assert (tmp_path / "harness-driver-stderr.log").exists()
        raise RuntimeError("Remote filesystem is full")

    environment = SimpleNamespace(
        upload_file=AsyncMock(),
        support=None,
    )
    calls = 0

    async def execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ExecResult(stdout="/app\n", return_code=0)
        if calls == 2:
            return ExecResult(return_code=0)
        if calls == 3:
            return result
        return await snapshot(*args, **kwargs)

    environment.exec = AsyncMock(side_effect=execute)
    context = AgentContext()
    if return_code:
        with pytest.raises(NonZeroAgentExitCodeError, match=f"code {return_code}"):
            asyncio.run(agent.run("Unchanged instruction", environment, context))
    else:
        asyncio.run(agent.run("Unchanged instruction", environment, context))
    assert context.metadata["return_code"] == return_code
    assert context.metadata["driver_output"]["errors"] == {}
    assert (
        tmp_path / "harness-driver-stdout.log"
    ).read_text() == "transport heartbeat\n[redacted]\n"
    stderr = (tmp_path / "harness-driver-stderr.log").read_text()
    assert "stdout closed (exit=42)" in stderr and "test-api-secret" not in stderr
    assert "[redacted]" in stderr


def test_driver_diagnostics_redact_other_known_credentials(agent, tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_TEST_TOKEN", "another-token-secret")
    result = ExecResult(stdout="test-api-secret another-token-secret", return_code=1)
    saved = agent._save_driver_output(result, "test-api-secret")
    assert saved["errors"] == {}
    assert (tmp_path / "harness-driver-stdout.log").read_text() == "[redacted] [redacted]"
    assert (tmp_path / "harness-driver-stderr.log").read_text() == ""


def test_host_diagnostic_write_failure_is_recorded_without_replacing_execution(agent, monkeypatch):
    original = Path.write_text

    def write(path, text, **kwargs):
        if path.name == "harness-driver-stdout.log":
            raise OSError("host disk full")
        return original(path, text, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    saved = agent._save_driver_output(ExecResult(stderr="real driver error", return_code=42), "key")
    assert saved["errors"] == {"stdout": "OSError"}
    assert saved["files"] == {"stderr": "harness-driver-stderr.log"}
