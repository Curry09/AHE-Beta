"""Workspace execution boundaries for simulated-user sessions (spec-0051/T2).

Callers consume this module instead of assuming that a workspace is a host
directory.  Docker workspaces never expose their repository as a host path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, runtime_checkable

_MAX_OUTPUT = 20_000


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@runtime_checkable
class WorkspaceRuntime(Protocol):
    """A session-scoped workspace with an explicit lifecycle."""

    runtime_id: str
    cwd: str
    evidence: dict[str, Any]

    def resolve(self, path: str) -> str: ...
    def read_text(self, path: str) -> str: ...
    def write_text(self, path: str, content: str) -> str: ...
    def run(self, cmd: str, timeout: float = 10.0) -> dict[str, Any]: ...
    def stage_directory(self, source: Path, destination: str) -> None: ...
    def popen_argv(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> list[str]: ...
    def export_patch(self) -> tuple[str, str]: ...
    def invalidate(self, reason: str) -> None: ...
    def close(self) -> None: ...


def _safe_relative(path: str) -> str:
    candidate = PurePosixPath(path or ".")
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path escapes sandbox: {path!r}")
    return str(candidate)


@dataclass
class LocalWorkspaceRuntime:
    """Compatibility runtime for fixtures and developer-only local scenarios."""

    root: str
    owns_tmp: bool = False
    runtime_id: str = field(default_factory=lambda: f"local-{uuid.uuid4().hex}")
    evidence: dict[str, Any] = field(default_factory=dict)
    # Spec-0073/T3: managed cloud attempts own repo, HOME and all shell descendants.
    attempt_root: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.cwd = str(Path(self.root).resolve())
        self.evidence.update({"kind": "local", "runtime_id": self.runtime_id, "cwd": self.cwd})

    def resolve(self, path: str) -> str:
        rel = _safe_relative(path)
        base = Path(self.cwd).resolve()
        target = (base / rel).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"path escapes sandbox: {path!r}")
        return str(target)

    def read_text(self, path: str) -> str:
        return Path(self.resolve(path)).read_text(encoding="utf-8")

    def write_text(self, path: str, content: str) -> str:
        target = Path(self.resolve(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def run(self, cmd: str, timeout: float = 10.0) -> dict[str, Any]:
        if self._closed or (self.attempt_root and self.evidence.get("invalid_reason")):
            raise RuntimeError("workspace attempt is closed or invalid")
        started = utc_now()
        # Spec-0069/T4: unified cloud task shells opt into their session-local venv.
        environment = {**os.environ, **self.environment} if self.environment else None
        task_venv = self.evidence.get("task_virtual_env")
        if task_venv:
            environment = {
                **(environment or os.environ),
                "VIRTUAL_ENV": str(task_venv),
                "PATH": str(task_venv)
                + "/bin:"
                + (environment or os.environ).get("PATH", "/usr/bin:/bin"),
            }
        try:
            child = subprocess.Popen(
                cmd,
                shell=True,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                start_new_session=True,
            )
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # The shell alone is not an execution boundary. Kill its entire group,
            # including grandchildren that retain stdout after the shell exits.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            contained = stop_owned_processes(self.environment.get("AUTO_DESIGNER_ATTEMPT_NONCE"))
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                contained = False
            if self.attempt_root:
                self.invalidate(f"command timeout >{timeout}s")
                self.evidence["timeout_contained"] = contained
            return {
                "ok": False,
                "status": "timed_out",
                "error": "timeout",
                "stdout": (exc.stdout or "")[:_MAX_OUTPUT] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[:_MAX_OUTPUT] if isinstance(exc.stderr, str) else "",
                "returncode": None,
                "started_at": started,
                "finished_at": utc_now(),
            }
        return {
            "ok": True,
            "status": "completed",
            "stdout": stdout[:_MAX_OUTPUT],
            "stderr": stderr[:_MAX_OUTPUT],
            "returncode": child.returncode,
            "started_at": started,
            "finished_at": utc_now(),
        }

    def stage_directory(self, source: Path, destination: str) -> None:
        target = Path(self.resolve(destination))
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    def popen_argv(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> list[str]:
        return list(argv)

    def export_patch(self) -> tuple[str, str]:
        proc = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
        )
        patch = proc.stdout if proc.returncode == 0 else ""
        return patch, hashlib.sha256(patch.encode()).hexdigest()

    def invalidate(self, reason: str) -> None:
        self.evidence.update({"invalidated_at": utc_now(), "invalid_reason": reason})

    def close(self) -> None:
        if self._closed:
            return
        if self.attempt_root:
            owner = Path(self.attempt_root) / "owner.json"
            expected = self.evidence["attempt_identity"]
            if owner.is_symlink() or json.loads(owner.read_text()) != expected:
                raise RuntimeError("Workspace attempt ownership changed; refusing cleanup")
            stopped = stop_owned_processes(self.environment["AUTO_DESIGNER_ATTEMPT_NONCE"])
            self.evidence["descendants_stopped"] = stopped
            if not stopped or self.evidence.get("timeout_contained") is False:
                self.invalidate("Attempt descendants could not be confirmed stopped")
                self.save_receipt()
                raise RuntimeError("Uncontained workspace attempt retained for inspection")
            self.evidence.setdefault("closed_at", utc_now())
            self.save_receipt()
            shutil.rmtree(self.attempt_root)
            self._closed = True
            return
        self.evidence.setdefault("closed_at", utc_now())
        if self.owns_tmp:
            shutil.rmtree(self.cwd, ignore_errors=True)
        self._closed = True

    def save_receipt(self) -> None:
        """Publish diagnostics outside the reclaimed attempt, without its environment."""
        path = self.evidence.get("receipt_path")
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.evidence, indent=2) + "\n")
            temporary.chmod(0o600)
            temporary.replace(target)


def _owned_processes(nonce: str) -> list[int]:
    matches = []
    marker = ("AUTO_DESIGNER_ATTEMPT_NONCE=" + nonce).encode()
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            state = (directory / "stat").read_text().rsplit(")", 1)[1].split()[0]
            if state != "Z" and marker in (directory / "environ").read_bytes().split(b"\0"):
                matches.append(int(directory.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return matches


def stop_owned_processes(nonce: str | None) -> bool:
    """Stop only this attempt's processes; pidfds prevent PID reuse races on Linux."""
    if not nonce:
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in _owned_processes(nonce):
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    # Re-check ownership after obtaining the stable process handle.
                    if pid in _owned_processes(nonce):
                        signal.pidfd_send_signal(descriptor, sig)
                finally:
                    os.close(descriptor)
            except ProcessLookupError:
                continue
        until = time.monotonic() + 1
        while time.monotonic() < until:
            if not _owned_processes(nonce):
                return True
            time.sleep(0.02)
    return not _owned_processes(nonce)


