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
        raise ConfigError(f"experiment_id 非法 {raw!r}：仅小写字母数字与单连字符，最长 {_ID_MAX}")
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
        "runtime": base / "runtime",
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


# Spec-0069/T1: the public version is deliberately separate from historical v1.
def load_config_v2(path: str | Path) -> dict[str, Any]:
    """Read a public experiment definition and resolve input paths, without I/O resources."""
    config_path = Path(path).expanduser().resolve()
    data = read_json_document(path=config_path)
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ConfigError(
            "Expected schema_version=2; historical configurations require explicit migration"
        )
    validate_schema(document=data, schema_name="experiment-v2.json")
    _reject_plaintext_credentials(node=data, location="config")
    runtime = data["runtime"]
    backend = runtime["backend"]
    if backend == "local":
        if "e2b" in runtime or runtime["gitea"]["provider"] != "localhost":
            raise ConfigError("local requires localhost Gitea and forbids e2b settings")
    elif "local" in runtime or "e2b" not in runtime or runtime["gitea"]["provider"] != "gitea.com":
        raise ConfigError("e2b requires e2b settings and Gitea.com; local settings are forbidden")
    harness = data["harness"]
    if harness["source"] == "archive":
        if "archive" not in harness or "sha256" not in harness:
            raise ConfigError("archive Harness requires archive and sha256")
        harness["archive"] = resolve_input_path(value=harness["archive"], base=config_path.parent)
    elif set(harness) != {"source"}:
        raise ConfigError("builtin Harness forbids archive/sha256 settings")
    for field in ("task_package", "persona_library"):
        data["workload"][field] = resolve_input_path(
            value=data["workload"][field], base=config_path.parent
        )
    rounds = data["rounds"]
    sessions = rounds["sessions_per_round"]
    if sessions > len(data["workload"]["persona_ids"]):
        raise ConfigError("sessions_per_round cannot exceed the number of unique persona_ids")
    if rounds["max_parallel_users"] > sessions:
        raise ConfigError("max_parallel_users cannot exceed sessions_per_round")
    for image in runtime.get("local", {}).values():
        if isinstance(image, str) and (image == "latest" or image.endswith(":latest")):
            raise ConfigError("Local image references must use an explicit version or digest")
    from urllib.parse import urlsplit

    for source in data.get("source", {}).values():
        url = urlsplit(source["repository"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query:
            raise ConfigError("source repository must be credential-free HTTPS")
    return data


def load_task_package(path: str | Path) -> dict[str, Any]:
    """Validate the task recipe. Gold patches/hidden tests have no schema fields."""
    package_path = Path(path).expanduser().resolve()
    data = read_json_document(path=package_path)
    validate_schema(document=data, schema_name="task-package-v1.json")
    _reject_plaintext_credentials(node=data, location="task")
    for field in ("instruction_file",):
        data[field] = resolve_input_path(value=data[field], base=package_path.parent)
    for field in ("script", "requirements_lock"):
        data["setup"][field] = resolve_input_path(
            value=data["setup"][field], base=package_path.parent
        )
    source = data["source"]
    if source["kind"] == "local":
        source["path"] = resolve_input_path(value=source["path"], base=package_path.parent)
        if data["kind"] == "swebench":
            raise ConfigError("SWE-bench requires a fixed Git source with repo/revision metadata")
    else:
        from urllib.parse import urlsplit

        url = urlsplit(source["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query:
            raise ConfigError("task Git URL must be credential-free HTTPS without query parameters")
    if data["kind"] == "ordinary" and data.get("not_in_benchmark") is not True:
        raise ConfigError("ordinary task must explicitly declare not_in_benchmark=true")
    if data["kind"] == "swebench" and "not_in_benchmark" in data:
        raise ConfigError("SWE-bench must not declare not_in_benchmark")
    return data


def read_json_document(*, path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot read JSON input {path}: {exc}") from exc


def validate_schema(*, document: Any, schema_name: str) -> None:
    from jsonschema import Draft202012Validator

    schema = read_json_document(path=Path(__file__).parent / "schemas" / schema_name)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: str(list(error.absolute_path)),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ConfigError(f"{location}: {error.message}")


def resolve_input_path(*, value: str, base: Path) -> str:
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else base / path).resolve())


def _reject_plaintext_credentials(*, node: Any, location: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if _SECRET_KEY_RE.search(key) and not key.endswith("_env"):
                raise ConfigError(f"Plaintext credential field forbidden: {location}.{key}")
            _reject_plaintext_credentials(node=value, location=f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_plaintext_credentials(node=value, location=f"{location}[{index}]")
    elif isinstance(node, str) and _looks_like_secret(text=node):
        raise ConfigError(f"Possible plaintext credential at {location}")
