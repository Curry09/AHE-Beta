"""Minimal provider contract used by the orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    image_digest: str
    cpu: int
    memory_mb: int
    storage_mb: int
    ttl_minutes: int
    network_policy: str = "benchmark_minimum"
    env_slots: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxHandle:
    id: str
    provider: str


@dataclass(frozen=True)
class CommandHandle:
    sandbox_id: str
    session_id: str
    command_id: str


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(Protocol):
    name: str

    def create(self, spec: SandboxSpec, *, env: Mapping[str, str]) -> SandboxHandle: ...

    def upload(self, handle: SandboxHandle, local: Path, remote: str) -> None: ...

    def exec_async(
        self, handle: SandboxHandle, command: str, *, timeout_seconds: int
    ) -> CommandHandle: ...

    def poll(self, command: CommandHandle) -> CommandResult | None: ...

    def download(self, handle: SandboxHandle, remote: str, local: Path) -> None: ...

    def inspect(self, handle: SandboxHandle) -> Mapping[str, object]: ...

    def delete(self, handle: SandboxHandle) -> None: ...
