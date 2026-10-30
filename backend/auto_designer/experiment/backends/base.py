"""Spec-0069/T2: provider resources are mutable facts, never frozen config fields."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from auto_designer.experiment.config import ConfigError


class BackendError(ConfigError):
    """A provider operation could not establish the requested resource fact."""


def require_execution_reader(capabilities: dict) -> None:
    """New evolution dispatches require the paired reader, even without markers."""
    contract = capabilities.get("execution_evidence", {})
    if (
        1 not in contract.get("schema_versions", [])
        or contract.get("required_dispatch") is not True
        or contract.get("context_projection") != "all-delivery-roles-v1"
    ):
        raise BackendError(
            "OpenAgents reader lacks execution-evidence v1 / required dispatch / role projection; "
            "prepare with the paired execution-contract reader revision"
        )


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

    # Spec-0084/T5: fixed management operations; no grader commands/credentials.
    def assessment_exchange(self, action: str, payload: dict) -> dict: ...

    def assessment_download(self, request_digest: str) -> bytes: ...

    def destroy(self) -> dict[str, Any]: ...
