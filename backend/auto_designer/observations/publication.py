"""Collect bounded opaque artifact files and publish immutable session evidence."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import selectors
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

from auto_designer.invocation import _redact

MAX_BUNDLE = 16_000_000
MAX_FILE = 4_500_000
MAX_FILES = 128


def preflight_root(root: Path) -> None:
    """Verify archive permissions before an interaction starts, not at cleanup."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or shutil.disk_usage(root).free < MAX_BUNDLE * 4:
        raise OSError("observation storage is linked or lacks collection headroom")
    pending = list((root / "collection-failures").glob("*.json"))
    if len(pending) >= 8:
        raise OSError("observation recovery backlog needs maintenance before a new experiment")
    with tempfile.TemporaryFile(dir=root) as probe:
        probe.write(b"observation-preflight")
        probe.flush()
        probe.seek(0)
        if probe.read() != b"observation-preflight":
            raise OSError("observation storage preflight failed")


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or str(path) == "."
    ):
        raise ValueError("invalid observation path")
    return str(path)


def framework_version() -> str:
    """Fingerprint the fixed collector code, including an uncommitted development build."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def bounded_command(argv: list[str], *, timeout: float, limit: int) -> bytes:
    """Drain a subprocess with bounded bytes/time; never buffer arbitrary stderr."""
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        chunks = []
        total = 0
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("observation collection timed out")
                    data = os.read(proc.stdout.fileno(), min(65536, limit + 1 - total))
                    if not data:
                        break
                    total += len(data)
                    if total > limit:
                        raise ValueError("observation collection exceeds budget")
                    chunks.append(data)
                if proc.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                    raise OSError("observation collection command failed")
            return b"".join(chunks)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)


def archive_files(raw: bytes) -> dict[str, bytes]:
    """Read docker-cp tar without extracting links, paths or executable content."""
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for index, member in enumerate(archive):
            if index > MAX_FILES * 4:
                raise ValueError("too many archive entries")
            if member.isdir() and member.name.rstrip("/") in (".", ""):
                continue
            path = PurePosixPath(safe_relative(member.name.rstrip("/")))
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_FILE:
                raise ValueError("unsafe observation archive entry")
            name = safe_relative(str(path))
            total += member.size
            if name in files or total > MAX_BUNDLE:
                raise ValueError("duplicate entry or oversized observation archive")
            files[name] = archive.extractfile(member).read(MAX_FILE + 1)
    # docker cp DIR/. emits './file' on recent engines; DIR emits 'DIR/file'.
    if "manifest.json" not in files and files:
        roots = {PurePosixPath(name).parts[0] for name in files}
        if len(roots) == 1 and all(len(PurePosixPath(name).parts) > 1 for name in files):
            files = {
                str(PurePosixPath(*PurePosixPath(name).parts[1:])): data
                for name, data in files.items()
            }
    return files


def local_files(root: Path) -> dict[str, bytes]:
    """Collect only the artifact's declared regular files, without following links."""
    if root.is_symlink():
        raise ValueError("linked observation root")

    def read(name: str) -> bytes:
        parts = PurePosixPath(safe_relative(name)).parts
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except OSError as exc:
            raise ValueError("unsafe or unavailable observation file") from exc
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
                raise ValueError("unsafe observation file")
            return stream.read(MAX_FILE + 1)

    manifest = read("manifest.json")
    value = json.loads(manifest)
    entries = value.get("files", [])
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError("invalid file list")
    out = {"manifest.json": manifest}
    for entry in entries:
        name = safe_relative(entry["path"])
        out[name] = read(name)
        if sum(map(len, out.values())) > MAX_BUNDLE:
            raise ValueError("oversized observation bundle")
    return out


