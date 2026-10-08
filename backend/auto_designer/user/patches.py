"""Immutable full session predictions for post-run grading (Spec-0075/T1)."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")


class PredictionArtifactError(ValueError):
    """An export cannot be bound to an immutable, safe session prediction."""


def _open_directory(path: Path) -> int:
    absolute = path.absolute()
    if ".." in absolute.parts:
        raise PredictionArtifactError("prediction root contains traversal")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_existing(directory: int, name: str) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PredictionArtifactError("prediction target is not a regular file")
        return handle.read()


def preserve_prediction(
    *, sessions_root: Path, session_id: str, patch: str, patch_sha256: str
) -> dict:
    """Publish full UTF-8 bytes once; retries may only reuse identical bytes.

    Directory descriptors and no-follow opens reject symlink escapes, including
    existing ancestor/target links. A hard-link publication is atomic and cannot
    replace another process's prediction. The public receipt contains no host paths.
    """
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise PredictionArtifactError("unsafe prediction session id")
    if not isinstance(patch, str):
        raise PredictionArtifactError("prediction export is not text")
    payload = patch.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    if patch_sha256 != digest:
        raise PredictionArtifactError("prediction export digest mismatch")
    directory = _open_directory(Path(sessions_root).parent / "predictions")
    name = f"{session_id}.patch"
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _read_existing(directory, name) != payload:
                raise PredictionArtifactError(
                    "session prediction already has different bytes"
                ) from None
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)
    return {
        "contract_version": 1,
        "session_id": session_id,
        "path": f"predictions/{name}",
        "sha256": digest,
        "bytes": len(payload),
    }
