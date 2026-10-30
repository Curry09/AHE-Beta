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
    from auto_designer.experiment.model_limits import validate_model_limits

    validate_model_limits(data)
    runtime = data["runtime"]
    backend = runtime["backend"]
    if backend == "local":
        if "e2b" in runtime or runtime["gitea"]["provider"] != "localhost":
            raise ConfigError("local requires localhost Gitea and forbids e2b settings")
    elif "local" in runtime or "e2b" not in runtime or runtime["gitea"]["provider"] != "gitea.com":
        raise ConfigError("e2b requires e2b settings and Gitea.com; local settings are forbidden")
    # Spec-0077/T1: optional CI inputs do not add defaults to old frozen identities.
    local = runtime.get("local", {})
    for field in ("runner_image", "ci_job_image"):
        if field in local:
            if not local_ci_enabled(data):
                raise ConfigError(f"runtime.local.{field} requires ci_enabled=true")
            _validate_ci_image_reference(local[field])
    # Spec-0079/T4: three input selectors are one atomic public contract.
    continuation = data.get("continuation")
    parent_workload = data["workload"].get("source") == "parent"
    parent_harness = data["harness"]["source"] == "continuation"
    if any((continuation is not None, parent_workload, parent_harness)):
        if not (continuation is not None and parent_workload and parent_harness):
            raise ConfigError(
                "continuation requires harness.source=continuation and workload.source=parent"
            )
        continuation["archive"] = resolve_input_path(
            value=continuation["archive"], base=config_path.parent
        )
    harness = data["harness"]
    if harness["source"] == "archive":
        if "archive" not in harness or "sha256" not in harness:
            raise ConfigError("archive Harness requires archive and sha256")
        harness["archive"] = resolve_input_path(value=harness["archive"], base=config_path.parent)
    elif set(harness) != {"source"}:
        raise ConfigError("builtin Harness forbids archive/sha256 settings")
    # Spec-0073/T1: normalize only new operator inputs; frozen manifests bypass this loader.
    workload = data["workload"]
    if not parent_workload:
        workload["persona_library"] = resolve_input_path(
            value=workload["persona_library"], base=config_path.parent
        )
        if "task_package" in workload:
            task_path = resolve_input_path(
                value=workload.pop("task_package"), base=config_path.parent
            )
            expected_kind = workload.pop("kind")
            if load_task_package(task_path)["kind"] != expected_kind:
                raise ConfigError("task package kind differs from workload.kind")
            workload["task_packages"] = [task_path]
        else:
            workload["task_packages"] = [
                resolve_input_path(value=value, base=config_path.parent)
                for value in workload["task_packages"]
            ]
        if len(workload["task_packages"]) > 1 and runtime.get("local", {}).get("seed_image"):
            raise ConfigError("runtime.local.seed_image is only supported for a single task")
    rounds = data["rounds"]
    sessions = rounds["sessions_per_round"]
    # Spec-0080/T1: persona selection is unique; execution slots may reuse it.
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
    # Spec-0072/T1: defaults become part of the frozen, hashed public configuration.
    data["policies"] = runtime_policies(data)
    data["models"]["delivery"]["auth_type"] = delivery_auth_type(data["models"]["delivery"])
    return data


def load_task_package(path: str | Path) -> dict[str, Any]:
    """Validate the task recipe. Gold patches/hidden tests have no schema fields."""
    package_path = Path(path).expanduser().resolve()
    data = read_json_document(path=package_path)
    validate_task_package_document(data)
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
    data.setdefault("interaction", "simulated_user")
    from auto_designer.experiment.workload import validate_task_execution

    validate_task_execution(
        data, source_root=Path(source["path"]) if source["kind"] == "local" else None
    )
    return data


