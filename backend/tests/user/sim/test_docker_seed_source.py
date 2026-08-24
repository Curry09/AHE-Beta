from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.models import WorkspaceSpec


def test_docker_seed_requires_image_and_instance() -> None:
    from auto_designer.user.sim import seed_source

    with pytest.raises(ValueError, match="params.image"):
        seed_source.provision(WorkspaceSpec(kind="docker-seed"))
    with pytest.raises(ValueError, match="params.instance_id"):
        seed_source.provision(
            WorkspaceSpec(kind="docker-seed", params={"image": "seed:test"})
        )
    with pytest.raises(ValueError, match="单路径段"):
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "seed:test", "instance_id": "../../workspace"},
            )
        )


def test_docker_seed_reports_create_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.sources import docker_seed

    monkeypatch.setattr(
        docker_seed.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "missing image"),
    )
    with pytest.raises(RuntimeError, match="missing image"):
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "missing:test", "instance_id": "x"},
            )
        )


def test_docker_seed_extracts_workspace_relocates_venv_and_removes_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.sources import docker_seed

    old_root = Path("/seed/build/workspace/instance-1/repo")
    calls: list[list[str]] = []

    def fake_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "create":
            return subprocess.CompletedProcess(args, 0, "container-1\n", "")
        source, destination = args[1], Path(args[2])
        if source.endswith(":/build-state.json"):
            destination.write_text(
                json.dumps(
                    {"instances": {"instance-1": {"source_path": str(old_root)}}}
                ),
                encoding="utf-8",
            )
        else:
            destination.mkdir(parents=True)
            metadata = destination / ".venv" / "lib" / "direct_url.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(str(old_root), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    removed: list[list[str]] = []
    monkeypatch.setattr(docker_seed, "_docker", fake_docker)
    monkeypatch.setattr(
        docker_seed.subprocess,
        "run",
        lambda args, **_kwargs: removed.append(args)
        or subprocess.CompletedProcess(args, 0, "", ""),
    )

    result = Path(
        seed_source.provision(
            WorkspaceSpec(
                kind="docker-seed",
                params={"image": "seed:test", "instance_id": "instance-1"},
            ),
            str(tmp_path),
        )
    )

    assert result == (tmp_path / "repo").resolve()
    assert str(old_root) not in (result / ".venv/lib/direct_url.json").read_text()
    assert str(result) in (result / ".venv/lib/direct_url.json").read_text()
    assert calls[0] == ["create", "seed:test", "/bin/true"]
    assert removed == [["docker", "rm", "container-1"]]
    assert not (tmp_path / ".seed-build-state.json").exists()