def publish(
    *, root: Path, session_id: str, run_id: str, version: dict, files: dict[str, bytes]
) -> dict:
    """Atomically publish a validated run; never overwrite historical evidence."""
    for identifier in (session_id, run_id):
        if safe_relative(identifier) != identifier or "/" in identifier:
            raise ValueError("invalid observation identity")
    if len(files.get("manifest.json", b"")) > 64000:
        raise ValueError("oversized manifest")
    artifact = json.loads(files["manifest.json"])
    entries = artifact.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
        raise ValueError("invalid observation file list")
    reading = safe_relative(artifact["reading"])
    exported: dict[str, bytes] = {}
    for entry in entries:
        name = safe_relative(entry["path"])
        if name in exported or name == "manifest.json":
            raise ValueError("duplicate or reserved file")
        data = files[name]
        if len(data) > MAX_FILE:
            raise ValueError("oversized observation file")
        text = _redact(text=data.decode("utf-8"))
        if text is None:
            raise ValueError("observation redaction failed")
        exported[name] = text.encode()
    if reading not in exported or sum(map(len, exported.values())) > MAX_BUNDLE:
        raise ValueError("missing reading guide or oversized bundle")
    declared = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        for name, data in sorted(exported.items())
    ]
    manifest = {
        "session_id": session_id,
        "run_id": run_id,
        "artifact": version,
        "reading": reading,
        "status": "complete" if artifact.get("status") == "complete" else "partial",
        "files": declared,
        "redaction": "platform-filtered",
    }
    session = root / session_id
    session.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (session / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        dest = session / "runs" / run_id
        previous = list((session / "runs").glob("*/manifest.json"))
        previous_count = sum(
            1 + len(json.loads(p.read_text())["files"]) for p in previous if p.parent != dest
        )
        if previous_count + 1 + len(declared) > 256:
            raise ValueError("session observation index exceeds budget")
        if dest.exists():
            if json.loads((dest / "manifest.json").read_text()) != manifest:
                raise ValueError("immutable observation run conflicts")
            for entry in declared:
                data = (dest / entry["path"]).read_bytes()
                if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("immutable observation file changed")
        else:
            stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=session))
            try:
                for name, data in exported.items():
                    path = stage / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
                dest.parent.mkdir(exist_ok=True)
                stage.rename(dest)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        index_files = []
        runs = []
        for path in sorted((session / "runs").glob("*/manifest.json")):
            value = json.loads(path.read_text())
            prefix = path.parent.relative_to(session).as_posix()
            index_files.append(
                {
                    "path": f"{prefix}/manifest.json",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
            index_files.extend({**e, "path": f"{prefix}/{e['path']}"} for e in value["files"])
            runs.append(
                {
                    "run_id": value["run_id"],
                    "artifact": value["artifact"],
                    "manifest": f"{prefix}/manifest.json",
                    "status": value["status"],
                }
            )
        if len(index_files) > 256:
            raise ValueError("session observation index exceeds budget")
        temp = session / ".index.tmp"
        temp.write_text(
            json.dumps(
                {"session_id": session_id, "runs": runs, "files": index_files}, ensure_ascii=False
            )
        )
        temp.replace(session / "manifest.json")
    return {
        "status": manifest["status"],
        "manifest": str(session / "manifest.json"),
        "run_id": run_id,
    }


def verify_published(*, root: Path, session_id: str, run_id: str, version: dict) -> dict | None:
    """Reuse an immutable run only after verifying its identity and every retained file."""
    for identifier in (session_id, run_id):
        if safe_relative(identifier) != identifier or "/" in identifier:
            raise ValueError("Invalid published observation identity")
    directory = Path(root) / session_id / "runs" / run_id
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError("Linked published observation directory")
    if not directory.exists():
        return None
    files = local_files(directory)
    manifest = json.loads(files["manifest.json"])
    if (
        manifest.get("session_id") != session_id
        or manifest.get("run_id") != run_id
        or manifest.get("artifact") != version
        or manifest.get("status") not in {"complete", "partial"}
        or manifest.get("redaction") != "platform-filtered"
    ):
        raise ValueError("Published observation provenance mismatch")
    seen = set()
    for item in manifest["files"]:
        name = safe_relative(item["path"])
        if name in seen or name == "manifest.json":
            raise ValueError("Duplicate published observation file")
        seen.add(name)
        body = files[name]
        if item.get("bytes") != len(body) or item.get("sha256") != hashlib.sha256(body).hexdigest():
            raise ValueError("Published observation content changed")
    if manifest.get("reading") not in seen:
        raise ValueError("Published observation reading guide missing")
    # Run files are authoritative; repair a derived index if the controller stopped before it.
    return publish(root=root, session_id=session_id, run_id=run_id, version=version, files=files)


class ObservationSource:
    """Bind trusted launch provenance and collect without knowing the runtime schema."""

    def __init__(
        self, *, directory: str, container_id: str | None, version: dict, expected: bool = True
    ) -> None:
        self.directory = directory
        self.container_id = container_id
        self.version = dict(version)
        self.run_id = uuid.uuid4().hex
        self.expected = expected

    def collect(self, *, root: Path, session_id: str) -> dict:
        if not self.expected:
            return {"status": "not_supported", "run_id": self.run_id, "artifact": self.version}
        error = None
        for _ in range(2):
            try:
                files = (
                    archive_files(
                        bounded_command(
                            ["docker", "cp", f"{self.container_id}:{self.directory}/.", "-"],
                            timeout=10,
                            limit=MAX_BUNDLE,
                        )
                    )
                    if self.container_id
                    else local_files(Path(self.directory))
                )
                return publish(
                    root=root,
                    session_id=session_id,
                    run_id=self.run_id,
                    version=self.version,
                    files=files,
                )
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                RecursionError,
                TimeoutError,
                tarfile.TarError,
            ) as exc:
                error = type(exc).__name__
        # Infrastructure failures do not become harness evolution proposals.
        receipt = {
            "status": "unavailable",
            "reason": error,
            "run_id": self.run_id,
            "session_id": session_id,
            "artifact": self.version,
            "source_directory": self.directory,
            "container_id": self.container_id,
            "retain_source": True,
        }
        root.mkdir(parents=True, exist_ok=True)
        receipts = root / "collection-failures"
        receipts.mkdir(exist_ok=True, mode=0o700)
        path = receipts / f"{session_id}-{self.run_id}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(receipt))
        temp.replace(path)
        return receipt


def recover(*, receipt_path: Path, root: Path) -> dict:
    """Retry one retained source; never delete a container or change its running state."""
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("status") != "unavailable" or not receipt.get("retain_source"):
        raise ValueError("not an observation recovery receipt")
    source = ObservationSource(
        directory=receipt["source_directory"],
        container_id=receipt["container_id"],
        version=receipt["artifact"],
    )
    source.run_id = receipt["run_id"]
    result = source.collect(root=root, session_id=receipt["session_id"])
    if result["status"] != "unavailable":
        history = root / "collection-recovered"
        history.mkdir(exist_ok=True, mode=0o700)
        receipt_path.replace(history / receipt_path.name)
        result["retained_source_cleanup"] = "manual_after_verifying_archive"
    return result
