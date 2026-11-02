"""The existing host persona drives native CC and Meta sessions on E2B.

CC resumes its native session with --continue. Meta retains the same Chat and
tmux session. Neither implementation receives scores or hidden verifier input.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import litellm
from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import BaseInstalledAgent
from harbor.models.trajectories import Step

from evaluation.harbor.agents import ClaudeCodeAgent

from .meta_agent import MetaHarnessAgent
from .meta_artifact.agent import AgentHarness

PACKAGE = Path(__file__).parent


class InteractiveClaude(ClaudeCodeAgent):
    """Native CLI, preserving conversation and owned processes across replies."""

    async def exec_as_agent(self, environment, command, env=None, cwd=None, timeout_sec=None):
        env = dict(
            env or {},
            API_TIMEOUT_MS=str(int(self.provider_timeout * 1000)),
            CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(getattr(self, "output_tokens", 65536)),
        )
        if self._process_owner is None:
            return await BaseInstalledAgent.exec_as_agent(
                self, environment, command, env, cwd, timeout_sec
            )
        wrapped, pid_file, cancel_file = self._process_owner.command(command)
        self.owned_commands.append((pid_file, cancel_file))
        try:
            result = await BaseInstalledAgent.exec_as_agent(
                self, environment, wrapped, env, cwd, timeout_sec
            )
        except BaseException:
            await self._process_owner.cancel_shielded(environment, pid_file, cancel_file)
            raise
        if "--output-format=stream-json" in command:
            self.last_reply = ""
            for line in (result.stdout or "").splitlines():
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if event.get("type") == "result" and not event.get("is_error"):
                    self.last_reply = event.get("result") or ""
            with (self.logs_dir / "native-cc-turns.jsonl").open("a") as log:
                log.write(json.dumps({"continue": self._resume, "reply": self.last_reply}) + "\n")
        return result

    async def freeze(self, environment):
        for pid_file, cancel_file in self.owned_commands:
            await self._process_owner.cancel_shielded(environment, pid_file, cancel_file)


class InteractiveMeta(MetaHarnessAgent):
    async def run(self, instruction, environment, context):
        # The pinned adapter's run() freezes tmux after one direct answer.
        # Defer that same cleanup until the multi-turn user session finishes.
        await AgentHarness.run(self, instruction, environment, context)

    async def resume(self, instruction, environment, context):
        self._pending_completion = False
        self._context = context
        self._trajectory_steps.append(
            Step(
                step_id=len(self._trajectory_steps) + 1,
                timestamp=datetime.now(UTC).isoformat(),
                source="user",
                message=instruction,
            )
        )
        try:
            await self._run_agent_loop(
                initial_prompt=instruction,
                chat=self._chat,
                original_instruction=self._original_instruction,
            )
        finally:
            context.n_input_tokens = (
                self._chat.total_input_tokens + self._subagent_metrics.total_prompt_tokens
            )
            context.n_output_tokens = (
                self._chat.total_output_tokens + self._subagent_metrics.total_completion_tokens
            )
            context.n_cache_tokens = (
                self._chat.total_cache_tokens + self._subagent_metrics.total_cached_tokens
            )
            context.rollout_details = self._chat.rollout_details + self._subagent_rollout_details
            self._dump_trajectory()

    async def freeze(self, environment):
        if self._owner_files:
            await self._owner.cancel_shielded(environment, *self._owner_files)


class SimulatedUserNativeAgent(BaseAgent):
    capabilities = AgentCapabilities(mcp_servers=True, skills=True)

    @staticmethod
    def name():
        return "native-harness-with-simulated-user"

    def version(self):
        return self.native_version

    def __init__(
        self,
        *args,
        native_kind,
        native_version,
        native_kwargs,
        process_runtime,
        interaction,
        request_timeout_sec,
        llm_options=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        assert native_kind in {"claude-code", "meta-harness"}
        self.llm_options = dict(llm_options or {})
        self.native_kind, self.native_version = native_kind, native_version
        self.interaction, self.request_timeout_sec = interaction, request_timeout_sec
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        shared = dict(
            logs_dir=self.logs_dir,
            model_name=self.model_name,
            logger=self.logger,
            mcp_servers=self.mcp_servers,
            skills_dir=self.skills_dir,
            environment_logs_dir=self.environment_logs_dir,
            extra_env=self.extra_env,
            process_runtime=process_runtime,
            version=native_version,
            **native_kwargs,
        )
        if native_kind == "claude-code":
            shared["model_name"] = self.model_name.removeprefix("openai/")
            self.inner = InteractiveClaude(**shared)
            self.inner.provider_timeout = request_timeout_sec
            self.inner.output_tokens = self.llm_options.get("max_output_tokens", 65536)
            self.inner.owned_commands, self.inner.last_reply = [], ""
        else:
            self.inner = InteractiveMeta(**shared)
        self.workdir = None
        self.worker = None
        self.frozen = False
        self._original_acompletion = None

    async def setup(self, environment):
        await self.inner.setup(environment)
        result = await environment.exec("pwd", timeout_sec=15)
        if result.return_code:
            raise RuntimeError("Cannot discover native task working directory")
        self.workdir = result.stdout.strip()

    def configure_meta_provider(self):
        if self.native_kind != "meta-harness" or self._original_acompletion is not None:
            return
        self._original_acompletion = litellm.acompletion

        async def configured_completion(*args, **kwargs):
            # This worker owns exactly one native actor; the persona is isolated
            # in a child process. Preserve upstream model/tool-loop behavior.
            kwargs.update(
                timeout=self.request_timeout_sec,
                max_tokens=self.llm_options.get("max_output_tokens", 65536),
                reasoning_effort=self.llm_options.get("reasoning_effort", "max"),
            )
            if self.llm_options.get("stream", "native") != "native":
                kwargs["stream"] = self.llm_options["stream"]
            if self.llm_options.get("thinking", True):
                kwargs["extra_body"] = {
                    **kwargs.get("extra_body", {}),
                    "thinking": {"type": "enabled"},
                }
            began = time.monotonic()
            response = await self._original_acompletion(*args, **kwargs)
            usage = response.usage.model_dump() if response.usage else {}
            with (self.logs_dir / "native-meta-api-usage.jsonl").open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "elapsed_seconds": time.monotonic() - began,
                            "reasoning_effort": kwargs["reasoning_effort"],
                            "max_tokens": kwargs["max_tokens"],
                            "timeout_seconds": self.request_timeout_sec,
                            "usage": usage,
                        }
                    )
                    + "\n"
                )
            return response

        litellm.acompletion = configured_completion

    async def native_request(self, text, environment, context, request_number):
        if self.frozen:
            raise RuntimeError("No actor calls are allowed after freezing")
        from . import fulltrace

        if self.native_kind == "meta-harness":
            fulltrace.install("actor", self.logs_dir / "full-call-traces/actor")
        self.configure_meta_provider()
        if request_number == 0:
            await self.inner.run(text, environment, context)
        else:
            await self.inner.resume(text, environment, context)
        if self.native_kind == "claude-code":
            reply = self.inner.last_reply
        else:
            if not self.inner._pending_completion:
                raise RuntimeError("Meta-Harness stopped without native completion")
            reply = next(
                (
                    s.message
                    for s in reversed(self.inner._trajectory_steps)
                    if s.source == "agent" and s.message
                ),
                "Task completion confirmed by Meta-Harness.",
            )
        if not reply:
            raise RuntimeError("Native actor returned no final reply")
        (self.logs_dir / "harness-reply.txt").write_text(reply)
        return reply

    async def freeze(self, environment):
        if self.frozen:
            return
        await self.inner.freeze(environment)
        self.frozen = True
        with (self.logs_dir / "harness-command-cleanup.jsonl").open("a") as log:
            log.write(json.dumps({"owner_exited": True, "native_actor_frozen": True}) + "\n")

    async def run(self, instruction, environment, context):
        began = time.monotonic()
        deadline = began + self.request_timeout_sec
        (self.logs_dir / "public-instruction.md").write_text(instruction)
        env = {
            k: os.environ[k]
            for k in (
                "PATH",
                "HOME",
                "LANG",
                "SSL_CERT_FILE",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            )
            if k in os.environ
        }
        env.update(
            USER_LLM_API_KEY=os.environ["USER_LLM_API_KEY"],
            USER_LLM_BASE_URL=os.environ["USER_LLM_BASE_URL"],
            USER_LLM_MODEL=self.interaction["user_model"].removeprefix("openai/"),
            USER_LLM_READ_TIMEOUT_SEC=str(self.request_timeout_sec),
            USER_LLM_REASONING_EFFORT=os.environ.get("USER_LLM_REASONING_EFFORT", "max"),
            USER_LLM_MAX_OUTPUT_TOKENS=os.environ.get("USER_LLM_MAX_OUTPUT_TOKENS", "65536"),
            FULL_TRACE_DIR=str(self.logs_dir / "full-call-traces/simulated-user"),
            PYTHONUNBUFFERED="1",
            AHE_BETA_USAGE_PATH=str(self.logs_dir / "user-llm-usage.jsonl"),
        )
        latest, final, requests, reason = None, None, 0, None
        errors = (self.logs_dir / "user-worker-stderr.log").open("wb")

        async def exchange(value):
            self.worker.stdin.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
            await self.worker.stdin.drain()

        async def session():
            nonlocal latest, final, requests
            self.worker = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                str(PACKAGE / "sim_worker.py"),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=errors,
                limit=16 * 1024 * 1024,
            )
            await exchange(
                {"task": instruction, "remaining_seconds": max(0.01, deadline - time.monotonic())}
            )
            with (self.logs_dir / "user-events.jsonl").open("w") as events:
                while line := await self.worker.stdout.readline():
                    event = json.loads(line)
                    events.write(json.dumps(event, ensure_ascii=False) + "\n")
                    events.flush()
                    if event["type"] == "request":
                        reply = await self.native_request(
                            event["text"], environment, context, requests
                        )
                        requests += 1
                        diff = await environment.exec(
                            "git -C "
                            + shlex.quote(self.workdir)
                            + ' diff --no-ext-diff HEAD -- . ":(exclude)bug_patch.diff"',
                            timeout_sec=15,
                        )
                        reply += (
                            "\n\n[Public workspace inspection: current git diff; truncated at 24000 characters]\n"
                            + (diff.stdout or "")[:24000]
                        )
                        await exchange({"text": reply})
                    elif event["type"] == "progress":
                        latest = event["result"]
                        (self.logs_dir / "user-session-progress.json").write_text(
                            json.dumps(latest, ensure_ascii=False, indent=2)
                        )
                    elif event["type"] == "freeze":
                        await self.freeze(environment)
                        await exchange({"frozen": True})
                    elif event["type"] == "result":
                        final = event["result"]
            code = await self.worker.wait()
            if code or final is None:
                raise RuntimeError("User simulator exited without a complete result")

        try:
            await asyncio.wait_for(session(), max(0.01, deadline - time.monotonic()))
        except TimeoutError:
            reason = "official_deadline"
        except asyncio.CancelledError:
            reason = "controller_cancelled"
            raise
        except Exception as error:
            reason = "simulator_invalid:" + type(error).__name__
            raise
        finally:
            if self.worker is not None and self.worker.returncode is None:
                self.worker.terminate()
                try:
                    await asyncio.wait_for(self.worker.wait(), 5)
                except TimeoutError:
                    self.worker.kill()
                    await self.worker.wait()
            errors.close()
            try:
                await self.freeze(environment)
            finally:
                if self._original_acompletion is not None:
                    litellm.acompletion = self._original_acompletion
                outcome = final or {
                    "evaluation_status": "invalid",
                    "end_reason": reason or "simulator_invalid",
                    "last_progress": latest,
                    "evaluation_error": {"kind": reason or "simulator_invalid"},
                }
                record = {
                    "interaction": self.interaction,
                    "elapsed_seconds": time.monotonic() - began,
                    "harness_requests": requests,
                    "result": outcome,
                    "workspace_frozen": self.frozen,
                    "deadline_seconds": self.request_timeout_sec,
                    "stop_reason": reason,
                    "first_message_policy": "exact_official_instruction",
                    "observation_policy": "public_task_completed_replies_readonly_git_diff",
                }
                (self.logs_dir / "user-session-result.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2)
                )
                (self.logs_dir / "harness-driver-result.json").write_text(
                    json.dumps(
                        {
                            "normal_reply": final is not None and reason is None,
                            "termination_reason": "TimeoutError"
                            if reason == "official_deadline"
                            else reason,
                            "workspace_frozen": self.frozen,
                            "elapsed_seconds": time.monotonic() - began,
                            "native_kind": self.native_kind,
                            "native_version": self.native_version,
                            "harness_requests": requests,
                        },
                        indent=2,
                    )
                )

    def populate_context_post_run(self, context):
        method = getattr(self.inner, "populate_context_post_run", None)
        if method is not None:
            method(context)


class DirectNativeAgent(SimulatedUserNativeAgent):
    async def run(self, instruction, environment, context):
        import time

        began = time.monotonic()
        (self.logs_dir / "public-instruction.md").write_text(instruction)
        reason = None
        try:
            await asyncio.wait_for(
                self.native_request(instruction, environment, context, 0), self.request_timeout_sec
            )
        except TimeoutError:
            reason = "TimeoutError"
        finally:
            await self.freeze(environment)
            if self._original_acompletion is not None:
                litellm.acompletion = self._original_acompletion
            (self.logs_dir / "harness-driver-result.json").write_text(
                json.dumps(
                    {
                        "elapsed_seconds": time.monotonic() - began,
                        "workspace_frozen": self.frozen,
                        "termination_reason": reason,
                        "normal_reply": (self.logs_dir / "harness-reply.txt").exists(),
                    }
                )
            )
