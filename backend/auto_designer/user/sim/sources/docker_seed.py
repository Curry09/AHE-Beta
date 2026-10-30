"""Runnable Docker seed source (spec-0051/T2).

Every provision call starts one disposable container.  Repository contents are
never copied to a host workspace.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid

from auto_designer.models import WorkspaceSpec
from auto_designer.usage import current_usage_context
from auto_designer.user.sim.runtime import DockerWorkspaceRuntime
from auto_designer.user.sim.seed_source import register

RUNTIME_LABEL = "org.auto-designer.seed-runtime"
RUNTIME_VERSION = "1"

# Runnable seed images intentionally pack a task pool into one shared image layer.  A session
# container must not inherit that whole pool as a readable filesystem: harness shell tools are
# allowed to use absolute paths and would otherwise cross-read another benchmark instance.
# Deleting lower-layer siblings creates container-local whiteouts; the shared image is unchanged.
_RETAIN_INSTANCE_SCRIPT = """\
import shutil
import sys
from pathlib import Path

root = Path("/workspace")
keep = root / sys.argv[1]
if not keep.is_dir() or not (keep / "repo").is_dir():
    raise SystemExit(f"target workspace is missing: {keep}")
for child in list(root.iterdir()):
    if child == keep:
        continue
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink()
Path("/build-state.json").unlink(missing_ok=True)
remaining = [child.name for child in root.iterdir()]
if remaining != [sys.argv[1]]:
    raise SystemExit(f"workspace isolation failed: {remaining}")
"""


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
        # Spec-0069/T3: retain ownership after a controller is forcibly stopped.
        ownership = []
        for key, label in (
            ("AUTO_DESIGNER_RUN_ID", "io.auto-designer.run_id"),
            ("AUTO_DESIGNER_EXPERIMENT_ID", "io.openagents.experiment_id"),
            ("AUTO_DESIGNER_CONFIG_HASH", "io.openagents.manifest_sha"),
        ):
            if os.environ.get(key):
                ownership.extend(["--label", f"{label}={os.environ[key]}"])
        # Spec-0073/T2: bind disposable containers to a logical session before setup.
        context = current_usage_context()
        if context.session_id:
            for label, value in (
                ("io.auto-designer.session_id", context.session_id),
                ("io.auto-designer.task_id", spec.params.get("task_id") or instance_id),
                ("io.auto-designer.task_digest", spec.params.get("task_digest")),
                ("io.auto-designer.round_no", context.round_no),
                ("io.auto-designer.attempt", getattr(context, "attempt", None)),
            ):
                if value is not None:
                    ownership.extend(["--label", f"{label}={value}"])
        harness_python = str(spec.params.get("harness_python") or "")
        task_environment = []
        if harness_python:
            image_environment = (image_info.get("Config") or {}).get("Env") or []
            image_path = next(
                (item[5:] for item in image_environment if item.startswith("PATH=")),
                "/opt/controller/.venv/bin:/usr/local/bin:/usr/bin:/bin",
            )
            task_environment = [
                "-e",
                f"PATH={workspace}/.venv/bin:{image_path}",
                "-e",
                f"VIRTUAL_ENV={workspace}/.venv",
            ]
        # Spec-0069/T3: only explicit proxy settings cross this workspace boundary.
        proxy_environment = spec.params.get("env") or {}
        allowed = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"}
        if not isinstance(proxy_environment, dict) or any(
            key not in allowed or not isinstance(value, str) or "\n" in value or "\r" in value
            for key, value in proxy_environment.items()
        ):
            raise ValueError("docker-seed params.env only accepts explicit proxy variables")
        for key, value in proxy_environment.items():
            task_environment.extend(["-e", f"{key}={value}"])
        started = _docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"auto-designer.session={name}",
                *ownership,
                *task_environment,
                "--network",
                network,
                "--workdir",
                workspace,
                image,
                # Spec-0084/T2: quiesce kills every non-init task process. A
                # shell loop would respawn its sleep child during that cleanup.
                # Keep PID 1 alive without creating any child processes.
                "sleep",
                "infinity",
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
        try:
            _docker(
                [
                    "exec",
                    container_id,
                    "python3",
                    "-c",
                    _RETAIN_INSTANCE_SCRIPT,
                    instance_id,
                ]
            )
        except Exception as exc:
            runtime.close()
            raise RuntimeError(f"无法将 session 隔离到 instance {instance_id!r}") from exc
        if harness_python:
            runtime.evidence["harness_python"] = harness_python
        if proxy_environment:
            runtime.evidence["proxy_environment"] = dict(proxy_environment)
        runtime.evidence.update(
            {
                "instance_id": instance_id,
                "workspace_scope": "single_instance",
                **(
                    {
                        "session_id": context.session_id,
                        "task_id": spec.params.get("task_id") or instance_id,
                        "task_digest": spec.params.get("task_digest"),
                    }
                    if context.session_id
                    else {}
                ),
            }
        )
        return runtime
