"""Spec-0081/T1: container task declarations independent of execution providers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}$")
_PROTECTED = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/run",
    "/opt/auto-designer",
    "/opt/evolution-run",
)


class EnvironmentContractError(ValueError):
    """An environment declaration cannot establish a valid execution boundary."""


def is_container_task(package: dict) -> bool:
    return package.get("schema_version") == 3 and type(package.get("schema_version")) is int


def _fields(*, value: object, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise EnvironmentContractError(f"{label} must contain only declared fields")
    return value


def _name(*, value: object, label: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise EnvironmentContractError(f"{label} must be a safe identifier")
    return value


def _absolute_path(*, value: object, label: str, allow_root: bool) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or value != PurePosixPath(value).as_posix()
        or ".." in PurePosixPath(value).parts
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in value for char in "\\*?[]")
        or (value == "/" and not allow_root)
    ):
        raise EnvironmentContractError(f"{label} must be a canonical absolute container path")
    return value


def _sequence(*, value: object, label: str) -> list:
    if not isinstance(value, list):
        raise EnvironmentContractError(f"{label} must be a list")
    return value


def _positive(*, value: object, label: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise EnvironmentContractError(f"{label} must be a positive finite number")


def _argv(*, value: object, label: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(arg, str) or "\0" in arg for arg in value)
        or not value[0]
    ):
        raise EnvironmentContractError(f"{label} must be a nonempty argv list")


def _command(*, value: object, label: str) -> None:
    command = _fields(value=value, allowed={"argv", "cwd", "timeout_seconds"}, label=label)
    _argv(value=command.get("argv"), label=label + ".argv")
    _positive(value=command.get("timeout_seconds"), label=label + ".timeout_seconds")
    if "cwd" in command:
        _absolute_path(value=command["cwd"], label=label + ".cwd", allow_root=True)


def _resources(*, value: object, label: str) -> None:
    resources = _fields(value=value, allowed={"cpus", "memory_mb"}, label=label)
    for key, scalar in resources.items():
        _positive(value=scalar, label=label + "." + key)
        if key == "memory_mb" and type(scalar) is not int:
            raise EnvironmentContractError(f"{label}.memory_mb must be an integer")


def _variables(*, value: object, label: str) -> None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        or not isinstance(scalar, str)
        or "\0" in scalar
        for key, scalar in value.items()
    ):
        raise EnvironmentContractError(f"{label} must contain string environment variables")


def _image(*, value: object, label: str) -> None:
    if not isinstance(value, str) or not _IMAGE.fullmatch(value):
        raise EnvironmentContractError(f"{label} must be an immutable image@sha256 digest")


def _material(*, value: object, label: str) -> None:
    material = _fields(
        value=value, allowed={"path", "url", "sha256", "format", "files"}, label=label
    )
    if ("path" in material) == ("url" in material):
        raise EnvironmentContractError(f"{label} requires exactly one of path and url")
    if not isinstance(material.get("sha256"), str) or not _SHA.fullmatch(material["sha256"]):
        raise EnvironmentContractError(f"{label}.sha256 must be a full SHA-256")
    if material.get("format") not in {"tar", "tar.gz", "file"}:
        raise EnvironmentContractError(f"{label}.format must be tar, tar.gz or file")
    if "path" in material and (
        not isinstance(material["path"], str) or not material["path"] or "\0" in material["path"]
    ):
        raise EnvironmentContractError(f"{label}.path must be a file path")
    if "url" in material:
        url = urlsplit(material["url"]) if isinstance(material["url"], str) else None
        if (
            not url
            or url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or any(char.isspace() for char in material["url"])
        ):
            raise EnvironmentContractError(f"{label}.url must be credential-free HTTP(S)")
    inventory = material.get("files", {})
    if not isinstance(inventory, dict):
        raise EnvironmentContractError(f"{label}.files must be a file/hash inventory")
    for name, digest in inventory.items():
        if (
            not isinstance(name, str)
            or not name
            or PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or name != PurePosixPath(name).as_posix()
            or name == "."
            or "\\" in name
            or any(ord(char) < 32 for char in name)
            or not isinstance(digest, str)
            or not _SHA.fullmatch(digest)
        ):
            raise EnvironmentContractError(f"{label}.files contains an unsafe path or hash")


def _user(*, value: object, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?", value
    ):
        raise EnvironmentContractError(f"{label} must be a Docker user or uid[:gid]")


def validate_container_environment(package: dict) -> None:
    """Check executable semantics without filesystem, provider or model operations."""
    if not is_container_task(package):
        raise EnvironmentContractError("Expected container task schema_version=3")
    env = _fields(
        value=package.get("environment"),
        allowed={
            "kind",
            "image",
            "workdir",
            "user",
            "patch",
            "resources",
            "capabilities",
            "inputs",
            "initialize",
            "readiness",
            "finalize",
            "services",
            "variables",
        },
        label="environment",
    )
    if env.get("kind") != "container":
        raise EnvironmentContractError("environment.kind must be container")
    _image(value=env.get("image"), label="environment.image")
    _absolute_path(value=env.get("workdir"), label="environment.workdir", allow_root=False)
    if "user" in env:
        _user(value=env["user"], label="environment.user")
    if env.get("patch", "not_applicable") not in {"git", "not_applicable"}:
        raise EnvironmentContractError("environment.patch must be git or not_applicable")
    _resources(value=env.get("resources", {}), label="environment.resources")
    _variables(value=env.get("variables", {}), label="environment.variables")
    capabilities = _sequence(value=env.get("capabilities", []), label="environment.capabilities")
    if any(capability != "ptrace" for capability in capabilities) or len(set(capabilities)) != len(
        capabilities
    ):
        raise EnvironmentContractError(
            "environment.capabilities contains unknown or duplicate capabilities"
        )
    _command(value=env.get("readiness"), label="environment.readiness")
    for stage in ("initialize", "finalize"):
        if stage in env:
            _command(value=env[stage], label="environment." + stage)
    services = _sequence(value=env.get("services", []), label="environment.services")
    by_id = {}
    handles = {}
    for service in services:
        row = _fields(
            value=service,
            allowed={
                "id",
                "placement",
                "image",
                "argv",
                "cwd",
                "user",
                "environment",
                "depends_on",
                "readiness",
                "finalize",
                "resources",
                "exports",
                "mode",
                "timeout_seconds",
                "handoff_ports",
            },
            label="service",
        )
        identifier = _name(value=row.get("id"), label="service.id")
        if identifier == "task" or identifier in by_id:
            raise EnvironmentContractError("Service IDs must be unique and cannot be task")
        by_id[identifier] = row
        if row.get("placement") not in {"task", "companion"}:
            raise EnvironmentContractError("service.placement must be task or companion")
        if row["placement"] == "companion" or "image" in row:
            _image(value=row.get("image"), label="service.image")
        if row["placement"] == "task" and "image" in row:
            raise EnvironmentContractError("An in-task service uses its task image")
        _argv(value=row.get("argv"), label="service.argv")
        if "cwd" in row:
            _absolute_path(value=row["cwd"], label="service.cwd", allow_root=True)
        if "user" in row:
            _user(value=row["user"], label="service.user")
        _variables(value=row.get("environment", {}), label="service.environment")
        _resources(value=row.get("resources", {}), label="service.resources")
        mode = row.get("mode", "daemon")
        if mode == "oneshot":
            _positive(value=row.get("timeout_seconds"), label="service.timeout_seconds")
            if "readiness" in row or "finalize" in row:
                raise EnvironmentContractError(
                    "A oneshot service uses bounded successful completion as readiness"
                )
        elif mode == "daemon":
            if "timeout_seconds" in row:
                raise EnvironmentContractError("Daemon startup timeout belongs in readiness")
            _command(value=row.get("readiness"), label="service.readiness")
            if "finalize" in row:
                _command(value=row["finalize"], label="service.finalize")
        else:
            raise EnvironmentContractError("service.mode must be daemon or oneshot")
        if "handoff_ports" in row:
            ports = _sequence(value=row["handoff_ports"], label="service.handoff_ports")
            if (
                row["placement"] != "task"
                or mode != "daemon"
                or any(type(port) is not int or not 1 <= port <= 65535 for port in ports)
                or len(set(ports)) != len(ports)
            ):
                raise EnvironmentContractError(
                    "service.handoff_ports requires unique TCP ports on an in-task daemon"
                )
        dependencies = _sequence(value=row.get("depends_on", []), label="service.depends_on")
        if any(not isinstance(ref, str) for ref in dependencies) or len(set(dependencies)) != len(
            dependencies
        ):
            raise EnvironmentContractError("service.depends_on must contain unique service IDs")
        for output in _sequence(value=row.get("exports", []), label="service.exports"):
            declaration = _fields(
                value=output, allowed={"handle", "path", "visibility"}, label="service export"
            )
            handle = _name(value=declaration.get("handle"), label="service export.handle")
            if handle in handles:
                raise EnvironmentContractError("Service export handles must be globally unique")
            _absolute_path(
                value=declaration.get("path"), label="service export.path", allow_root=False
            )
            if declaration.get("visibility", "management") not in {"task", "management"}:
                raise EnvironmentContractError(
                    "Service export visibility must be task or management"
                )
            handles[handle] = declaration
    remaining = set(by_id)
    completed = set()
    while remaining:
        ready = {key for key in remaining if set(by_id[key].get("depends_on", [])) <= completed}
        if not ready:
            raise EnvironmentContractError(
                "Service dependencies contain a cycle or unknown service"
            )
        completed.update(ready)
        remaining.difference_update(ready)
    seen = set()
    targets = []
    for item in _sequence(value=env.get("inputs", []), label="environment.inputs"):
        row = _fields(value=item, allowed={"id", "material", "target", "placement"}, label="input")
        identifier = _name(value=row.get("id"), label="input.id")
        if identifier in seen:
            raise EnvironmentContractError("Input IDs must be unique")
        seen.add(identifier)
        _material(value=row.get("material"), label="input.material")
        target = _absolute_path(value=row.get("target"), label="input.target", allow_root=False)
        if any(target == base or target.startswith(base + "/") for base in _PROTECTED):
            raise EnvironmentContractError("Input target overlaps management or kernel paths")
        placement = row.get("placement", "task")
        if placement != "task" and (
            placement not in by_id or by_id[placement]["placement"] != "companion"
        ):
            raise EnvironmentContractError(
                "Input placement must identify task or a companion service"
            )
        for previous_placement, previous in targets:
            if placement == previous_placement and (
                target == previous
                or target.startswith(previous + "/")
                or previous.startswith(target + "/")
            ):
                raise EnvironmentContractError("Input targets overlap in the same container")
        targets.append((placement, target))
    for output in package.get("artifacts", {}).get("exports", []):
        if output["source"] == "managed_service":
            declaration = handles.get(output["handle"])
            if not declaration or declaration.get("visibility", "management") != "task":
                raise EnvironmentContractError(
                    "Artifact handle must bind a task-visible service export"
                )


def container_environment(package: dict) -> dict:
    """Return execution defaults without changing the original package identity."""
    validate_container_environment(package)
    env = copy.deepcopy(package["environment"])
    for key, default in (
        ("inputs", []),
        ("services", []),
        ("capabilities", []),
        ("resources", {}),
        ("variables", {}),
    ):
        env.setdefault(key, default)
    env.setdefault("patch", "git" if package.get("source") else "not_applicable")
    for item in env["inputs"]:
        item.setdefault("placement", "task")
    for service in env["services"]:
        service.setdefault("mode", "daemon")
        if service["placement"] == "task" and service["mode"] == "daemon":
            service.setdefault("handoff_ports", [])
        for key, default in (
            ("depends_on", []),
            ("exports", []),
            ("environment", {}),
            ("resources", {}),
        ):
            service.setdefault(key, default)
        for output in service["exports"]:
            output.setdefault("visibility", "management")
    return env


def resolve_container_paths(package: dict, base: Path) -> dict:
    """Resolve operator-side input files; no download or existence claim occurs."""
    result = copy.deepcopy(package)
    instruction = Path(result["instruction_file"]).expanduser()
    result["instruction_file"] = str(
        (instruction if instruction.is_absolute() else base / instruction).resolve()
    )
    for item in result["environment"].get("inputs", []):
        material = item["material"]
        if "path" in material:
            path = Path(material["path"]).expanduser()
            material["path"] = str((path if path.is_absolute() else base / path).resolve())
    return result


def environment_materials(package: dict) -> list[dict]:
    """Enumerate declared input refs while retaining placement and target binding."""
    return container_environment(package)["inputs"]


def environment_identity(package: dict) -> str:
    """Logical recipe identity excludes mutable provider/resource observations."""
    environment = container_environment(package)
    for item in environment["inputs"]:
        # Locations select hash-identified bytes and change when frozen inputs
        # are installed in another provider; they are not recipe semantics.
        item["material"].pop("path", None)
        item["material"].pop("url", None)
    return hashlib.sha256(
        json.dumps(
            environment,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
