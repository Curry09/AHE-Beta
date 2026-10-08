"""Read-only requests for independent session grading (Spec-0083/T1)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

MAX_INPUT_BYTES = 256 * 1024 * 1024


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    return value


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class InputValidationError(ValueError):
    """A plan is well formed but cannot satisfy an adapter's evidence contract."""

    def __init__(self, message: str, *, status: str = "ungradable") -> None:
        super().__init__(message)
        if status not in {"unsupported", "missing_artifact", "ungradable"}:
            raise ValueError(f"invalid input failure status: {status}")
        self.status = status


@dataclass(frozen=True)
class MaterialInput:
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class ArtifactInput:
    path: Path
    sha256: str
    bytes: int
    source: str = "workspace"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    payload: bytes | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "metadata", freeze(self.metadata))


@dataclass(frozen=True)
class GradingRequest:
    adapter: str
    contract_version: int
    task_id: str
    task_digest: str
    session_id: str
    source: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Mapping[str, ArtifactInput] = field(default_factory=dict)
    materials: Mapping[str, MaterialInput] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 1800
    plan_digest: str = ""
    instance_id: str = ""
    patch: str = ""
    session: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError("only grading contract version 1 is supported")
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("grading timeout must be positive")
        for name in ("source", "artifacts", "materials", "config", "session"):
            object.__setattr__(self, name, freeze(getattr(self, name)))


class GradingAdapter(Protocol):
    name: str
    contract_version: int

    def validate_inputs(self, request: GradingRequest) -> None: ...

    def evaluate(self, request: GradingRequest, attempt_dir: Path) -> Any: ...
