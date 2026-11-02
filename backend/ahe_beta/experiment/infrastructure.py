# Spec-0047/T3：每实验独立 Compose 栈；按 label + manifest 资源 ID 认领，不按同名复用。
"""Provision, stop, and destroy experiment infrastructure via Compose project."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ahe_beta.experiment.config import ConfigError, compose_project

LABEL_EXPERIMENT = "io.openagents.experiment_id"
LABEL_MANIFEST = "io.openagents.manifest_sha"
# Spec-0069/T3: Canonical Ubuntu 24.04 LTS channel, actual Squid 6.13 build.
DEFAULT_EGRESS_IMAGE = "ubuntu/squid:6.6-24.04_beta@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029"
COMPOSE_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "deploy" / "experiment" / "docker-compose.yml"
)
EGRESS_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "deploy" / "experiment" / "egress-proxy.conf"
)

RunFn = Callable[..., subprocess.CompletedProcess]


class InfrastructureError(ConfigError):
    """Compose/label mismatch or destroy without confirm."""


def render_stack(
    *,
    dest: Path,
    experiment_id: str,
    manifest_sha: str,
    vigil_image: str,
    images: dict[str, str] | None = None,
    gitea_host_port: int = 0,
    ci_enabled: bool = False,
) -> Path:
    if type(gitea_host_port) is not int or not 0 <= gitea_host_port <= 65535:
        raise InfrastructureError("Gitea host port must be 0 (allocate) or a valid TCP port")
    dest.mkdir(parents=True, exist_ok=True)
    compose_src = COMPOSE_TEMPLATE.read_text(encoding="utf-8")
    if ci_enabled:
        from ahe_beta.experiment.backends.local_ci import compose_service

        compose_src = compose_src.replace(
            'GITEA__actions__ENABLED: "false"', 'GITEA__actions__ENABLED: "true"'
        )
        compose_src = compose_src.replace("\nnetworks:\n", compose_service() + "\nnetworks:\n")
        compose_src += "\n  runner_data:\n    labels: *ownership\n"
        compose_src += "\n  ci_docker_data:\n    labels: *ownership\n"
    if "container_name:" in compose_src:
        raise InfrastructureError("compose 模板禁止 container_name")
    (dest / "docker-compose.yml").write_text(compose_src, encoding="utf-8")
    (dest / "egress-proxy.conf").write_text(
        EGRESS_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    env_path = dest / "compose.env"
    resolved_images = dict(images or {})
    env_path.write_text(
        "\n".join(
            [
                f"EXPERIMENT_ID={experiment_id}",
                f"MANIFEST_SHA={manifest_sha}",
                f"GITEA_IMAGE={resolved_images.get('gitea', 'gitea/gitea:1.22')}",
                f"GITEA_HOST_PORT={gitea_host_port}",
                f"RUNNER_IMAGE={resolved_images.get('runner', 'gitea/act_runner:0.2.11')}",
                *(
                    [f"CI_DAEMON_IMAGE={resolved_images.get('ci_daemon', 'docker:27.5.1-dind')}"]
                    if ci_enabled
                    else []
                ),
                f"EGRESS_IMAGE={resolved_images.get('egress', DEFAULT_EGRESS_IMAGE)}",
                f"VIGIL_IMAGE={vigil_image}",
                f"COMPOSE_PROJECT_NAME={compose_project(experiment_id=experiment_id, cfg_hash=manifest_sha)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if "TOKEN=" in env_path.read_text(encoding="utf-8") and vigil_image.startswith("sk-"):
        raise InfrastructureError("compose.env 含密钥")
    return dest / "docker-compose.yml"


def compose_argv(*, dest: Path, project: str, extra: list[str]) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(dest / "compose.env"),
        "-f",
        str(dest / "docker-compose.yml"),
        *extra,
    ]


def provision(
    *,
    dest: Path,
    experiment_id: str,
    manifest_sha: str,
    vigil_image: str,
    run: RunFn | None = None,
) -> dict[str, Any]:
    render_stack(
        dest=dest, experiment_id=experiment_id, manifest_sha=manifest_sha, vigil_image=vigil_image
    )
    project = compose_project(experiment_id=experiment_id, cfg_hash=manifest_sha)
    runner = run or subprocess.run
    argv = compose_argv(dest=dest, project=project, extra=["up", "-d"])
    result = runner(argv, capture_output=True, text=True)
    if getattr(result, "returncode", 1) != 0:
        raise InfrastructureError(f"compose up 失败：{getattr(result, 'stderr', '')[:300]}")
    return {
        "compose_project": project,
        "experiment_id": experiment_id,
        "manifest_sha": manifest_sha,
    }


def stop_stack(
    *, dest: Path, experiment_id: str, manifest_sha: str, run: RunFn | None = None
) -> None:
    project = compose_project(experiment_id=experiment_id, cfg_hash=manifest_sha)
    runner = run or subprocess.run
    argv = compose_argv(dest=dest, project=project, extra=["stop"])
    result = runner(argv, capture_output=True, text=True)
    if getattr(result, "returncode", 1) != 0:
        raise InfrastructureError(f"compose stop 失败：{getattr(result, 'stderr', '')[:300]}")


def destroy_stack(
    *,
    dest: Path,
    experiment_id: str,
    manifest_sha: str,
    confirm: str,
    labels: dict[str, str],
    run: RunFn | None = None,
) -> None:
    if confirm != experiment_id:
        raise InfrastructureError("destroy 必须 --confirm 完整 experiment_id")
    owned = labels.get(LABEL_EXPERIMENT, "")
    sha = labels.get(LABEL_MANIFEST, "")
    if owned != experiment_id or sha != manifest_sha:
        raise InfrastructureError("label 与 manifest 不一致，拒绝跨实验销毁")
    project = compose_project(experiment_id=experiment_id, cfg_hash=manifest_sha)
    runner = run or subprocess.run
    argv = compose_argv(dest=dest, project=project, extra=["down", "--volumes", "--remove-orphans"])
    result = runner(argv, capture_output=True, text=True)
    if getattr(result, "returncode", 1) != 0:
        raise InfrastructureError(f"compose down 失败：{getattr(result, 'stderr', '')[:300]}")


def parse_compose_template() -> str:
    return COMPOSE_TEMPLATE.read_text(encoding="utf-8")


def write_runtime(*, dest: Path, data: dict[str, Any]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "runtime.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def env_without_secrets(*, dest: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    path = dest / "compose.env"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if "TOKEN" in key.upper() or "SECRET" in key.upper() or "KEY" in key.upper():
            continue
        out[key] = value
    return out
