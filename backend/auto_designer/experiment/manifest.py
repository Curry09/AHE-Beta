# Spec-0047/T2：不可变 manifest 与 append-only journal。
"""create is exclusive; later facts go to journal.jsonl, never rewrite manifest."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import ConfigError

_LOCK = threading.Lock()


class ManifestError(ConfigError):
    """Manifest already exists, missing, or journal write failed."""


def create_manifest(*, path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise ManifestError(f"manifest 已存在，拒绝覆盖：{path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def read_manifest(*, path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"缺少 manifest：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ManifestError(f"manifest 必须为 JSON object：{path}")
    return value


def recovery_identity(manifest: dict[str, Any]) -> dict[str, str]:
    """Return the immutable fields shared by controller and demand process."""
    fields = ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash")
    values = {field: str(manifest.get(field) or "").strip() for field in fields}
    missing = [field for field, value in values.items() if not value]
    if missing:
        raise ManifestError(
            "manifest 缺恢复身份字段：" + ", ".join(missing) + "；旧实验不能直接细粒度续跑"
        )
    return values


def assert_immutable(*, path: Path, expected: dict[str, Any]) -> None:
    current = read_manifest(path=path)
    if current != expected:
        raise ManifestError("manifest 漂移：禁止把动态事实写回 manifest")


def append_journal(
    *, path: Path, action: str, from_state: str, to_state: str, resources: dict[str, Any]
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        seq = _next_seq(path=path)
        row = {
            "seq": seq,
            "ts": datetime.now(UTC).isoformat(),
            "from": from_state,
            "to": to_state,
            "action": action,
            "resources": resources,
            "error": None,
        }
        line = json.dumps(row, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return row


def last_state(*, path: Path) -> str:
    if not path.is_file():
        return "ABSENT"
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return "ABSENT"
    return str(json.loads(lines[-1]).get("to") or "ABSENT")


def _next_seq(*, path: Path) -> int:
    if not path.is_file():
        return 1
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return 1
    return int(json.loads(lines[-1])["seq"]) + 1
