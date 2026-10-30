"""Native Harbor agents with provider-specific public MCP transport."""

import asyncio
import json

from harbor.agents.installed.claude_code import ClaudeCode

from .processes import NativeProcessOwner, prepare_process_runtime


class ClaudeCodeAgent(ClaudeCode):
    @classmethod
    def parse_options(cls, kwargs=None, env=None):
        # The integration descriptor is not a Claude CLI option. Keep Harbor's
        # strict validation for every remaining native option.
        options = dict(kwargs or {})
        runtime = options.pop("process_runtime", None)
        if runtime is not None and (
            not isinstance(runtime, dict)
            or set(runtime) != {"python_archive", "python_sha256"}
            or not all(isinstance(value, str) and value for value in runtime.values())
        ):
            raise ValueError("Invalid native process runtime descriptor")
        return super().parse_options(options, env)

    def __init__(self, *args, process_runtime=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._process_runtime = process_runtime
        self._process_owner = None

    async def setup(self, environment):
        await self._prepare_process_owner(environment)
        await super().setup(environment)

    async def _prepare_process_owner(self, environment):
        runtime = self._process_runtime or prepare_process_runtime()
        self._process_owner = NativeProcessOwner(runtime, self.logs_dir)
        await self._process_owner.setup(environment)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "native-process-owner.json").write_text(
            json.dumps(
                {"owner": "linux-child-subreaper", "runtime_sha256": runtime["python_sha256"]}
            )
            + "\n"
        )

    async def exec_as_agent(self, environment, command, env=None, cwd=None, timeout_sec=None):
        if self._process_owner is None:
            return await super().exec_as_agent(environment, command, env, cwd, timeout_sec)
        wrapped, pid_file, cancel_file = self._process_owner.command(command)
        try:
            return await super().exec_as_agent(environment, wrapped, env, cwd, timeout_sec)
        except (asyncio.CancelledError, Exception):
            await self._process_owner.cancel_shielded(environment, pid_file, cancel_file)
            raise

    async def run(self, instruction, environment, context):
        support = getattr(environment, "support", None)
        collect = support is not None and support.mcp_ready
        if collect and self.mcp_servers:
            self.mcp_servers = await support.native_mcp_servers(self.mcp_servers)
        try:
            return await super().run(instruction, environment, context)
        finally:
            if collect:
                await environment.finish_mcp()
