"""Docker seed image source.

Extract one prepared SWE-bench repository from a storage-only image, then
relocate its editable virtualenv for the fresh per-session path.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register
from auto_designer.user.sim.sources.prebuilt import _relocate_venv


@register("docker-seed")
class DockerSeedSource:
    kind = "docker-seed"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        image = str(spec.params.get("image", "")).strip()
        instance_id = str(spec.params.get("instance_id", "")).strip()
        if not image:
            raise ValueError("docker-seed 源需要非空 params.image")
        if not instance_id:
            raise ValueError("docker-seed 源需要非空 params.instance_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", instance_id) is None:
            raise ValueError("docker-seed params.instance_id 必须是安全的单路径段")

        base = Path(dest_root) if dest_root else Path(tempfile.mkdtemp(prefix="sim_ws_docker_seed_"))
        base.mkdir(parents=True, exist_ok=True)
        dest = base / "repo"
        state_path = base / ".seed-build-state.json"

        created = _docker(["create", image, "/bin/true"])
        container_id = created.stdout.strip()
        if not container_id:
            raise RuntimeError(f"docker create 未返回 container id：{image}")
        try:
            _docker(["cp", f"{container_id}:/build-state.json", str(state_path)])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            meta = (state.get("instances") or {}).get(instance_id)
            if not meta:
                raise KeyError(f"seed 镜像不含 instance：{instance_id}")
            old_root_raw = str(meta.get("source_path", "")).strip()
            if not old_root_raw:
                raise KeyError(f"seed 状态缺 source_path：{instance_id}")
            _docker(["cp", f"{container_id}:/workspace/{instance_id}/repo", str(dest)])
        finally:
            subprocess.run(["docker", "rm", container_id], capture_output=True, text=True)

        _relocate_venv(dest=dest, old_root=Path(old_root_raw))
        state_path.unlink(missing_ok=True)
        return str(dest.resolve())


def _docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker 命令失败：docker {' '.join(args)}（rc={proc.returncode}）\n"
            f"stderr: {(proc.stderr or '').strip()[:2000]}"
        )
    return proc
