# Spec-0047/T3: mock Docker dual-experiment isolation and destroy confirmation.
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from ahe_beta.experiment.config import compose_project, config_hash
from ahe_beta.experiment.infrastructure import (
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
    assert "name: ahe-beta-" not in text
    assert "127.0.0.1:${GITEA_HOST_PORT:-0}:3000" in text
    assert "io.openagents.experiment_id" in text


@pytest.mark.parametrize("deployment", ["experiment", "gitea"])
def test_default_egress_has_no_operator_specific_destinations(deployment) -> None:
    egress = Path(__file__).resolve().parents[2] / "deploy" / deployment / "egress-proxy.conf"
    rules = egress.read_text(encoding="utf-8")
    assert set(re.findall(r"^acl allowed_egress dstdomain (.+)$", rules, re.MULTILINE)) == {
        ".anthropic.com",
        ".claude.ai",
    }
    assert not re.search(r"^acl \S+ dst\s", rules, re.MULTILINE)
    assert not re.search(r"^(cache_peer|never_direct)\s", rules, re.MULTILINE)
    assert "http_access deny all" in rules.splitlines()
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
    with pytest.raises(InfrastructureError, match="do not match"):
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
