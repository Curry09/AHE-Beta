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
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$VIGIL_BUILD_TEST_LOG"\n',
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


def test_hosted_build_requires_an_explicit_non_latest_tag(tmp_path: Path) -> None:
    for tag in ("", "ahe-beta-vigil", "ahe-beta-vigil:latest"):
        result = subprocess.run(
            ["bash", str(_script()), str(tmp_path), str(tmp_path)],
            env={
                **os.environ,
                "VIGIL_OBSERVATION_PROFILE": "gitea-com-r2-v1",
                "VIGIL_IMAGE_TAG": tag,
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "禁止 latest" in result.stderr


def test_hosted_build_validates_actual_image_and_records_dirty_source(tmp_path: Path) -> None:
    import json

    source_paths = []
    for name in ("openagents", "nexau"):
        source = tmp_path / name
        source.mkdir()
        (source / "pyproject.toml").write_text(f'name = "{name}"\n')
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.test",
                "commit",
                "-qm",
                "test: seed",
            ],
            check=True,
        )
        source_paths.append(source)
    (source_paths[0] / "reader.py").write_text("# uncommitted reader\n")
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    fake_docker = bin_path / "docker"
    fake_docker.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ["DOCKER_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "build" and os.environ.get("MUTATE_SOURCE"):
    with open(os.environ["MUTATE_SOURCE"], "a") as f:
        f.write("# changed during build")
if sys.argv[1:3] == ["image", "inspect"]:
    print("sha256:" + "a" * 64)
elif sys.argv[1] == "run":
    print(os.environ["CAPABILITIES"])
""")
    fake_docker.chmod(0o755)
    capabilities = {
        "schema": "openagents-observation-reader-capabilities-v1",
        "marker": "auto-designer:observation-evidence-v1",
        "encodings": ["gzip", "zip"],
        "zip_profile": "single-evidence-json-v1",
        "download_policies": ["same-origin-v1", "gitea-com-r2-v1"],
        "max_transfer_bytes": 4_000_000,
        "max_expanded_bytes": 24_000_000,
    }
    record = tmp_path / "record.json"
    log = tmp_path / "docker.jsonl"
    env = {
        **os.environ,
        "PATH": f"{bin_path}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log),
        "CAPABILITIES": json.dumps(capabilities),
        "VIGIL_OBSERVATION_PROFILE": "gitea-com-r2-v1",
        "VIGIL_IMAGE_TAG": "reader:hosted-test",
        "VIGIL_OBSERVATION_RECORD": str(record),
    }
    command = ["bash", str(_script()), *map(str, source_paths)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    saved = json.loads(record.read_text())
    assert saved["image_id"] == "sha256:" + "a" * 64
    assert saved["openagents"]["dirty"] is True
    assert saved["nexau"]["dirty"] is False
    assert saved["capabilities"] == capabilities
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    run = next(call for call in calls if call[0] == "run")
    assert run[run.index("--network") + 1] == "none"
    assert "OPENAGENTS_NO_SELF_UPDATE=1" in run
    assert run[-3:] == [saved["image_id"], "observation-capabilities", "--json"]
    original_digest = saved["openagents"]["source_sha256"]
    record.unlink()
    (source_paths[0] / "reader.py").write_text("# changed reader at same HEAD\n")
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(record.read_text())["openagents"]["source_sha256"] != original_digest
    record.unlink()
    capabilities["encodings"] = ["gzip"]
    env["CAPABILITIES"] = json.dumps(capabilities)
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not record.exists()
    assert "未通过托管证据" in result.stderr

    env["CAPABILITIES"] = json.dumps({**capabilities, "encodings": ["gzip", "zip"]})
    env["MUTATE_SOURCE"] = str(source_paths[0] / "reader.py")
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert not record.exists()
    assert "构建期间源码发生变化" in result.stderr
