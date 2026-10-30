"""Compatibility adapter for pinned Meta-Harness artifact on Harbor 0.24.

The original prompt, tool schema, model loop, marker polling and completion
policy live in meta_artifact unchanged. This adapter translates framework APIs,
resolves private provider settings and owns the tmux process tree.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import time

from harbor.environments.base import ExecResult

from evaluation.harbor.processes import NativeProcessOwner

from .meta_artifact.agent import AgentHarness

REVISION = "57fefdb2ff84af3fd81b69d67814acbe69bd0743"


class MetaHarnessAgent(AgentHarness):
    @classmethod
    def parse_options(cls, kwargs=None, env=None):
        options = dict(kwargs or {})
        options.pop("process_runtime", None)
        options.pop("version", None)
        return super().parse_options(options, env)

    def __init__(self, *args, version=REVISION, process_runtime=None, **kwargs):
        if version != REVISION:
            raise ValueError("Meta-Harness source revision must match the vendored artifact")
        self._process_runtime = process_runtime
        self._owner = None
        self._owner_files = None
        self._handle = None
        env = kwargs.get("extra_env") or {}
        key = env.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        base = env.get("OPENAI_API_BASE") or os.environ.get("LLM_BASE_URL")
        if key:
            # Each Harbor worker hosts exactly one trial. The upstream native
            # tool path reads LiteLLM's standard provider variables directly.
            os.environ["OPENAI_API_KEY"] = key
        if base:
            kwargs.setdefault("api_base", base)
        # Preserve the minimum supported upstream Harbor version's default.
        kwargs.setdefault("temperature", 0.7)
        super().__init__(*args, **kwargs)
        self._temperature = self.options.temperature
        self._reasoning_effort = self.options.reasoning_effort
        self._enable_summarize = self.options.enable_summarize
        config = self.options.trajectory_config
        self._linear_history = config.linear_history if config else False
        self._save_raw_content_in_trajectory = config.raw_content if config else False

    def _setup_episode_logging(self, logging_dir, episode):
        # Exact behavior of Harbor 0.1.44's removed helper.
        if logging_dir is None:
            return None, None, None
        folder = logging_dir / f"episode-{episode}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "debug.json", folder / "prompt.txt", folder / "response.txt"

    def _record_asciinema_marker(self, marker_text):
        # This compatibility hook was already a no-op in Harbor 0.1.44.
        return None

    async def setup(self, environment):
        if self._process_runtime is None:
            raise ValueError("Pinned process ownership runtime is required")
        self._owner = NativeProcessOwner(self._process_runtime, self.logs_dir)
        self._owner.preserve_children_on_success = False
        await self._owner.setup(environment)
        original_exec = environment.exec
        ready = self._owner.root + "/meta-tmux-ready"

        async def owned_start(command, *args, **kwargs):
            if self._session is None or command != self._session._tmux_start_session:
                return await original_exec(command, *args, **kwargs)
            keep_alive = (
                command
                + " && touch "
                + shlex.quote(ready)
                + " && exec "
                + self._owner.python
                + " -E -s -c "
                + shlex.quote("import time\nwhile True: time.sleep(30)")
            )
            wrapped, pid_file, cancel_file = self._owner.command(keep_alive)
            self._owner_files = pid_file, cancel_file
            user = environment._resolve_user(kwargs.get("user"))
            env = environment._merge_env(kwargs.get("env"))
            self._handle = await environment._dispatch_command(
                wrapped,
                cwd=None,
                env=env,
                timeout_sec=7200,
                user=str(user) if user is not None else "root",
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                check = await original_exec(
                    "test -f " + shlex.quote(ready), timeout_sec=10, user="root"
                )
                if check.return_code == 0:
                    return ExecResult(return_code=0, stdout="", stderr="")
                await asyncio.sleep(0.2)
            raise RuntimeError("Owned Meta-Harness tmux session did not become ready")

        environment.exec = owned_start
        try:
            await super().setup(environment)
        except BaseException:
            if self._owner_files:
                await self._owner.cancel_shielded(environment, *self._owner_files)
            raise
        finally:
            environment.exec = original_exec

    async def run(self, instruction, environment, context):
        started = time.monotonic()
        completed = False
        try:
            await super().run(instruction, environment, context)
            completed = self._pending_completion
        finally:
            # Freeze actor commands before Harbor collects the candidate patch,
            # including on deadline, cancellation and detached shell children.
            if self._owner_files:
                await self._owner.cancel_shielded(environment, *self._owner_files)
            record = {
                "normal_reply": completed,
                "elapsed_seconds": time.monotonic() - started,
                "termination_reason": None if completed else "IncompleteExecution",
                "artifact_revision": REVISION,
                "upstream_name": self.name(),
                "upstream_version": self.version(),
                "compatibility_runtime": "Harbor 0.24.0 / LiteLLM 1.104.2",
                "workspace_frozen": True,
            }
            (self.logs_dir / "harness-driver-result.json").write_text(json.dumps(record, indent=2))
            if completed:
                text = next(
                    (s.message for s in reversed(self._trajectory_steps) if s.message),
                    "Task completion confirmed twice by upstream Meta-Harness.",
                )
                (self.logs_dir / "harness-reply.txt").write_text(text)
