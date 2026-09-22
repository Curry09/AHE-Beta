# Spec-0047/T3：mock Docker 的双实验隔离与 destroy 确认。
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_designer.experiment.config import compose_project, config_hash
from auto_designer.experiment.infrastructure import (
    InfrastructureError,
    destroy_stack,
    parse_compose_template,
    provision,
    render_stack,
    stop_stack,
)


def test_compose_template_has_no_global_names() -> None:
    text = parse_compose_template()
    assert "container_name:" not in text
    assert "name: auto-designer-" not in text
    assert "127.0.0.1::3000" in text
    assert "io.openagents.experiment_id" in text


def test_experiment_egress_allows_configured_wis_gateway() -> None:
    # Delivery runs inside the isolated vigil network; the host-side API probe
    # is not sufficient to prove that the configured WIS gateway is reachable.
    egress = Path(__file__).resolve().parents[2] / "deploy" / "experiment" / "egress-proxy.conf"
    assert "acl allowed_egress dstdomain .paperbypass.com" in egress.read_text(encoding="utf-8")


def test_experiment_egress_scopes_boyue_gateway_to_exact_host_and_port() -> None:
    egress = Path(__file__).resolve().parents[2] / "deploy" / "experiment" / "egress-proxy.conf"
    rules = egress.read_text(encoding="utf-8")
    assert "acl boyue_glm dst 35.220.164.252/32" in rules
    assert "acl boyue_glm_port port 3888" in rules
    rule = "http_access allow boyue_glm boyue_glm_port"
    assert rule in rules
    assert rules.index(rule) < rules.index("http_access deny all")
    assert "http_access allow all" not in rules.splitlines()


def test_two_experiments_get_distinct_projects(tmp_path: Path) -> None:
    a = {"experiment_id": "exp-a", "n": 1}
    b = {"experiment_id": "exp-b", "n": 1}
    ha, hb = config_hash(data=a), config_hash(data=b)
    assert compose_project(experiment_id="exp-a", cfg_hash=ha) != compose_project(
        experiment_id="exp-b", cfg_hash=hb
    )
    dest_a = tmp_path / "a" / "infrastructure"
    dest_b = tmp_path / "b" / "infrastructure"
    render_stack(dest=dest_a, experiment_id="exp-a", manifest_sha=ha, vigil_image="sha256:aaa")
    render_stack(dest=dest_b, experiment_id="exp-b", manifest_sha=hb, vigil_image="sha256:bbb")
    env_a = (dest_a / "compose.env").read_text(encoding="utf-8")
    env_b = (dest_b / "compose.env").read_text(encoding="utf-8")
    assert "EXPERIMENT_ID=exp-a" in env_a
    assert "EXPERIMENT_ID=exp-b" in env_b
    assert "TOKEN=" not in env_a
    assert env_a != env_b


def test_three_scaling_batches_get_distinct_compose_projects_and_stacks(tmp_path: Path) -> None:
    batches = ("ordinary-1-glm53-v0", "ordinary-4-glm53-v0", "ordinary-8-glm53-v0")
    projects = set()
    envs = []
    for batch in batches:
        digest = config_hash(data={"experiment_id": batch, "batch_size": batch.split("-")[1]})
        project = compose_project(experiment_id=batch, cfg_hash=digest)
        projects.add(project)
        destination = tmp_path / batch / "infrastructure"
        render_stack(
            dest=destination,
            experiment_id=batch,
            manifest_sha=digest,
            vigil_image="sha256:vigil",
        )
        envs.append((destination / "compose.env").read_text(encoding="utf-8"))

    assert len(projects) == 3
    assert len(set(envs)) == 3
    assert all("COMPOSE_PROJECT_NAME=" in env for env in envs)
    assert all("TOKEN=" not in env for env in envs)


class _Docker:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "ok", "")


def test_provision_stop_destroy_use_project_and_labels(tmp_path: Path) -> None:
    dest = tmp_path / "infrastructure"
    sha = "abc123def"
    docker = _Docker()
    info = provision(
        dest=dest,
        experiment_id="exp-a",
        manifest_sha=sha,
        vigil_image="sha256:vigil",
        run=docker,
    )
    project = info["compose_project"]
    assert ["--project-name", project] == docker.calls[0][2:4]
    assert "up" in docker.calls[0]
    stop_stack(dest=dest, experiment_id="exp-a", manifest_sha=sha, run=docker)
    assert "stop" in docker.calls[1]
    assert "--volumes" not in docker.calls[1]
    with pytest.raises(InfrastructureError, match="confirm"):
        destroy_stack(
            dest=dest,
            experiment_id="exp-a",
            manifest_sha=sha,
            confirm="other",
            labels={
                "io.openagents.experiment_id": "exp-a",
                "io.openagents.manifest_sha": sha,
            },
            run=docker,
        )
    with pytest.raises(InfrastructureError, match="不一致"):
        destroy_stack(
            dest=dest,
            experiment_id="exp-a",
            manifest_sha=sha,
            confirm="exp-a",
            labels={
                "io.openagents.experiment_id": "exp-b",
                "io.openagents.manifest_sha": sha,
            },
            run=docker,
        )
    destroy_stack(
        dest=dest,
        experiment_id="exp-a",
        manifest_sha=sha,
        confirm="exp-a",
        labels={
            "io.openagents.experiment_id": "exp-a",
            "io.openagents.manifest_sha": sha,
        },
        run=docker,
    )
    assert "down" in docker.calls[-1]
    assert "--volumes" in docker.calls[-1]
