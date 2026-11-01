"""Spec-0081/T2: verified task inputs; no provider or experiment orchestration."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath


class MaterialError(ValueError):
    """A task input could not be verified or safely materialized."""


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _download_progress(*, task_id: str, input_id: str) -> Callable[[int], None]:
    last_update = time.monotonic()

    def report_bytes(transferred: int) -> None:
        nonlocal last_update
        current = time.monotonic()
        if current - last_update >= 15:
            print(
                f"[materials] {task_id}/{input_id}: {transferred} bytes downloaded",
                file=sys.stderr,
                flush=True,
            )
            last_update = current

    return report_bytes


def _verified_file(*, path: Path, expected: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise MaterialError("Material is missing or is not a regular, unlinked file")
    if sha256_file(path) != expected:
        raise MaterialError("Task material SHA-256 mismatch")
    return path


def fetch_material(
    *, material: dict, cache: Path, progress: Callable[[int], None] | None = None
) -> Path:
    """Atomically cache verified bytes, keeping corrupt/partial downloads invisible."""
    expected = material["sha256"]
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise MaterialError("A full SHA-256 is required before caching material")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / expected
    if target.is_file():
        return _verified_file(path=target, expected=expected)
    with (cache / (expected + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_file():
            return _verified_file(path=target, expected=expected)
        descriptor, name = tempfile.mkstemp(prefix=".material-", dir=cache)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                if "path" in material:
                    source = _verified_file(path=Path(material["path"]), expected=expected)
                    with source.open("rb") as stream:
                        shutil.copyfileobj(stream, output)
                else:
                    request = urllib.request.Request(
                        material["url"], headers={"User-Agent": "auto-designer-task-materials"}
                    )
                    with urllib.request.urlopen(request, timeout=60) as response:
                        transferred = 0
                        while chunk := response.read(1024**2):
                            output.write(chunk)
                            transferred += len(chunk)
                            if progress is not None:
                                progress(transferred)
                output.flush()
                os.fsync(output.fileno())
            _verified_file(path=temporary, expected=expected)
            temporary.chmod(0o600)
            temporary.replace(target)
        except (OSError, ValueError) as exc:
            raise MaterialError(
                "Task material acquisition failed; verified cache retained"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
    return target


def _relative_member(*, name: str) -> str:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise MaterialError("Task archive member escapes its input root")
    return path.as_posix()


def materialize_input(*, material: dict, destination: Path) -> dict[str, str]:
    """Verify and extract into an empty owned directory; never follow archive links."""
    source = _verified_file(path=Path(material["path"]), expected=material["sha256"])
    if material.get("format") not in {"tar", "tar.gz", "file"}:
        raise MaterialError("Unknown task material format")
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise MaterialError("Linked material destination")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise MaterialError("Material destination must be empty")
    inventory = {}
    try:
        if material["format"] == "file":
            name = "input"
            shutil.copyfile(source, destination / name)
            inventory[name] = material["sha256"]
        else:
            with tarfile.open(source, "r:*") as archive:
                seen = set()
                for member in archive:
                    name = _relative_member(name=member.name)
                    if name == "." and member.isdir():
                        continue
                    if name in seen:
                        raise MaterialError("Duplicate task archive member")
                    seen.add(name)
                    target = destination / name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile():
                        raise MaterialError("Task archive contains a link or special file")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise MaterialError("Unreadable task archive member")
                    with stream, target.open("xb") as output:
                        shutil.copyfileobj(stream, output)
                    target.chmod(member.mode & 0o777)
                    inventory[name] = sha256_file(target)
        expected_files = material.get("files")
        if expected_files is not None and inventory != expected_files:
            raise MaterialError("Task material file inventory differs from declared input")
    except (tarfile.TarError, OSError) as exc:
        raise MaterialError("Task input materialization failed") from exc
    return inventory


def check_materials(*, package: dict, cache: Path | None = None) -> list[dict]:
    """Inspect local references without networking or creating cache directories."""
    from .contract import environment_materials

    result = []
    for item in environment_materials(package):
        material = item["material"]
        candidate = Path(material["path"]) if "path" in material else None
        if candidate is None and cache is not None:
            candidate = cache / material["sha256"]
        if candidate is not None and candidate.exists():
            _verified_file(path=candidate, expected=material["sha256"])
            state = "verified_local"
        elif "url" in material:
            state = "pending_download"
        else:
            raise MaterialError(f"Missing local task material: {item['id']}")
        result.append({"id": item["id"], "sha256": material["sha256"], "status": state})
    return result


def freeze_environment(
    *, package: dict, directory: Path, stage: Path, cache: Path
) -> tuple[dict, dict]:
    """Return a relocatable package plus immutable input/provenance files to register."""
    from .contract import environment_materials

    frozen = copy.deepcopy(package)
    originals = environment_materials(package)
    # environment_materials may return copies; replace the actual package inputs by id.
    actual = {row["id"]: row for row in frozen["environment"].get("inputs", [])}
    files = {}
    origins = []
    for item in originals:
        identifier = item["id"]
        material = item["material"]
        print(
            f"[materials] {package['id']}/{identifier}: verifying input",
            file=sys.stderr,
            flush=True,
        )
        cached = fetch_material(
            material=material,
            cache=cache,
            progress=_download_progress(task_id=package["id"], input_id=identifier),
        )
        suffix = (
            ".tar.gz"
            if material["format"] == "tar.gz"
            else ".tar"
            if material["format"] == "tar"
            else ".file"
        )
        target = directory / "inputs" / (identifier + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, target)
        # Validate archive shape/inventory before any task environment sees it.
        with tempfile.TemporaryDirectory(prefix=".verify-input-", dir=directory) as temp:
            inventory = materialize_input(
                material={**material, "path": str(target)}, destination=Path(temp)
            )
        normalized = {k: v for k, v in material.items() if k not in {"path", "url"}}
        normalized["path"] = target.relative_to(stage).as_posix()
        actual[identifier]["material"] = normalized
        files["input:" + identifier] = target
        origins.append({"id": identifier, "material": material, "files": inventory})
    # Coordinates of operator-local files are not needed after immutable bytes freeze.
    for row in origins:
        if "path" in row["material"]:
            row["material"] = {k: v for k, v in row["material"].items() if k != "path"}
    origin = directory / "input-origins.json"
    origin.write_text(json.dumps(origins, ensure_ascii=False, indent=2) + "\n")
    files["input_origins"] = origin
    return frozen, files


def execution_environment(
    *, package: dict, run_root: Path, destination_root: Path | None = None
) -> dict:
    """Resolve frozen inputs strictly within a relocated run, preserving pure definitions."""
    from .contract import container_environment

    target_root = Path(destination_root) if destination_root is not None else run_root.resolve()
    if not target_root.is_absolute() or ".." in target_root.parts:
        raise MaterialError("Environment execution root must be an absolute owned coordinate")
    environment = container_environment(package)
    for item in environment.get("inputs", []):
        material = item["material"]
        relative = Path(material["path"])
        candidate = run_root / relative
        if (
            relative.is_absolute()
            or candidate.is_symlink()
            or not candidate.resolve().is_relative_to(run_root.resolve())
        ):
            raise MaterialError("Frozen environment material escapes its run")
        _verified_file(path=candidate, expected=material["sha256"])
        # A cloud coordinate is not a local filesystem path. Verify local bytes,
        # then map them without resolving unrelated local /opt symlinks.
        material["path"] = str(target_root / relative)
    return environment
