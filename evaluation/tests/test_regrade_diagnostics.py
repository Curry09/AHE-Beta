"""Retain failure evidence without repeating a verifier or modifying its input."""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from evaluation.harbor import regrade as module


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    task = tmp_path / "task"
    task.mkdir()
    (task / "instruction.md").write_text("Produce answer.txt.")
    (task / "tests").mkdir()
    (task / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    (task / "task.toml").write_text(
        'schema_version = "1.3"\n'
        '[verifier]\nenvironment_mode = "separate"\n'
        '[verifier.environment]\ndocker_image = "example/verifier:v1"\n'
    )
    original = tmp_path / "original"
    (original / "artifacts").mkdir(parents=True)
    (original / "artifacts/answer.txt").write_bytes(b"immutable retained submission")
    environment = AsyncMock()
    environment.with_default_user = Mock(return_value=nullcontext())
    monkeypatch.setattr(
        module.EnvironmentFactory, "create_environment_from_config", Mock(return_value=environment)
    )
    handler = AsyncMock()
    monkeypatch.setattr(module, "ArtifactHandler", Mock(return_value=handler))
    verifier = AsyncMock()
    verifier.verify.return_value = SimpleNamespace(rewards={"reward": 1})
    monkeypatch.setattr(
        module.VerifierFactory, "create_verifier_from_config", Mock(return_value=verifier)
    )
    return SimpleNamespace(
        task=task,
        original=original,
        destination=tmp_path / "regrade",
        environment=environment,
        handler=handler,
        verifier=verifier,
        job={"environment": {"type": "docker"}, "agents": [{}], "verifier": {"env": {}}},
    )


@pytest.mark.parametrize("phase", ["environment_start", "artifact_upload", "verifier_execution"])
def test_regrade_failure_keeps_redacted_cause_and_phase(recovery, monkeypatch, phase):
    secret = "synthetic-credential-for-test"
    monkeypatch.setenv("test_Api_Key", secret)
    try:
        try:
            raise OSError(f"response stream reset with {secret}")
        except OSError as cause:
            raise RuntimeError(f"command wait failed with {secret}") from cause
    except RuntimeError as error:
        failure = error
    operation = {
        "environment_start": recovery.environment.start,
        "artifact_upload": recovery.handler.upload_artifacts,
        "verifier_execution": recovery.verifier.verify,
    }[phase]
    operation.side_effect = failure
    original = module.artifact_hashes(recovery.original / "artifacts")
    result = asyncio.run(
        module.regrade(recovery.task, recovery.original, recovery.destination, recovery.job)
    )
    persisted = (recovery.destination / "regrade.json").read_text()
    assert secret not in persisted
    assert "[redacted]" in persisted
    assert result["phase"] == phase
    assert result["exception_type"] == "RuntimeError"
    assert "OSError" in result["exception_traceback"]
    assert "response stream reset" in result["exception_traceback"]
    assert result["rewards"] is None
    assert result["actor_model_requests"] == 0
    assert result["artifacts_unchanged"]
    assert module.artifact_hashes(recovery.original / "artifacts") == original
    operation.assert_awaited_once()
    recovery.environment.stop.assert_awaited_once_with(True)
    assert recovery.verifier.verify.await_count == (1 if phase == "verifier_execution" else 0)


def test_cleanup_error_is_persisted_without_hiding_original_failure(recovery):
    recovery.verifier.verify.side_effect = RuntimeError("verifier stream reset")
    recovery.environment.stop.side_effect = OSError("provider cleanup failed")
    with pytest.raises(OSError, match="provider cleanup failed"):
        asyncio.run(
            module.regrade(recovery.task, recovery.original, recovery.destination, recovery.job)
        )
    result = json.loads((recovery.destination / "regrade.json").read_text())
    assert result["phase"] == "verifier_execution"
    assert result["exception_message"] == "verifier stream reset"
    assert result["cleanup_failure"]["phase"] == "environment_cleanup"
    assert result["cleanup_failure"]["exception_type"] == "OSError"
    assert result["cleanup_failure"]["exception_message"] == "provider cleanup failed"
    assert result["artifacts_unchanged"]
    recovery.verifier.verify.assert_awaited_once()
    recovery.environment.stop.assert_awaited_once_with(True)
