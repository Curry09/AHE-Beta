"""Bounded staging and isolated Docker execution (Spec-0083/T4).

Task bytes never become host commands or bind mounts. Containers use frozen image
IDs, no Docker socket, no host credentials and no network during verification.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import selectors
import shutil
import subprocess
import tarfile
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ..contracts import (
    MAX_INPUT_BYTES,
    ArtifactInput,
    GradingRequest,
    InputValidationError,
    MaterialInput,
)

MAX_BUNDLE_BYTES = MAX_INPUT_BYTES
IMMUTABLE_IMAGE = re.compile(r"(?:sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64})\Z")


class TimeBudget:
    """One total request deadline, including image preparation and verifier."""

    def __init__(self, timeout: float) -> None:
        self.deadline = time.monotonic() + timeout

    def remaining(self, cap: float | None = None) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("grading request", 0)
        return remaining if cap is None else min(cap, remaining)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def material_bytes(material: MaterialInput) -> bytes:
    if not material.path.is_file() or material.path.is_symlink():
        raise InputValidationError(
            f"missing regular grading material: {material.path}", status="missing_artifact"
        )
    if material.path.stat().st_size > MAX_BUNDLE_BYTES:
        raise InputValidationError("grading material exceeds 256 MiB limit")
    data = material.path.read_bytes()
    if sha256(data) != material.sha256:
        raise InputValidationError(f"material hash mismatch: {material.path.name}")
    return data


def artifact_bytes(artifact: ArtifactInput) -> bytes:
    data = artifact.payload
    if data is None:
        if not artifact.path.is_file() or artifact.path.is_symlink():
            raise InputValidationError(
                "missing regular collected artifact", status="missing_artifact"
            )
        if artifact.path.stat().st_size > MAX_BUNDLE_BYTES:
            raise InputValidationError("artifact exceeds 256 MiB limit")
        data = artifact.path.read_bytes()
    if len(data) > MAX_BUNDLE_BYTES:
        raise InputValidationError("artifact exceeds 256 MiB limit")
    if len(data) != artifact.bytes or sha256(data) != artifact.sha256:
        raise InputValidationError("artifact receipt hash or byte count mismatch")
    return data


def require_material(request: GradingRequest, name: str) -> bytes:
    if name not in request.materials:
        raise InputValidationError(f"missing required material: {name}", status="missing_artifact")
    return material_bytes(request.materials[name])


def archive_files(data: bytes) -> dict[str, bytes]:
    """Inspect a bounded regular-file tar without writing anything (offline safe)."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for entry in archive:
                path = PurePosixPath(entry.name)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.name:
                    raise InputValidationError("unsafe tar member path")
                if entry.isdir():
                    continue
                if not entry.isfile() or str(path) in files:
                    raise InputValidationError(
                        "tar links, special files and duplicate members are forbidden"
                    )
                if str(path) == "." or any(
                    previous in {str(parent) for parent in path.parents}
                    or str(PurePosixPath(previous)).startswith(str(path) + "/")
                    for previous in files
                ):
                    raise InputValidationError("tar file/directory path collision")
                total += entry.size
                if total > MAX_BUNDLE_BYTES or len(files) >= 10000:
                    raise InputValidationError("unpacked material exceeds collection limits")
                stream = archive.extractfile(entry)
                if stream is None:
                    raise InputValidationError("unreadable tar member")
                files[str(path)] = stream.read()
    except (tarfile.TarError, OSError) as exc:
        raise InputValidationError(f"invalid grading tar: {exc}") from exc
    return files


def write_files(
    files: Mapping[str, bytes], root: Path, modes: Mapping[str, int] | None = None
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755 if modes and modes.get(relative, 0) & 0o111 else 0o644)


def input_hashes(request: GradingRequest) -> dict[str, str]:
    return {
        **{f"material:{key}": item.sha256 for key, item in request.materials.items()},
        **{f"artifact:{key}": item.sha256 for key, item in request.artifacts.items()},
    }


def immutable_image(request: GradingRequest) -> str:
    image = request.config.get("image")
    if not isinstance(image, str) or not IMMUTABLE_IMAGE.fullmatch(image):
        raise InputValidationError("image must be a local sha256 ID or registry@sha256 digest")
    return image


def run_docker(args: list[str], *, timeout: float = 60) -> str:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {proc.stderr[-2000:]}")
    return proc.stdout.strip()


