"""Workspace execution boundaries for simulated-user sessions (spec-0051/T2).

Callers consume this module instead of assuming that a workspace is a host
directory.  Docker workspaces never expose their repository as a host path.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

_MAX_OUTPUT = 20_000


def read_bounded_file(root: str, path: str, max_bytes: int) -> bytes:
    """Spec-0083/T3: open beneath the workspace without following any symlink."""
    parts = PurePosixPath(path).parts
    if (
        not parts
        or path != PurePosixPath(path).as_posix()
        or any(part in {"..", ".", ""} for part in parts)
        or PurePosixPath(path).is_absolute()
        or "\\" in path
    ):
        raise ValueError("artifact path must be a canonical workspace-relative file")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("artifact must be a regular file")
            if before.st_size > max_bytes:
                raise OverflowError("artifact exceeds declared byte limit")
            data = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
            if len(data) > max_bytes:
                raise OverflowError("artifact exceeds declared byte limit")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or len(data) != after.st_size:
                raise RuntimeError("artifact changed during collection")
            return data
    finally:
        os.close(directory)


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
    # Spec-0083/T3: capture requires a bounded binary path and a stopped writer boundary.
    def export_file(self, path: str, max_bytes: int) -> bytes: ...
    def quiesce(self) -> None: ...
    def invalidate(self, reason: str) -> None: ...
    def close(self) -> None: ...


def _safe_relative(path: str) -> str:
    candidate = PurePosixPath(path or ".")
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path escapes sandbox: {path!r}")
    return str(candidate)


def _capture_patch_base(
    runtime: Any, execute: Callable[[list[str]], subprocess.CompletedProcess[str]]
) -> None:
    """Spec-0075/T1: freeze original HEAD before the Harness can create commits."""
    if runtime._patch_base_failed:
        raise RuntimeError("original patch base could not be captured")
    if runtime._patch_base_commit is not None:
        return
    try:
        proc = execute(["git", "rev-parse", "--verify", "HEAD^{commit}"])
        base = proc.stdout.strip()
        if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
            raise RuntimeError(proc.stderr.strip() or "cannot capture original Git HEAD")
    except Exception as exc:  # noqa: BLE001 - never fall back to a later HEAD
        runtime._patch_base_failed = True
        runtime.evidence["diff_base_error"] = type(exc).__name__
        raise
    runtime._patch_base_commit = base
    runtime.evidence["diff_base_commit"] = base


def _prediction_patch_argv(base_commit: str | None) -> list[str]:
    if base_commit is None:
        # Legacy stand-alone exporters retain the original tracked-only contract.
        return ["git", "diff", "--binary", "--no-ext-diff", "--no-textconv"]
    quoted_base = shlex.quote(base_commit)
    # An isolated index includes staged, committed and new nonignored files,
    # while leaving the user's actual index untouched. The directory never sits
    # in the task tree and the trap removes it on both successful and failed exports.
    script = (
        "set -eu\n"
        "prediction_index_dir=$(mktemp -d)\n"
        "trap 'rm -rf -- \"$prediction_index_dir\"' EXIT\n"
        'export GIT_INDEX_FILE="$prediction_index_dir/index"\n'
        f"git read-tree {quoted_base}\n"
        # These paths are created by task setup/Python execution, not task source.
        # Pathspec exclusions only affect this disposable index; the real index
        # and task ignore rules are never modified.
        "git add -A -- . ':(glob,exclude)**/.venv/**' "
        "':(glob,exclude)**/__pycache__/**' ':(glob,exclude)**/*.py[cod]'\n"
        f"git diff --cached --binary --no-ext-diff --no-textconv {quoted_base} --\n"
    )
    return ["sh", "-c", script]


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
    _patch_base_commit: str | None = field(default=None, init=False)
    _patch_base_failed: bool = field(default=False, init=False)

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

    def export_file(self, path: str, max_bytes: int) -> bytes:
        # Spec-0083/T3: binary outputs never pass through clipped shell stdout.
        if self._closed:
            raise RuntimeError("workspace is closed")
        return read_bounded_file(self.cwd, path, max_bytes)

    def quiesce(self) -> None:
        """Stop attempt-owned background writers before saving grading outputs."""
        if not stop_owned_processes(self.environment.get("AUTO_DESIGNER_ATTEMPT_NONCE")):
            raise RuntimeError("workspace descendants could not be stopped")

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

    def _git_export(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=self.cwd, capture_output=True, text=True)

    def freeze_patch_base(self) -> None:
        _capture_patch_base(self, self._git_export)

    def export_patch(self) -> tuple[str, str]:
        if self._patch_base_failed:
            raise RuntimeError("original patch base could not be captured")
        proc = self._git_export(_prediction_patch_argv(self._patch_base_commit))
        # Spec-0075/T1: a failed export is not a successful empty prediction.
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git diff failed")
        patch = proc.stdout
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
                descriptor = _open_pidfd(pid=pid)
                try:
                    # Re-check ownership after obtaining the stable process handle.
                    if pid in _owned_processes(nonce):
                        _send_pidfd_signal(descriptor=descriptor, signum=sig)
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


def _pidfd_syscall(*, number: int, arguments: tuple) -> int:
    """Spec-0077/T4: use stable Linux handles when Python lacks the optional APIs."""
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("Safe attempt cleanup requires Linux pidfd support on this platform")
    # Linux x86_64 and asm-generic/aarch64 assign 434/424 to open/send_signal.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(number), *arguments)
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(result)


def _open_pidfd(*, pid: int) -> int:
    native = getattr(os, "pidfd_open", None)
    if native is not None:
        return native(pid)
    return _pidfd_syscall(number=434, arguments=(ctypes.c_int(pid), ctypes.c_uint(0)))


def _send_pidfd_signal(*, descriptor: int, signum: int) -> None:
    native = getattr(signal, "pidfd_send_signal", None)
    if native is not None:
        native(descriptor, signum)
        return
    _pidfd_syscall(
        number=424,
        arguments=(
            ctypes.c_int(descriptor),
            ctypes.c_int(signum),
            ctypes.c_void_p(),
            ctypes.c_uint(0),
        ),
    )


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
    _patch_base_commit: str | None = field(default=None, init=False)
    _patch_base_failed: bool = field(default=False, init=False)

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

    def export_file(self, path: str, max_bytes: int) -> bytes:
        """Spec-0083/T3: bounded binary read inside the actual workspace boundary."""
        import inspect

        self._ensure_live()
        # This is controller code, not a command or script supplied by the task.
        script = (
            "import os,stat,sys\nfrom pathlib import PurePosixPath\n"
            + inspect.getsource(read_bounded_file)
            + "\ntry:\n sys.stdout.buffer.write(read_bounded_file(sys.argv[1],sys.argv[2],int(sys.argv[3])))\n"
            + "except Exception as exc:\n print(type(exc).__name__,file=sys.stderr);sys.exit(1)\n"
        )
        result = subprocess.run(
            [
                "docker",
                "exec",
                self.container_id,
                "python3",
                "-c",
                script,
                self.cwd,
                path,
                str(max_bytes),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            error = result.stderr.decode(errors="replace").strip()
            if error == "FileNotFoundError":
                raise FileNotFoundError(path)
            if error == "OverflowError":
                raise OverflowError("artifact exceeds declared byte limit")
            raise RuntimeError("artifact read failed: " + error)
        if len(result.stdout) > max_bytes:
            raise OverflowError("artifact exceeds declared byte limit")
        return result.stdout

    def quiesce(self) -> None:
        """Spec-0083/T3: a disposable task container must have no background writers."""
        self._ensure_live()
        # Current Docker tasks have no managed companions. Those future services
        # require the environment broker, not this container-wide cleanup rule.
        script = (
            "import os,signal,time\nfrom pathlib import Path\n"
            "def live():\n"
            " out=[]\n"
            " for p in Path('/proc').iterdir():\n"
            "  if p.name.isdigit() and int(p.name) not in (1,os.getpid()):\n"
            "   try:\n"
            "    if p.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]!='Z': out.append(int(p.name))\n"
            "   except (FileNotFoundError,PermissionError): pass\n"
            " return out\n"
            "for sig in (signal.SIGTERM,signal.SIGKILL):\n"
            " for pid in live():\n"
            "  try: os.kill(pid,sig)\n"
            "  except ProcessLookupError: pass\n"
            " time.sleep(.1)\n"
            "if live(): raise RuntimeError('task descendants still active')\n"
        )
        result = self._exec(["python3", "-c", script], timeout=10)
        if result.returncode:
            raise RuntimeError("workspace descendants could not be stopped")

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

    def freeze_patch_base(self) -> None:
        _capture_patch_base(self, self._exec)

    def export_patch(self) -> tuple[str, str]:
        if self._patch_base_failed:
            raise RuntimeError("original patch base could not be captured")
        proc = self._exec(_prediction_patch_argv(self._patch_base_commit))
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


class ReviewSnapshot:
    """Spec-0084/T2: captured bytes, without access to the task process or filesystem.

    This is a bounded subjective review view. Full prediction/artifact receipts
    remain separate, so clipping this view never changes formal grading inputs.
    """

    def __init__(self, files: dict[str, bytes], *, patch: str = "", omissions: Sequence[str] = ()):
        self._files = MappingProxyType({name: bytes(data) for name, data in files.items()})
        self._patch = patch
        self.cwd = "/review-snapshot"
        self.runtime_id = "review-snapshot"
        manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
        self.evidence = {
            "kind": "read_only_review",
            "files": manifest,
            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "omissions": list(omissions),
        }

    def resolve(self, path: str) -> str:
        return _safe_relative(path)

    def read_text(self, path: str) -> str:
        name = self.resolve(path)
        if name not in self._files:
            raise FileNotFoundError(f"Not captured in this review snapshot: {name}")
        text = self._files[name].decode("utf-8", errors="replace")
        return text[:_MAX_OUTPUT] + ("\n[review text clipped]" if len(text) > _MAX_OUTPUT else "")

    def list_files(self, path: str = ".") -> list[str]:
        prefix = self.resolve(path)
        return [
            name
            for name in sorted(self._files)
            if prefix == "." or name == prefix or name.startswith(prefix + "/")
        ]

    def read_diff(self) -> str:
        return self._patch[:_MAX_OUTPUT] + (
            "\n[review patch clipped]" if len(self._patch) > _MAX_OUTPUT else ""
        )

    def write_text(self, path: str, content: str) -> str:
        raise PermissionError("Review snapshots do not allow writes")

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        raise PermissionError("Review snapshots do not execute commands")

    def close(self) -> None:
        pass


def capture_review_snapshot(
    workspace, *, patch: str | None = None, files: dict[str, bytes] | None = None
) -> ReviewSnapshot:
    """Capture a reply boundary without exposing deferred reads of a live workspace.

    The fixed listing is infrastructure work, never a model-selected command.
    Safe bounded exports reject symlinks and changing files. Missing/large files
    stay explicitly unavailable; this view is not the complete grading bundle.
    """
    if isinstance(workspace, ReviewSnapshot):
        return workspace
    captured = dict(files or {})
    omissions: list[str] = []
    if workspace is None:
        return ReviewSnapshot(captured, patch=patch or "", omissions=["no_workspace"])
    runtime = as_runtime(workspace)
    if patch is None:
        try:
            patch, _ = runtime.export_patch()
        except Exception as exc:  # noqa: BLE001 - subjective evidence may be unavailable
            patch = ""
            omissions.append(f"patch:{type(exc).__name__}")
    try:
        listing = runtime.run("git ls-files -z --cached --others --exclude-standard", timeout=10)
        if listing.get("returncode") != 0:
            raise RuntimeError("file listing unavailable")
        names = sorted(set(str(listing.get("stdout") or "").split("\0")) - {""})
        if len(str(listing.get("stdout") or "")) >= _MAX_OUTPUT:
            omissions.append("review_file_listing_clipped")
        total = sum(len(data) for data in captured.values())
        for index, name in enumerate(names):
            if name in captured:
                continue
            if index >= 256 or total >= 8 * 1024 * 1024:
                omissions.append("review_snapshot_capacity")
                break
            if any(
                part in {".git", ".venv", "node_modules", "__pycache__"}
                for part in PurePosixPath(name).parts
            ):
                continue
            try:
                data = runtime.export_file(name, min(1024 * 1024, 8 * 1024 * 1024 - total))
                captured[name] = data
                total += len(data)
            except Exception as exc:  # noqa: BLE001
                omissions.append(f"{name}:{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001
        omissions.append(f"files:{type(exc).__name__}")
    return ReviewSnapshot(captured, patch=patch or "", omissions=omissions)