def validate_task_package_document(data: Any) -> None:
    """Validate operator or frozen packages without resolving or rewriting their identity."""
    version = data.get("schema_version") if isinstance(data, dict) else None
    if type(version) is not int or version not in {1, 2}:
        raise ConfigError("Expected task package schema_version=1 or 2")
    validate_schema(document=data, schema_name=f"task-package-v{version}.json")
    _reject_plaintext_credentials(node=data, location="task")
    if version == 1:
        return
    if data["kind"] == "ordinary" and data.get("not_in_benchmark") is not True:
        raise ConfigError("ordinary task must explicitly declare not_in_benchmark=true")
    if data["kind"] != "ordinary" and "not_in_benchmark" in data:
        raise ConfigError("benchmark task must not declare not_in_benchmark")
    seen_ids: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    for declaration in data.get("artifacts", {}).get("exports", []):
        identifier = declaration["id"]
        target = declaration.get("path", declaration.get("handle"))
        if identifier in seen_ids or (declaration["source"], target) in seen_targets:
            raise ConfigError("Artifact IDs and source targets must be unique")
        seen_ids.add(identifier)
        seen_targets.add((declaration["source"], target))
        if declaration["source"] == "workspace":
            # Paths name one future regular output file, never a shell glob or host path.
            if (
                target.startswith(("/", "~"))
                or any(part in {"", ".", ".."} for part in target.split("/"))
                or any(char in target for char in "\\:*?[]")
                or any(ord(char) < 32 or ord(char) == 127 for char in target)
            ):
                raise ConfigError("Artifact path must be a task-root relative regular file path")


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
            model_limit = (
                location
                in {f"config.models.{role}.limits" for role in ("user", "harness", "demand")}
                and key
                in {
                    "context_window_tokens",
                    "max_context_tokens",
                    "reserved_output_tokens",
                    "input_headroom_tokens",
                }
                and type(value) is int
            )
            if _SECRET_KEY_RE.search(key) and not key.endswith("_env") and not model_limit:
                raise ConfigError(f"Plaintext credential field forbidden: {location}.{key}")
            _reject_plaintext_credentials(node=value, location=f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_plaintext_credentials(node=value, location=f"{location}[{index}]")
    elif isinstance(node, str) and _looks_like_secret(text=node):
        raise ConfigError(f"Possible plaintext credential at {location}")


# Spec-0072/T1: reuse defaults when reading old frozen v2 without modifying its identity.
def runtime_policies(config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "synthesizer_grouping": False,
        "timing": {"latency_isolated": False, "wall_guard_seconds": 0},
        "delivery": {
            "timeout_seconds": 86400,
            "poll_seconds": 15,
            "coordination": "soft",
            "permission_mode": "bypassPermissions",
            "idle_timeout_seconds": 300,
        },
        "alarms": {"proposal_depth": 20, "ready_depth": 20},
    }
    supplied = config.get("policies", {})
    defaults["synthesizer_grouping"] = supplied.get("synthesizer_grouping", False)
    for section in ("timing", "delivery", "alarms"):
        defaults[section].update(supplied.get(section, {}))
    return defaults


def delivery_auth_type(model: dict[str, Any]) -> str:
    """Explicit protocol is independent of credential name; retain old v2 defaults."""
    value = model.get("auth_type")
    if value is None:
        value = {
            "ANTHROPIC_API_KEY": "api-key",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
        }.get(model["api_key_env"], "bearer")
    if value not in {"api-key", "bearer", "oauth"}:
        raise ConfigError("Unsupported delivery auth_type")
    return value


def local_ci_enabled(config: dict[str, Any]) -> bool:
    """Spec-0077/T1: read the optional flag without mutating frozen configurations."""
    runtime = config.get("runtime", {})
    value = runtime.get("local", {}).get("ci_enabled", False)
    if type(value) is not bool:
        raise ConfigError("runtime.local.ci_enabled must be a boolean")
    if value and (
        runtime["backend"] != "local" or runtime.get("gitea", {}).get("provider") != "localhost"
    ):
        raise ConfigError("Local CI requires local backend and localhost Gitea")
    return value


def _validate_ci_image_reference(image: str) -> None:
    """Require an explicit Docker tag or SHA-256 digest, safe for Compose inputs."""
    repository, separator, digest = image.partition("@")
    final = repository.rsplit("/", 1)[-1]
    name, tagged, tag = final.partition(":")
    image_name = repository[: -(len(tag) + 1)] if tagged else repository
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*", image_name)
        or "//" in repository
        or not name
        or (
            tagged
            and (
                not re.fullmatch(r"[\w][\w.-]{0,127}", tag, re.ASCII)
                or (tag == "latest" and not separator)
            )
        )
        or (separator and not re.fullmatch(r"sha256:[a-f0-9]{64}", digest))
        or (not separator and not tagged)
    ):
        raise ConfigError("CI image references must use an explicit version or SHA-256 digest")


def delivery_required(config: dict[str, Any]) -> bool:
    """Spec-0079/T4: parent feedback requires delivery even for one new user round."""
    return config["rounds"]["count"] > 1 or "continuation" in config
