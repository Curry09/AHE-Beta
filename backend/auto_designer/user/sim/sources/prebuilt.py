"""Spec-0073/T3: copy pure task source and rebuild each managed session's venv.

New frozen experiments prepare dependencies at their final session/attempt path,
with independent writable source and virtual environments. Legacy callers still
copy prepared workspaces and relocate regular editable metadata; linked data is
copied independently so relocation cannot modify the seed or shared cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime, Workspace
from auto_designer.user.sim.seed_source import register

_TEXT_SUFFIXES = {".pth", ".egg-link", ".py", ".json"}


@register("prebuilt")
class PrebuiltSource:
    kind = "prebuilt"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace:
        if "workload_contract_version" in spec.params:
            if (
                type(spec.params["workload_contract_version"]) is not int
                or spec.params["workload_contract_version"] != 1
            ):
                raise ValueError("Unknown prebuilt workload contract")
            from auto_designer.usage import current_usage_context

            usage = current_usage_context()
            identity = {
                name: getattr(usage, name, None)
                for name in ("run_id", "session_id", "task_id", "task_digest", "attempt")
            }
            return _provision_task(params=spec.params, identity=identity, dest_root=dest_root)
        source_raw = spec.params.get("source")
        if not source_raw:
            raise ValueError("prebuilt 源需要非空 params.source")
        source = Path(str(source_raw)).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"prebuilt workspace 不存在：{source}")

        base = Path(dest_root) if dest_root else Path(tempfile.mkdtemp(prefix="sim_ws_prebuilt_"))
        dest = base / "repo"
        shutil.copytree(
            source,
            dest,
            # Copy linked text/data as regular files. Relocation must never write
            # through a copied symlink into the original seed or shared cache.
            symlinks=False,
            ignore=shutil.ignore_patterns(".venv.stale-*"),
        )
        _relocate_venv(dest=dest, old_root=source)
        if spec.params.get("activate_venv") is True:
            if not (dest / ".venv/bin/python").is_file():
                raise ValueError("Unified prebuilt workspace requires a prepared task virtualenv")
            # Spec-0069/T4: the Harness interpreter is independent of task shell Python.
            runtime = LocalWorkspaceRuntime(root=str(dest.resolve()), owns_tmp=dest_root is None)
            runtime.evidence.update(
                task_virtual_env=str(dest.resolve() / ".venv"),
                harness_python=str(spec.params.get("harness_python") or ""),
            )
            return runtime
        return str(dest.resolve())


def validate_task_baseline(params: dict) -> dict:
    """Prepare's non-root worker validates the same final-directory setup protocol."""
    identity = {
        "run_id": params["run_id"],
        "session_id": "prepare-task-" + params["task_id"],
        "task_id": params["task_id"],
        "task_digest": params["task_digest"],
        "attempt": 1,
    }
    runtime = _provision_task(params=params, identity=identity, dest_root=None)
    try:
        return dict(runtime.evidence)
    finally:
        runtime.close()


