from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "deploy" / "vigil" / "build.sh"


def test_build_requires_both_checkout_paths() -> None:
    result = subprocess.run(["bash", str(_script())], capture_output=True, text=True)
    assert result.returncode != 0
    assert "OpenAgents 仓路径" in result.stderr
    assert "NexAU 仓路径" in result.stderr


def test_build_validates_checkouts_and_shapes_named_context(tmp_path: Path) -> None:
    openagents = tmp_path / "OpenAgents"
    nexau = tmp_path / "NexAU"
    openagents.mkdir()
    nexau.mkdir()
    (openagents / "pyproject.toml").write_text('name = "openagents"\n', encoding="utf-8")
    (nexau / "pyproject.toml").write_text('name = "nexau"\n', encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "docker.args"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$VIGIL_BUILD_TEST_LOG\"\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "VIGIL_BUILD_TEST_LOG": str(log),
        "VIGIL_PIP_INDEX_URL": "https://mirror.invalid/simple",
        "VIGIL_CLAUDE_CODE_VERSION": "9.8.7",
        "HTTPS_PROXY": "http://proxy.invalid:8080",
        "https_proxy": "http://proxy.invalid:8080",
    }

    result = subprocess.run(
        ["bash", str(_script()), str(openagents), str(nexau)],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    args = log.read_text(encoding="utf-8").splitlines()
    assert ["--build-context", f"nexau={nexau}"] == args[1:3]
    assert "PIP_INDEX_URL=https://mirror.invalid/simple" in args
    assert "CLAUDE_CODE_VERSION=9.8.7" in args
    assert "HTTPS_PROXY=http://proxy.invalid:8080" in args
    assert args[-1] == str(openagents)
