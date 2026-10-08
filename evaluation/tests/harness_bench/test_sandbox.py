from __future__ import annotations

import time
from pathlib import Path

from evaluation.harness_bench.providers.base import SandboxSpec
from evaluation.harness_bench.providers.local import LocalProvider


def test_local_provider_round_trip_and_cleanup(tmp_path: Path) -> None:
    provider = LocalProvider(tmp_path / "provider")
    spec = SandboxSpec("local", "sha256:test", 1, 512, 1024, 30)
    handle = provider.create(spec, env={})
    try:
        source = tmp_path / "input.txt"
        source.write_text("hello", encoding="utf-8")
        provider.upload(handle, source, "/input.txt")
        timeout_seconds = 10
        command = provider.exec_async(
            handle, "tr a-z A-Z < input.txt > output.txt", timeout_seconds=timeout_seconds
        )
        # Allow the declared budget, including login-shell startup on a busy CI runner.
        deadline = time.monotonic() + timeout_seconds
        result = provider.poll(command)
        while result is None and time.monotonic() < deadline:
            time.sleep(0.01)
            result = provider.poll(command)
        assert result is not None and result.exit_code == 0, result
        output = tmp_path / "output.txt"
        provider.download(handle, "/output.txt", output)
        assert output.read_text() == "HELLO"
    finally:
        provider.delete(handle)
    assert not provider.inspect(handle)["exists"]
