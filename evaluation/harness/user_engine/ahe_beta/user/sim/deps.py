"""Dependency provisioning: execute WorkspaceSpec.setup in workspace to ready dependency environment (spec-0009/T3).

Last link on provisioning side—SeedSource.provision lands files (orchestrator, pre-launch), then execute setup commands one-by-one in workspace_dir per spec.setup (by convention build per-workspace `.venv` + pip install into it), upgrading workspace from "has files" to "can run per declared dependencies". Empty setup is no-op (existing fixture/empty scenarios unchanged). Mechanism lives in data (commands): this module faithfully executes setup, never hardcodes venv logic; idempotency delegated to setup command/marker.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shlex
import time
from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.runtime import Workspace, as_runtime, utc_now

# Error truncation limit for stderr (characters), prevent excessively long logs flooding exception messages.
_STDERR_CLIP = 4_000


class SetupError(RuntimeError):
    """Setup command nonzero exit or timeout—message attaches command, returncode, truncated stderr for diagnosis."""


def prepare_task_environment(runtime: Workspace, params: dict) -> None:
    """Spec-0073/T3: rebuild at the final path; only uv's download cache is shared.

    Cache entries are published atomically by pinned uv, never used as editable
    source or a shared venv. Serializing each recipe also protects simultaneous
    cold installs. Installation copies files out of the cache explicitly.
    """
    workspace = as_runtime(runtime)
    for name in ("setup_script", "requirements_lock"):
        path = Path(params[name])
        if (
            path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != params[name + "_sha256"]
        ):
            raise SetupError(f"Frozen task preparation material changed: {name}")
    timeout = float(params.get("setup_timeout", 600))
    cache = Path(params["cache_root"]) / params["recipe_hash"]
    if cache.is_symlink() or cache.parent.is_symlink():
        raise SetupError("Linked task dependency cache")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = cache.parent / (params["recipe_hash"] + ".lock")
    if lock_path.is_symlink():
        raise SetupError("Linked task dependency cache lock")
    with lock_path.open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SetupError("Timed out waiting for task dependency cache lock") from None
                time.sleep(0.05)
        try:
            spec = WorkspaceSpec(setup=["bash " + shlex.quote(str(params["setup_script"]))])
            ensure_deps(workspace, spec, timeout=max(0.01, deadline - time.monotonic()))
            venv = Path(workspace.cwd, ".venv")
            if venv.is_symlink() or venv.resolve() != venv:
                raise SetupError(
                    "Task virtual environment must belong to its final session directory"
                )
            python = venv / "bin/python"
            if not python.is_file():
                raise SetupError("Task setup did not produce an isolated Python environment")
            probe = "import json,pathlib,sys;print(json.dumps([str(pathlib.Path(sys.prefix).resolve()),str(pathlib.Path(sys.base_prefix).resolve())]))"
            result = workspace.run(
                shlex.quote(str(python)) + " -I -c " + shlex.quote(probe),
                timeout=max(0.01, deadline - time.monotonic()),
            )
            try:
                prefix, base_prefix = json.loads(result.get("stdout", ""))
            except (ValueError, TypeError):
                raise SetupError(
                    "Task Python did not confirm its session-local virtual environment"
                ) from None
            if result.get("returncode") != 0 or prefix != str(venv) or prefix == base_prefix:
                raise SetupError(
                    "Task Python prefix differs from its final session virtual environment"
                )
            workspace.evidence["task_python_prefix"] = prefix
            workspace.evidence["setup_completed_at"] = utc_now()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def ensure_deps(workspace_dir: Workspace, spec: WorkspaceSpec, *, timeout: float = 600.0) -> None:
    """Ready dependencies in workspace_dir per spec.setup; empty setup is no-op.

    Execute setup commands one-by-one in workspace_dir as cwd (shell=True, capture output),
    raise SetupError on nonzero exit or timeout (attach command + stderr). By convention setup
    builds `.venv` and pip installs—this function does not hardcode venv logic, only faithfully executes;
    consumer side Sandbox then probes `.venv`.
    """
    if not spec.setup:
        return
    runtime = as_runtime(workspace_dir)
    for cmd in spec.setup:
        result = runtime.run(cmd, timeout=timeout)
        if result.get("status") == "timed_out":
            raise SetupError(
                f"Setup command timed out (>{timeout}s): {cmd!r}\n"
                f"stderr: {str(result.get('stderr') or '')[:_STDERR_CLIP]}"
            )
        if result.get("returncode") != 0:
            raise SetupError(
                f"Setup command failed (rc={result.get('returncode')}): {cmd!r}\n"
                f"stderr: {str(result.get('stderr') or '')[:_STDERR_CLIP]}"
            )
