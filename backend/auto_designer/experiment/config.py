# Spec-0047/T2：实验配置、路径派生与 fail-closed 校验。
"""Spec-0071/T3: strict public v2 configuration and shared identity helpers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ID_MAX = 48
_SECRET_KEY_RE = re.compile(r"(token|password|secret|api[_-]?key|credential)", re.I)


class ConfigError(ValueError):
    """Invalid experiment id, path, isolation, or secret-bearing config."""


def validate_experiment_id(*, raw: str) -> str:
    text = raw.strip()
    if not _ID_RE.fullmatch(text) or len(text) > _ID_MAX:
        raise ConfigError(f"experiment_id 非法 {raw!r}：仅小写字母数字与单连字符，最长 {_ID_MAX}")
    return text


def config_hash(*, data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compose_project(*, experiment_id: str, cfg_hash: str) -> str:
    suffix = cfg_hash[:8]
    base = f"adx-{experiment_id}-{suffix}"
    return base[:63]


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
            "Expected schema_version=2; historical configurations require explicit migration using their frozen checkout (research/README.md)"
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