def logged_process(argv: list[str], path: Path, *, timeout: float) -> int:
    """Stream at most 16 MiB to disk; a noisy verifier cannot exhaust the host."""
    deadline = TimeBudget(timeout)
    limit = 16 * 1024 * 1024
    written = path.stat().st_size if path.exists() else 0
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
        assert proc.stdout is not None
        try:
            with selectors.DefaultSelector() as selector, path.open("ab") as log:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    for key, _ in selector.select(deadline.remaining(1)):
                        data = os.read(key.fd, 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        written += len(data)
                        if written > limit:
                            raise RuntimeError("verifier/build log exceeds 16 MiB limit")
                        log.write(data)
            return proc.wait(timeout=deadline.remaining())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def resolve_image(image: str, *, timeout: float, budget: TimeBudget | None = None) -> str:
    budget = budget or TimeBudget(timeout)
    try:
        output = run_docker(["image", "inspect", image], timeout=budget.remaining(30))
    except RuntimeError:
        if image.startswith("sha256:"):
            raise
        run_docker(["pull", image], timeout=budget.remaining())
        output = run_docker(["image", "inspect", image], timeout=budget.remaining(30))
    identity = json.loads(output)[0]["Id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise RuntimeError("Docker did not return immutable image identity")
    return identity


def build_environment(context: Path, dockerfile: str, output: Path, *, timeout: float) -> str:
    """Build exact official context, recording all output and final content ID."""
    iidfile = output / "image-id.txt"
    code = logged_process(
        [
            "docker",
            "build",
            "--iidfile",
            str(iidfile),
            "-f",
            str(context / dockerfile),
            str(context),
        ],
        output / "image-build.log",
        timeout=timeout,
    )
    if code or not iidfile.is_file():
        raise RuntimeError("official environment build failed; see image-build.log")
    image = iidfile.read_text().strip()
    if not IMMUTABLE_IMAGE.fullmatch(image):
        raise RuntimeError("official build returned an invalid image ID")
    return image


class VerifierContainer:
    def __init__(
        self,
        image: str,
        output: Path,
        *,
        memory_mb: int = 4096,
        cpus: int = 2,
        budget: TimeBudget | None = None,
    ) -> None:
        self.image = image
        self.output = output
        self.name = "ad-grade-" + uuid.uuid4().hex
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.budget = budget

    def remaining(self, cap: float) -> float:
        return self.budget.remaining(cap) if self.budget else cap

    def __enter__(self) -> VerifierContainer:
        try:
            run_docker(
                [
                    "create",
                    "--name",
                    self.name,
                    "--network=none",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=256",
                    f"--memory={self.memory_mb}m",
                    f"--cpus={self.cpus}",
                    "--entrypoint",
                    "/bin/sh",
                    self.image,
                    "-c",
                    "while :; do sleep 3600; done",
                ],
                timeout=self.remaining(60),
            )
            run_docker(["start", self.name], timeout=self.remaining(60))
            self.command(
                [
                    "mkdir",
                    "-p",
                    "/tests",
                    "/logs/verifier",
                    "/logs/artifacts",
                    "/inputs",
                    "/grader",
                ],
                user="0",
            )
            self.command(["chmod", "777", "/logs/verifier", "/logs/artifacts"], user="0")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_: object) -> None:
        cleanup_error = None
        try:
            # Cleanup has a separate bounded allowance after the execution
            # deadline; an expired verifier must still be forcibly removed.
            run_docker(["rm", "--force", self.name], timeout=30)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            cleanup_error = str(exc)
        receipt = {
            "container_name": self.name,
            "image_digest": self.image,
            "completed": cleanup_error is None,
            "error": cleanup_error,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "container-cleanup.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if cleanup_error is not None:
            raise RuntimeError(f"verifier container cleanup failed: {cleanup_error}")

    def command(
        self,
        argv: list[str],
        *,
        timeout: float = 60,
        user: str | None = None,
        workdir: str | None = None,
        log_name: str = "verifier.log",
    ) -> tuple[int, str]:
        args = ["docker", "exec"]
        if user is not None:
            args += ["--user", user]
        if workdir is not None:
            args += ["--workdir", workdir]
        args += [self.name, *argv]
        code = logged_process(args, self.output / log_name, timeout=self.remaining(timeout))
        with (self.output / log_name).open("rb") as log:
            log.seek(max(0, log.seek(0, 2) - 20000))
            data = log.read(20000).decode(errors="replace")
        return code, data

    def copy_in(self, source: Path, destination: str) -> None:
        target = PurePosixPath(destination)
        if not target.is_absolute() or ".." in target.parts:
            raise InputValidationError("unsafe verifier input destination")
        directory = source.is_dir()
        code, _ = self.command(
            ["mkdir", "-p", str(target if directory else target.parent)], user="0"
        )
        if code:
            raise RuntimeError("verifier input directory setup failed")
        source_path = str(source) + ("/." if directory else "")
        run_docker(["cp", source_path, f"{self.name}:{destination}"], timeout=self.remaining(60))

    def copy_out(self, path: str, name: str) -> Path | None:
        destination = self.output / name
        # Reject missing/oversize/link outputs inside the container before Docker
        # streams bytes back to the host. Trusted argv only; paths are fixed.
        code, _ = self.command(
            [
                "sh",
                "-c",
                'test -f "$1" && test ! -L "$1" && test "$(wc -c < "$1")" -le 268435456',
                "check-output",
                path,
            ],
            log_name="export.log",
        )
        if code:
            return None
        try:
            run_docker(["cp", f"{self.name}:{path}", str(destination)], timeout=self.remaining(60))
        except RuntimeError:
            return None
        if destination.is_symlink() or not destination.is_file():
            if destination.is_dir():
                shutil.rmtree(destination)
            return None
        if destination.stat().st_size > MAX_BUNDLE_BYTES:
            destination.unlink()
            return None
        return destination
