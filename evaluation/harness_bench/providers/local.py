"""Test/development provider using isolated temporary working directories."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from .base import CommandHandle, CommandResult, SandboxHandle, SandboxSpec


class LocalProvider:
    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="hbench-local-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._env: dict[str, dict[str, str]] = {}
        self._processes: dict[str, tuple[str, subprocess.Popen[str], float]] = {}
        self._commands: dict[str, CommandResult] = {}

    def create(self, spec: SandboxSpec, *, env: Mapping[str, str]) -> SandboxHandle:
        sandbox_id = uuid.uuid4().hex
        (self.root / sandbox_id).mkdir()
        self._env[sandbox_id] = {**os.environ, **dict(env)}
        return SandboxHandle(id=sandbox_id, provider=self.name)

    def _path(self, handle: SandboxHandle, remote: str = "") -> Path:
        if handle.provider != self.name:
            raise ValueError("sandbox belongs to another provider")
        relative = remote.lstrip("/")
        target = (self.root / handle.id / relative).resolve()
        base = (self.root / handle.id).resolve()
        if target != base and base not in target.parents:
            raise ValueError("remote path escapes local sandbox")
        return target

    def upload(self, handle: SandboxHandle, local: Path, remote: str) -> None:
        target = self._path(handle, remote)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, target)

    def exec_async(
        self, handle: SandboxHandle, command: str, *, timeout_seconds: int
    ) -> CommandHandle:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        session_id = uuid.uuid4().hex
        process = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            cwd=self._path(handle),
            env=self._env[handle.id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        command_id = uuid.uuid4().hex
        key = f"{session_id}:{command_id}"
        self._processes[key] = (handle.id, process, time.monotonic() + timeout_seconds)
        return CommandHandle(handle.id, session_id, command_id)

    def poll(self, command: CommandHandle) -> CommandResult | None:
        key = f"{command.session_id}:{command.command_id}"
        if key in self._commands:
            return self._commands[key]
        _, process, deadline = self._processes[key]
        if process.poll() is None and time.monotonic() >= deadline:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.poll() is None:
            return None
        stdout, stderr = process.communicate()
        result = CommandResult(int(process.returncode), stdout, stderr)
        self._commands[key] = result
        return result

    def download(self, handle: SandboxHandle, remote: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._path(handle, remote), local)

    def inspect(self, handle: SandboxHandle) -> Mapping[str, object]:
        return {"id": handle.id, "exists": self._path(handle).is_dir(), "provider": self.name}

    def delete(self, handle: SandboxHandle) -> None:
        for key, (sandbox_id, process, _) in list(self._processes.items()):
            if sandbox_id == handle.id:
                if process.poll() is None:
                    process.terminate()
                self._processes.pop(key, None)
        shutil.rmtree(self._path(handle), ignore_errors=True)
        self._env.pop(handle.id, None)
