# Spec-0047/T2：实验配置、路径派生与 fail-closed 校验。
"""ExperimentConfig is the operator input; secrets never belong here."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ID_MAX = 48
_SECRET_KEY_RE = re.compile(r"(token|password|secret|api[_-]?key|credential)", re.I)


class ConfigError(ValueError):
    """Invalid experiment id, path, isolation, or secret-bearing config."""


@dataclass(frozen=True)
class ExperimentConfig:
    schema_version: int
    experiment_id: str
    mode: str
    source: dict[str, Any]
    images: dict[str, str]
    models: dict[str, str]
    capacity: dict[str, Any]
    infrastructure: dict[str, str]
    retention: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ExperimentConfig:
        _reject_secrets(node=data, path="$")
        experiment_id = validate_experiment_id(raw=str(data.get("experiment_id") or ""))
        isolation = str((data.get("infrastructure") or {}).get("isolation") or "dedicated")
        if isolation not in ("dedicated", "shared-dev"):
            raise ConfigError(f"infrastructure.isolation 非法：{isolation}")
        mode = str(data.get("mode") or "full-evolution")
        if mode not in ("user-only", "design-only", "delivery-only", "full-evolution"):
            raise ConfigError(f"mode 非法：{mode}")
        images = dict(data.get("images") or {})
        for name, ref in images.items():
            if str(ref).endswith(":latest") or str(ref) == "latest":
                raise ConfigError(f"images.{name} 禁止 latest")
        return cls(
            schema_version=int(data.get("schema_version") or 1),
            experiment_id=experiment_id,
            mode=mode,
            source=dict(data.get("source") or {}),
            images=images,
            models=dict(data.get("models") or {}),
            capacity=dict(data.get("capacity") or {}),
            infrastructure=dict(data.get("infrastructure") or {"isolation": isolation}),
            retention=dict(data.get("retention") or {"keep_on_stop": True}),
            raw=data,
        )


def validate_experiment_id(*, raw: str) -> str:
    text = raw.strip()
    if not _ID_RE.fullmatch(text) or len(text) > _ID_MAX:
        raise ConfigError(
            f"experiment_id 非法 {raw!r}：仅小写字母数字与单连字符，最长 {_ID_MAX}"
        )
    return text


def experiments_root() -> Path:
    raw = os.environ.get("EXPERIMENTS_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    backend = Path(__file__).resolve().parents[2]
    return (backend.parent / "auto-designer-experiments").resolve()


def config_hash(*, data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compose_project(*, experiment_id: str, cfg_hash: str) -> str:
    suffix = cfg_hash[:8]
    base = f"adx-{experiment_id}-{suffix}"
    return base[:63]


def experiment_paths(*, experiment_id: str, root: Path | None = None) -> dict[str, Path]:
    base = (root or experiments_root()) / experiment_id
    ensure_under_root(root=root or experiments_root(), path=base)
    return {
        "root": base,
        "config": base / "config.yaml",
        "manifest": base / "manifest.json",
        "journal": base / "journal.jsonl",
        "checkpoints": base / "checkpoints",
        "telemetry": base / "telemetry",
        "logs": base / "logs",
        "sessions": base / "sessions",
        "workspaces": base / "workspaces",
        "source": base / "source",
        "infrastructure": base / "infrastructure",
        "secrets": base / "secrets",
        "archive": base / "archive",
        "data": base / "data",
    }


def ensure_under_root(*, root: Path, path: Path) -> Path:
    root_r = root.resolve()
    real = path.resolve()
    if path.exists() and path.is_symlink():
        raise ConfigError(f"禁止符号链接路径：{path}")
    try:
        real.relative_to(root_r)
    except ValueError as exc:
        raise ConfigError(f"路径越出实验根 {root_r}：{path}") from exc
    return real


def _reject_secrets(*, node: object, path: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if _SECRET_KEY_RE.search(str(key)):
                raise ConfigError(f"配置禁止密钥字段 {path}.{key}")
            _reject_secrets(node=value, path=f"{path}.{key}")
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _reject_secrets(node=value, path=f"{path}[{idx}]")
    elif isinstance(node, str) and _looks_like_secret(text=node):
        raise ConfigError(f"配置值疑似密钥：{path}")


def _looks_like_secret(*, text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(("sk-", "gitea_")) and len(stripped) > 20:
        return True
    return False
