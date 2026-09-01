"""Runnable Docker seed source (spec-0051/T2).

Every provision call starts one disposable container.  Repository contents are
never copied to a host workspace.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.runtime import DockerWorkspaceRuntime
from auto_designer.user.sim.seed_source import register

RUNTIME_LABEL = "org.auto-designer.seed-runtime"
RUNTIME_VERSION = "1"


def _docker(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"docker 命令失败：docker {' '.join(args)}（rc={proc.returncode}）\n"
            f"stderr: {(proc.stderr or '').strip()[:2000]}"
        )
    return proc


@register("docker-seed")
class DockerSeedSource:
    kind = "docker-seed"

    def provision(
        self,
        spec: WorkspaceSpec,
        dest_root: str | None = None,  # noqa: ARG002
    ) -> DockerWorkspaceRuntime:
        image = str(spec.params.get("image", "")).strip()
        instance_id = str(spec.params.get("instance_id", "")).strip()
        if not image:
            raise ValueError("docker-seed 源需要非空 params.image")
        if not instance_id:
            raise ValueError("docker-seed 源需要非空 params.instance_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", instance_id) is None:
            raise ValueError("docker-seed params.instance_id 必须是安全的单路径段")

        inspected = _docker(["image", "inspect", image])
        image_info = json.loads(inspected.stdout)[0]
        labels = (image_info.get("Config") or {}).get("Labels") or {}
        if labels.get(RUNTIME_LABEL) != RUNTIME_VERSION:
            raise RuntimeError(
                f"seed image {image!r} 不是 runnable v{RUNTIME_VERSION}；"
                "旧 storage-only image 禁止回退 docker cp，请先构建 runtime image"
            )
        image_digest = str(image_info.get("Id") or image)
        workspace = f"/workspace/{instance_id}/repo"
        name = f"ad-session-{uuid.uuid4().hex[:16]}"
        network = str(spec.params.get("network") or "none")
        started = _docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"auto-designer.session={name}",
                "--network",
                network,
                "--workdir",
                workspace,
                image,
                "sh",
                "-lc",
                "trap 'exit 0' TERM INT; while :; do sleep 3600; done",
            ]
        )
        container_id = started.stdout.strip()
        if not container_id:
            raise RuntimeError(f"docker run 未返回 container id：{image}")
        runtime = DockerWorkspaceRuntime(
            container_id=container_id,
            container_name=name,
            image=image,
            image_digest=image_digest,
            cwd=workspace,
        )
        try:
            state = _docker(["exec", container_id, "cat", "/build-state.json"]).stdout
            parsed = json.loads(state)
            if instance_id not in (parsed.get("instances") or {}):
                raise KeyError(instance_id)
        except Exception as exc:
            runtime.close()
            raise RuntimeError(f"seed image 不含 instance {instance_id!r}") from exc
        return runtime