def _verify_source(source: Path, files: dict) -> None:
    actual = {}
    for directory, dirs, names in os.walk(source, followlinks=False):
        if Path(directory) == source:
            dirs[:] = [name for name in dirs if name != ".git"]
        for name in dirs + names:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Linked task baseline source")
        for name in names:
            path = Path(directory) / name
            actual[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != files:
        raise ValueError("Task baseline source inventory changed")


def _provision_task(
    *, params: dict, identity: dict, dest_root: str | None
) -> LocalWorkspaceRuntime:
    from auto_designer.user.sim.deps import prepare_task_environment

    if (
        type(params.get("workload_contract_version")) is not int
        or params["workload_contract_version"] != 1
    ):
        raise ValueError("Unknown prebuilt workload contract")
    if (
        os.geteuid() == 0
        or os.getuid() != params["execution_uid"]
        or os.getgid() != params["execution_gid"]
    ):
        raise ValueError("Managed task workspace must run as its recorded non-root worker")
    if (
        identity.get("run_id") != params["run_id"]
        or identity.get("task_id") != params["task_id"]
        or identity.get("task_digest") != params["task_digest"]
        or not identity.get("session_id")
        or type(identity.get("attempt")) is not int
        or identity["attempt"] < 1
    ):
        raise ValueError(
            "Managed task workspace requires matching bound session/task/attempt identity"
        )
    root = Path(params["run_root"])
    if root.is_symlink() or not root.is_absolute():
        raise ValueError("Linked or relative task run root")
    root = root.resolve()
    frozen = json.loads((root / "manifest.json").read_text())
    if (
        frozen.get("run_id") != params["run_id"]
        or frozen.get("config_hash") != params["config_hash"]
        or type(frozen.get("workload_contract_version")) is not int
        or frozen.get("workload_contract_version") != 1
    ):
        raise ValueError("Task workspace run/config binding differs from frozen manifest")
    if not re.fullmatch(r"[a-f0-9]{64}", str(params["recipe_hash"])):
        raise ValueError("Task preparation recipe must be a SHA-256 content key")
    paths = ("source", "session_root", "cache_root", "setup_script", "requirements_lock")
    for key in paths:
        path = Path(params[key])
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Task workspace path escapes owned run: {key}")
    cache = Path(params["cache_root"]) / params["recipe_hash"]
    if not cache.resolve().is_relative_to(Path(params["cache_root"]).resolve()):
        raise ValueError("Task dependency cache key escapes cache root")
    source = Path(params["source"])
    _verify_source(source, params["source_files"])
    session = hashlib.sha256(str(identity["session_id"]).encode()).hexdigest()
    parent = Path(params["session_root"]) / session
    if parent.is_symlink():
        raise ValueError("Linked session workspace directory")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempt = parent / f"attempt-{identity['attempt']}"
    if dest_root is not None and Path(dest_root).resolve() != attempt:
        raise ValueError("Managed task workspace destination must be its owned attempt directory")
    attempt.mkdir(mode=0o700)  # A stale attempt is never silently reused.
    identity = {
        **identity,
        "config_hash": params["config_hash"],
        "nonce": uuid.uuid4().hex,
        "execution_uid": os.getuid(),
        "execution_gid": os.getgid(),
    }
    owner = attempt / "owner.json"
    owner.write_text(json.dumps(identity, sort_keys=True))
    owner.chmod(0o600)
    repo, home = attempt / "repo", attempt / "home"
    home.mkdir(mode=0o700)
    env = {
        "HOME": str(home),
        "USER": os.environ.get("USER", "user"),
        "PYTHONPATH": "",
        "PYTHONHOME": "",
        "PYTHONNOUSERSITE": "1",
        "TASK_ROOT": str(repo),
        "TASK_PYTHON": params["managed_python"],
        "UV_BIN": params["uv"],
        "VIRTUAL_ENV": str(repo / ".venv"),
        "REQUIREMENTS_LOCK": params["requirements_lock"],
        "AUTO_DESIGNER_TASK_REQUIREMENTS": params["requirements_lock"],
        "UV_CACHE_DIR": str(cache),
        "UV_LINK_MODE": "copy",
        "AUTO_DESIGNER_ATTEMPT_NONCE": identity["nonce"],
    }
    receipt = root / "runtime/workspace-receipts" / session / f"attempt-{identity['attempt']}.json"
    runtime = LocalWorkspaceRuntime(
        root=str(repo),
        owns_tmp=True,
        attempt_root=str(attempt),
        environment=env,
        evidence={
            "attempt_identity": identity,
            "task_virtual_env": str(repo / ".venv"),
            "harness_python": params["harness_python"],
            "recipe_hash": params["recipe_hash"],
            "receipt_path": str(receipt),
            "link_mode": "copy",
        },
    )
    try:
        shutil.copytree(source, repo, symlinks=False)
        _verify_source(repo, params["source_files"])
        prepare_task_environment(runtime, params)
        runtime.save_receipt()
        return runtime
    except BaseException as exc:
        runtime.invalidate(type(exc).__name__ + ": " + str(exc)[:4000])
        runtime.close()
        raise


def _relocate_venv(*, dest: Path, old_root: Path) -> None:
    venv = dest / ".venv"
    if not venv.is_dir():
        return
    old = str(old_root).encode()
    new = str(dest.resolve()).encode()
    candidates: list[Path] = [venv / "pyvenv.cfg"]
    bin_dir = venv / "bin"
    if bin_dir.is_dir():
        candidates.extend(
            path for path in bin_dir.iterdir() if path.is_file() and not path.is_symlink()
        )
    lib_dir = venv / "lib"
    if lib_dir.is_dir():
        candidates.extend(
            path
            for path in lib_dir.rglob("*")
            if path.is_file() and (path.suffix in _TEXT_SUFFIXES or path.name == "direct_url.json")
        )

    for path in candidates:
        if path.is_symlink():
            raise ValueError("Linked relocation metadata")
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if old in data:
            path.write_bytes(data.replace(old, new))
