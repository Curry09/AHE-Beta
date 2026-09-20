#!/usr/bin/env python3
"""Atomic Harbor batch checkpoint storage for the evaluation suite."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "hse-checkpoint-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checkpoint(path: Path, payload: dict[str, Any]) -> str:
    """Atomically write a checkpoint and return its content hash.

    A completed trial is never removed from ``completed_trials``. Callers must
    append a new checkpoint sequence instead of mutating an older artifact.
    """
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"checkpoint schema must be {SCHEMA_VERSION}")
    for key in ("experiment_id", "batch_id", "config_sha256", "manifest_sha256", "completed_trials", "pending_trials"):
        if key not in payload:
            raise ValueError(f"checkpoint missing {key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return sha256(path)


def load_checkpoint(path: Path, *, config_sha256: str, manifest_sha256: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported checkpoint schema")
    if payload.get("config_sha256") != config_sha256:
        raise ValueError("checkpoint config hash does not match the requested run")
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError("checkpoint manifest hash does not match the requested run")
    return payload
