"""Run an operator-pinned stdio Harness in a Harbor task environment.

The task instruction and verifier remain Harbor-owned. Provider credentials
are read at runtime, never passed as agent kwargs or written into job config.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.models.agent.context import AgentContext

from evaluation.harbor.processes import CommandProcessOwner

from .budget_protocol import TaskBudget

PACKAGE = Path(__file__).resolve().parent


class FrozenHarnessAgent(BaseAgent):
    capabilities = AgentCapabilities(mcp_servers=True, skills=True)

    @staticmethod
    def name() -> str:
        return "frozen-harness"

    def __init__(
        self,
        *args,
        archive: str,
        archive_sha256: str,
        revision: str,
        runtime_wheel: str,
        runtime_sha256: str,
        runtime_lock: str,
        runtime_lock_sha256: str,
        python_archive: str,
        python_sha256: str,
        workdir: str,
        request_timeout_sec: int,
        call_timeout_sec: int | None = None,
        reasoning_effort: str | None = None,
        llm_options: dict | None = None,
        time_adaptation: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if reasoning_effort is not None:
            raise ValueError(
                "The frozen Harness does not consume Harbor's reasoning_effort kwarg; "
                "it keeps its archived agent.yaml model configuration."
            )
        self.llm_options = dict(llm_options or {})
        self.time_adaptation = time_adaptation
        self.archive = Path(archive).resolve()
        self.wheel = Path(runtime_wheel).resolve()
        self.lock = Path(runtime_lock).resolve()
        self.python_archive = Path(python_archive).resolve()
        self.revision = revision
        self.workdir = workdir
        self.request_timeout_sec = request_timeout_sec
        if call_timeout_sec is not None and call_timeout_sec <= 0:
            raise ValueError("Harness call timeout must be positive")
        self.call_timeout_sec = call_timeout_sec
        for path, expected in (
            (self.archive, archive_sha256),
            (self.wheel, runtime_sha256),
            (self.python_archive, python_sha256),
            (self.lock, runtime_lock_sha256),
        ):
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Material digest mismatch: {path.name}")
        if (workdir != "auto" and not Path(workdir).is_absolute()) or request_timeout_sec <= 0:
            raise ValueError("An absolute task workdir and positive timeout are required")
        self.materials = {
            "archive_sha256": archive_sha256,
            "runtime_sha256": runtime_sha256,
            "python_sha256": python_sha256,
            "runtime_lock_sha256": runtime_lock_sha256,
        }
        self._process_owner = CommandProcessOwner(
            "/opt/frozen-harness", "/opt/frozen-harness/runtime/bin/python", self.logs_dir
        )

    def version(self) -> str:
        return self.revision

    def _env_value(self, *names: str) -> str | None:
        for source in (self.extra_env, os.environ):
            for name in names:
                if source.get(name):
                    return source[name]
        return None

    def _save_driver_output(self, result: ExecResult, api_key: str) -> dict:
        """Keep returned command output on the host, before remote collection.

        A full task filesystem can prevent the driver from saving its own
        traceback. Retain the SDK's returned streams independently, redacting
        known credentials. Diagnostic write errors do not replace execution.
        """
        secrets = {api_key}
        for source in (self.extra_env, os.environ):
            secrets.update(
                value
                for name, value in source.items()
                if isinstance(value, str)
                and len(value) > 4
                and any(word in name.upper() for word in ("KEY", "TOKEN", "PASSWORD"))
            )
        files = {}
        errors = {}
        for stream in ("stdout", "stderr"):
            text = getattr(result, stream, None) or ""
            for secret in sorted(secrets, key=len, reverse=True):
                text = text.replace(secret, "[redacted]")
            name = f"harness-driver-{stream}.log"
            try:
                (self.logs_dir / name).write_text(text, encoding="utf-8")
                files[stream] = name
            except OSError as error:
                errors[stream] = type(error).__name__
                self.logger.warning(
                    "Driver %s diagnostic write failed: %s", stream, type(error).__name__
                )
        return {"files": files, "errors": errors}

    async def setup(self, environment: BaseEnvironment) -> None:
        async def checked(command: str, command_timeout_sec: int):
            result = await environment.exec(command, timeout_sec=command_timeout_sec, user="root")
            if result.return_code != 0:
                raise RuntimeError(result.stderr or result.stdout or "Harness setup failed")

        await checked(
            "mkdir -p /opt/frozen-harness/source /opt/frozen-harness/materials /logs/agent",
            command_timeout_sec=60,
        )
        files = [
            (self.archive, "/opt/frozen-harness/materials/harness.tar.gz"),
            (self.wheel, "/opt/frozen-harness/materials/nexau-0.4.1-py3-none-any.whl"),
            (self.lock, "/opt/frozen-harness/materials/runtime.lock"),
            (self.python_archive, "/opt/frozen-harness/materials/python.tar.gz"),
            (
                PACKAGE / "stdio.py",
                "/opt/frozen-harness/stdio.py",
            ),
            (
                PACKAGE / "driver.py",
                "/opt/frozen-harness/driver.py",
            ),
            (
                PACKAGE / "process_runner.py",
                "/opt/frozen-harness/process_runner.py",
            ),
            (PACKAGE / "workspace.py", "/opt/frozen-harness/workspace.py"),
            (PACKAGE / "budget_protocol.py", "/opt/frozen-harness/budget_protocol.py"),
        ]
        material_digests = {
            self.archive: self.materials["archive_sha256"],
            self.wheel: self.materials["runtime_sha256"],
            self.lock: self.materials["runtime_lock_sha256"],
            self.python_archive: self.materials["python_sha256"],
        }
        remote_digests = []
        for source, target in files:
            expected = (
                material_digests.get(source) or hashlib.sha256(source.read_bytes()).hexdigest()
            )
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Material changed before upload: {source.name}")
            remote_digests.append((expected, target))
            if source.stat().st_size <= 2 * 1024**2:
                await environment.upload_file(source, target)
                continue
            # Large interpreter uploads can exhaust a proxy's write deadline
            # when many trials start together. Assemble bounded, independently
            # acknowledged parts and verify the original archive digest.
            parts = []
            with tempfile.TemporaryDirectory(prefix="harness-upload-") as temp:
                with source.open("rb") as stream:
                    while chunk := stream.read(2 * 1024**2):
                        part = Path(temp) / f"part-{len(parts):04d}"
                        part.write_bytes(chunk)
                        remote = target + "." + part.name
                        await environment.upload_file(part, remote)
                        parts.append(shlex.quote(remote))
                await checked(
                    "cat "
                    + " ".join(parts)
                    + " > "
                    + shlex.quote(target)
                    + " && printf '%s  %s\\n' "
                    + shlex.quote(expected)
                    + " "
                    + shlex.quote(target)
                    + " | sha256sum -c - && rm -- "
                    + " ".join(parts),
                    command_timeout_sec=60,
                )
        checks = "".join(f"{digest}  {path}\n" for digest, path in remote_digests)
        await checked(
            "printf %s " + shlex.quote(checks) + " | sha256sum -c -", command_timeout_sec=30
        )
        await checked(
            "tar -xzf /opt/frozen-harness/materials/harness.tar.gz -C /opt/frozen-harness/source && "
            "test -f /opt/frozen-harness/source/entry.py && "
            "tar -xzf /opt/frozen-harness/materials/python.tar.gz -C /opt/frozen-harness && "
            # Official task images need not have uv or pip. The pinned Python
            # archive contains ensurepip, so provision from that interpreter.
            # Ignore task/user import paths for Harness Python only; shell
            # tools still inherit the task's original environment variables.
            "/opt/frozen-harness/python312/bin/python3.12 -E -s -m venv "
            "/opt/frozen-harness/runtime && "
            # Some official SWE-Pro images retain a build-time localhost pip
            # index. Scope this override to our separate Harness venv; never
            # change the task's pip config, project packages or verifier image.
            "PIP_CONFIG_FILE=/dev/null /opt/frozen-harness/runtime/bin/python -E -s -m pip "
            "--isolated install --index-url https://pypi.org/simple "
            "--disable-pip-version-check --no-deps -r "
            "/opt/frozen-harness/materials/runtime.lock && "
            "/opt/frozen-harness/runtime/bin/python -E -s -c 'from nexau import Agent, AgentConfig; "
            "from ag_ui.core import BaseEvent' && "
            "chmod -R a+rX /opt/frozen-harness",
            command_timeout_sec=900,
        )

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        self._task_budget = TaskBudget(
            self.request_timeout_sec, hashlib.sha256(str(self.logs_dir).encode()).hexdigest()[:24]
        )
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "budget-origin.json").write_text(self._task_budget.to_json())
        result = await environment.exec("pwd", timeout_sec=30)
        image_workdir = result.stdout.strip()
        if result.return_code != 0 or not Path(image_workdir).is_absolute():
            raise RuntimeError("Cannot resolve the official task image's WORKDIR")
        if self.workdir == "auto":
            self.workdir = image_workdir
        else:
            result = await environment.exec("test -d " + shlex.quote(self.workdir), timeout_sec=30)
            if result.return_code != 0:
                raise RuntimeError("Configured Harness task workspace is absent")
        result = await environment.exec(
            "/opt/frozen-harness/runtime/bin/python -E -s /opt/frozen-harness/workspace.py "
            + shlex.quote(self.workdir)
            + " /logs/agent/harness-workspace.json",
            timeout_sec=30,
        )
        if result.return_code:
            raise RuntimeError("Cannot establish Harness bookkeeping collection boundary")
        key = self._env_value("HARNESS_LLM_API_KEY", "LLM_API_KEY")
        base = self._env_value("HARNESS_LLM_BASE_URL", "LLM_BASE_URL")
        model = self.model_name or self._env_value("LLM_MODEL")
        if not key or not base or not model:
            raise RuntimeError("Harness model, base URL and API key are required")
        support = getattr(environment, "support", None)
        if self.mcp_servers:
            if support is None or not support.mcp_ready:
                raise RuntimeError("Task MCP servers require an available evaluation transport")
            await support.prepare_mcp(self.workdir)
            instruction += support.mcp_instructions()
        if self.skills_dir:
            skills = Path(self.skills_dir)
            if not skills.is_absolute():
                skills = Path(self.workdir) / skills
            instruction += (
                "\n\nTask-provided skills are available at "
                + shlex.quote(str(skills))
                + ". Inspect the relevant SKILL.md files before acting."
            )
        instruction_file = self.logs_dir / "public-instruction.md"
        instruction_file.write_text(instruction, encoding="utf-8")
        await environment.upload_file(instruction_file, "/opt/frozen-harness/instruction.md")
        context.metadata = {
            "adapter": self.import_path(),
            "harness_revision": self.revision,
            "model": model,
            "materials": self.materials,
            "workdir": self.workdir,
            "image_workdir": image_workdir,
            "request_timeout_sec": self.request_timeout_sec,
            "persistence_grace_sec": 600,
            "process_owner": "linux-child-subreaper",
            "harness_call_timeout_sec": self.call_timeout_sec,
            "internal_harness_budgets": "Archived defaults unless explicitly overridden",
            "mcp_transport": support.mcp_transport if self.mcp_servers else None,
            "skills_dir": self.skills_dir,
        }
        env = {
            "LLM_MODEL": model.removeprefix("openai/"),
            "LLM_BASE_URL": base,
            "LLM_API_KEY": key,
            "SANDBOX_WORK_DIR": self.workdir,
            "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
            "HARNESS_REQUEST_TIMEOUT_SEC": str(self.request_timeout_sec),
            **self._task_budget.environment(),
            "HARNESS_OBSERVATION_DIR": "/logs/agent/budget-observations",
            "PYTHONUNBUFFERED": "1",
            "HARNESS_LLM_OPTIONS_JSON": json.dumps(
                dict(self.llm_options, timeout_seconds=self.request_timeout_sec)
            ),
            "HARNESS_FORWARD_TIME_ADAPTATION": "1" if self.time_adaptation else "0",
        }
        if self.call_timeout_sec is not None:
            # Archived Harness versions expose different names. Supplying both
            # changes only the supported runtime budget, never archived code.
            env["HARNESS_CALL_TIMEOUT"] = str(self.call_timeout_sec)
            env["HARNESS_CALL_TIMEOUT_SECONDS"] = str(self.call_timeout_sec)
        wrapped, pid_file, cancel_file = self._process_owner.command(
            "/opt/frozen-harness/runtime/bin/python -E -s -u /opt/frozen-harness/driver.py"
        )
        try:
            result = await self.execute_driver(
                environment,
                wrapped,
                cwd="/opt/frozen-harness",
                env=env,
                timeout_sec=self.request_timeout_sec + 600,
            )
            context.metadata["return_code"] = result.return_code
            context.metadata["driver_output"] = self._save_driver_output(result, key)
        except (asyncio.CancelledError, Exception):
            await self._process_owner.cancel_shielded(environment, pid_file, cancel_file)
            raise
        finally:
            # Preserve the runtime records separately from the candidate diff.
            # Snapshot failure must not replace an existing execution exception.
            try:
                snapshot = await environment.exec(
                    "if test -d "
                    + shlex.quote(self.workdir + "/.harness")
                    + "; then tar -czf /logs/agent/harness-bookkeeping.tar.gz -C "
                    + shlex.quote(self.workdir)
                    + " .harness; fi",
                    timeout_sec=60,
                )
                if snapshot.return_code:
                    self.logger.warning("Harness bookkeeping snapshot did not complete")
            except Exception as error:
                self.logger.warning("Harness bookkeeping snapshot failed: %s", type(error).__name__)
            if self.mcp_servers:
                await environment.finish_mcp()
        if result.return_code != 0:
            # Tracebacks can include a provider request; keep them in private logs.
            raise NonZeroAgentExitCodeError(
                f"Frozen Harness driver exited with code {result.return_code}; see agent logs"
            )

    async def execute_driver(self, environment, command, **kwargs):
        return await environment.exec(command, **kwargs)
