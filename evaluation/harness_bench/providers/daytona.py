"""Daytona adapter with reconnectable async command identifiers."""

from __future__ import annotations

import shlex
import uuid
from collections.abc import Mapping
from pathlib import Path

from .base import CommandHandle, CommandResult, SandboxHandle, SandboxSpec


class DaytonaProvider:
    name = "daytona"

    def __init__(self, api_key: str) -> None:
        try:
            from daytona import Daytona, DaytonaConfig
        except ImportError as exc:  # pragma: no cover - optional provider dependency
            raise RuntimeError("Daytona provider requires the daytona package") from exc
        self.client = Daytona(DaytonaConfig(api_key=api_key))
        self._sandboxes: dict[str, object] = {}
        self._commands: dict[tuple[str, str, str], object] = {}

    def create(self, spec: SandboxSpec, *, env: Mapping[str, str]) -> SandboxHandle:
        from daytona import CreateSandboxFromImageParams, Resources

        if not spec.image_digest:
            raise ValueError("Daytona sandbox image must be pinned by digest")
        box = self.client.create(
            CreateSandboxFromImageParams(
                image=spec.image,
                resources=Resources(
                    cpu=spec.cpu,
                    memory=max(1, (spec.memory_mb + 1023) // 1024),
                    disk=max(1, (spec.storage_mb + 1023) // 1024),
                ),
                ephemeral=True,
                ttl_minutes=spec.ttl_minutes,
                labels=dict(spec.labels),
                env_vars=dict(env),
            ),
            timeout=1200,
        )
        self._sandboxes[box.id] = box
        return SandboxHandle(box.id, self.name)

    def _box(self, handle: SandboxHandle):
        try:
            return self._sandboxes[handle.id]
        except KeyError as exc:
            raise KeyError(f"unknown Daytona sandbox: {handle.id}") from exc

    def upload(self, handle: SandboxHandle, local: Path, remote: str) -> None:
        self._box(handle).fs.upload_file(str(local), remote)

    def exec_async(
        self, handle: SandboxHandle, command: str, *, timeout_seconds: int
    ) -> CommandHandle:
        from daytona import SessionExecuteRequest

        box = self._box(handle)
        session_id = f"hbench-{uuid.uuid4().hex}"
        box.process.create_session(session_id)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        guarded_command = (
            f"timeout --signal=TERM --kill-after=30s {timeout_seconds}s "
            f"/bin/bash -lc {shlex.quote(command)}"
        )
        started = box.process.execute_session_command(
            session_id,
            SessionExecuteRequest(command=guarded_command, run_async=True),
            timeout=60,
        )
        result = CommandHandle(handle.id, session_id, started.cmd_id)
        self._commands[(handle.id, session_id, started.cmd_id)] = started
        return result

    def poll(self, command: CommandHandle) -> CommandResult | None:
        box = self._sandboxes[command.sandbox_id]
        current = box.process.get_session_command(command.session_id, command.command_id)
        if current.exit_code is None:
            return None
        logs = box.process.get_session_command_logs(command.session_id, command.command_id)
        return CommandResult(int(current.exit_code), logs.stdout or "", logs.stderr or "")

    def download(self, handle: SandboxHandle, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._box(handle).fs.download_file(remote, str(local))

    def inspect(self, handle: SandboxHandle) -> Mapping[str, object]:
        box = self._box(handle)
        return {"id": box.id, "provider": self.name, "known": True}

    def delete(self, handle: SandboxHandle) -> None:
        box = self._box(handle)
        self.client.delete(box, timeout=180, wait=True)
        self._sandboxes.pop(handle.id, None)