@dataclass
class DockerWorkspaceRuntime:
    """A repository that exists only inside one disposable Docker container."""

    container_id: str
    container_name: str
    image: str
    image_digest: str
    cwd: str
    runtime_id: str = field(default_factory=lambda: f"docker-{uuid.uuid4().hex}")
    evidence: dict[str, Any] = field(default_factory=dict)
    _closed: bool = False
    _invalid: bool = False

    def __post_init__(self) -> None:
        self.evidence.update(
            {
                "kind": "docker",
                "runtime_id": self.runtime_id,
                "container_id": self.container_id,
                "container_name": self.container_name,
                "image": self.image,
                "image_digest": self.image_digest,
                "cwd": self.cwd,
                "started_at": utc_now(),
            }
        )

    def _ensure_live(self) -> None:
        if self._closed:
            raise RuntimeError("workspace container is closed")
        if self._invalid:
            raise RuntimeError("workspace container is invalid after an uncontained timeout/crash")

    def _path(self, path: str) -> str:
        rel = _safe_relative(path)
        return str(PurePosixPath(self.cwd) / rel)

    def resolve(self, path: str) -> str:
        """Resolve a relative path inside the container workspace."""
        return self._path(path)

    def _exec(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        input_text: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._ensure_live()
        command = ["docker", "exec", "-i", "-w", cwd or self.cwd]
        for key, value in (env or {}).items():
            command.extend(["-e", f"{key}={value}"])
        command.extend([self.container_id, *argv])
        return subprocess.run(
            command, input=input_text, capture_output=True, text=True, timeout=timeout
        )

    def read_text(self, path: str) -> str:
        proc = self._exec(["cat", self._path(path)])
        if proc.returncode != 0:
            raise OSError(proc.stderr.strip() or f"cannot read {path!r}")
        return proc.stdout

    def write_text(self, path: str, content: str) -> str:
        target = self._path(path)
        parent = str(PurePosixPath(target).parent)
        proc = self._exec(
            ["sh", "-lc", f"mkdir -p {shlex.quote(parent)} && cat > {shlex.quote(target)}"],
            input_text=content,
        )
        if proc.returncode != 0:
            raise OSError(proc.stderr.strip() or f"cannot write {path!r}")
        return target

    def run(self, cmd: str, timeout: float = 10.0) -> dict[str, Any]:
        started = utc_now()
        try:
            proc = self._exec(["sh", "-lc", cmd], timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # Killing docker-exec does not prove that descendants in the container stopped.
            # Mark the whole execution boundary unusable; orchestrator finally removes it.
            self.invalidate(f"command timeout >{timeout}s")
            return {
                "ok": False,
                "status": "timed_out",
                "error": "timeout",
                "stdout": (exc.stdout or "")[:_MAX_OUTPUT] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[:_MAX_OUTPUT] if isinstance(exc.stderr, str) else "",
                "returncode": None,
                "started_at": started,
                "finished_at": utc_now(),
            }
        return {
            "ok": True,
            "status": "completed",
            "stdout": proc.stdout[:_MAX_OUTPUT],
            "stderr": proc.stderr[:_MAX_OUTPUT],
            "returncode": proc.returncode,
            "started_at": started,
            "finished_at": utc_now(),
        }

    def stage_directory(self, source: Path, destination: str) -> None:
        self._ensure_live()
        destination = str(PurePosixPath(destination))
        if not destination.startswith("/"):
            raise ValueError("container stage destination must be absolute")
        with tempfile.NamedTemporaryFile(suffix=".tar") as archive:
            with tarfile.open(fileobj=archive, mode="w") as tf:
                tf.add(source, arcname="payload")
            archive.flush()
            with open(archive.name, "rb") as stream:
                command = [
                    "docker",
                    "exec",
                    "-i",
                    self.container_id,
                    "sh",
                    "-lc",
                    f"rm -rf {shlex.quote(destination)} && mkdir -p {shlex.quote(destination)} "
                    f"&& tar -xf - -C {shlex.quote(destination)} --strip-components=1",
                ]
                proc = subprocess.run(command, stdin=stream, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="replace")[:2000])

    def popen_argv(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> list[str]:
        self._ensure_live()
        command = ["docker", "exec", "-i", "-w", cwd]
        for key, value in env.items():
            command.extend(["-e", f"{key}={value}"])
        return [*command, self.container_id, *argv]

    def export_patch(self) -> tuple[str, str]:
        proc = self._exec(["git", "diff", "--binary", "--no-ext-diff"])
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git diff failed")
        patch = proc.stdout
        digest = hashlib.sha256(patch.encode()).hexdigest()
        self.evidence.update({"diff_sha256": digest, "diff_bytes": len(patch.encode())})
        return patch, digest

    def invalidate(self, reason: str) -> None:
        if self._closed:
            return
        self._invalid = True
        self.evidence.update({"invalidated_at": utc_now(), "invalid_reason": reason})
        subprocess.run(["docker", "kill", self.container_id], capture_output=True, text=True)

    def close(self) -> None:
        if self._closed:
            return
        if self.evidence.get("observation", {}).get("retain_source"):
            # Keep the only copy after a failed export, but never keep the task running.
            stopped = subprocess.run(
                ["docker", "stop", "--time", "2", self.container_id],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.evidence.update(
                {"retained_for_observations": True, "stop_confirmed": stopped.returncode == 0}
            )
            self._closed = True
            self.evidence["closed_at"] = utc_now()
            return
        subprocess.run(["docker", "rm", "-f", self.container_id], capture_output=True, text=True)
        self._closed = True
        self.evidence["closed_at"] = utc_now()


Workspace = str | WorkspaceRuntime


def as_runtime(workspace: Workspace, *, owns_tmp: bool = False) -> WorkspaceRuntime:
    if isinstance(workspace, str):
        return LocalWorkspaceRuntime(workspace, owns_tmp=owns_tmp)
    return workspace


def make_empty_runtime() -> LocalWorkspaceRuntime:
    return LocalWorkspaceRuntime(tempfile.mkdtemp(prefix="shared_ws_"), owns_tmp=True)
