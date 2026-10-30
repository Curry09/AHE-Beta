"""Task-role auditing and public MCP transport for Harbor environments."""

from __future__ import annotations

import json
import math
from pathlib import Path

from evaluation.benchmarks import get_profile


def container_allocation(probe: str, config) -> dict:
    lines = probe.splitlines()
    if len(lines) != 4:
        raise RuntimeError("Cannot inspect container CPU and memory limits")
    cpu = lines[2].split()
    allocated_cpus = None
    if len(cpu) == 2 and cpu[0] not in {"max", "-1"}:
        allocated_cpus = int(cpu[0]) / int(cpu[1])
    allocated_memory = None
    if lines[3].isdigit() and int(lines[3]) < 2**60:
        allocated_memory = int(lines[3]) / 1024**2
    if config.cpus is not None and (
        allocated_cpus is None or not math.isclose(allocated_cpus, config.cpus)
    ):
        raise RuntimeError("Container CPU limit differs from task declaration")
    if config.memory_mb is not None and allocated_memory != config.memory_mb:
        raise RuntimeError("Container memory limit differs from task declaration")
    return {"allocated_cpus": allocated_cpus, "allocated_memory_mb": allocated_memory}


class TaskEnvironmentMixin:
    """Keep task declarations unchanged and retain startup evidence per role."""

    def __init__(
        self,
        *args,
        task_env_config,
        session_id,
        environment_dir,
        benchmark="Harbor",
        role=None,
        **kwargs,
    ):
        self.role = role
        self.benchmark = benchmark
        profile = get_profile(benchmark)
        self.support = profile.EnvironmentSupport(self) if profile else None
        super().__init__(
            *args,
            task_env_config=task_env_config.model_copy(deep=True),
            session_id=session_id,
            environment_dir=environment_dir,
            **kwargs,
        )
        self._verifier_environment = (
            Path(environment_dir).name == "tests" or "__verifier__" in session_id
        )

    def child_kwargs(self):
        return {}

    async def record_allocation(self, directory):
        result = await self.exec(
            "nproc; head -1 /proc/meminfo; "
            "if test -f /sys/fs/cgroup/cpu.max; then cat /sys/fs/cgroup/cpu.max; "
            "else printf '%s %s\\n' "
            '"$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)" '
            '"$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)"; fi; '
            "if test -f /sys/fs/cgroup/memory.max; then cat /sys/fs/cgroup/memory.max; "
            "else cat /sys/fs/cgroup/memory/memory.limit_in_bytes; fi",
            user="root",
            timeout_sec=30,
        )
        if result.return_code:
            raise RuntimeError("Cannot inspect task environment allocation")
        record = {
            "provider": self.type().value,
            "image": self.task_env_config.docker_image,
            "declared_cpus": self.task_env_config.cpus,
            "declared_memory_mb": self.task_env_config.memory_mb,
            "declared_storage_mb": self.task_env_config.storage_mb,
            "guest_probe": result.stdout,
            **container_allocation(result.stdout or "", self.task_env_config),
            "role": self.role or ("verifier" if self._verifier_environment else "agent"),
        }
        (directory / f"{self.session_id}.json").write_text(json.dumps(record, indent=2) + "\n")

    async def start(self, force_build):
        try:
            await super().start(force_build)
            directory = self.trial_paths.trial_dir / "infrastructure"
            directory.mkdir(exist_ok=True)
            await self.record_allocation(directory)
            if self.support:
                await self.support.start(directory)
        except BaseException:
            await self.stop(True)
            raise

    async def exec(self, command, *args, **kwargs):
        if self.support:
            command = self.support.command(command)
            kwargs["env"] = self.support.command_env(kwargs.get("env"))
        return await super().exec(command, *args, **kwargs)

    async def finish_mcp(self):
        if self.support:
            await self.support.collect()

    async def stop(self, delete):
        try:
            if self.support:
                await self.support.stop()
        finally:
            await super().stop(delete)
