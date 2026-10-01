"""Spec-0069/T2: provider resources are mutable facts, never frozen config fields."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from auto_designer.experiment.config import ConfigError


class BackendError(ConfigError):
    """A provider operation could not establish the requested resource fact."""


class Backend(Protocol):
    """Every adapter owns resources.json; the public runtime owns runtime.json.

    credentials may be augmented with a generated Gitea token by local provision.
    Provider tokens belong in secrets/provider.env, never resources.json or receipts.
    logs returns a snapshot; the CLI implements following without blocking adapters.
    """

    def __init__(
        self, run_dir: Path, manifest: dict[str, Any], credentials: Mapping[str, str]
    ) -> None: ...

    def provision(self) -> dict[str, Any]: ...

    def preflight(self) -> dict[str, Any]: ...

    def launch(self, *, mode: str = "fresh") -> dict[str, Any]: ...

    def inspect(self) -> dict[str, Any]: ...

    def stop(self, *, grace_seconds: float = 30) -> dict[str, Any]: ...

    def logs(self, *, tail: int = 100, follow: bool = False) -> str: ...

    def collect(self) -> dict[str, Any]: ...

    def destroy(self) -> dict[str, Any]: ...
