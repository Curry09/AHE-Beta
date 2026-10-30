"""Run the pinned official ARE image in a separate provider sandbox.

Only public MCP responses cross into the agent. Scenario/oracle filesystem and
judge credentials stay in the sidecar. Logs are collected before verification.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from datetime import UTC, datetime
from pathlib import Path

import yaml
from harbor.models.task.config import EnvironmentConfig

from evaluation.environments.files import list_requests, read_bytes, write_bytes

from .mcp_timeouts import transport_timeouts


def sidecar_config(spec):
    if any(key in spec for key in ("cpus", "mem_limit", "deploy")):
        raise ValueError("Explicit compose resource declarations need an adapter")
    return EnvironmentConfig(docker_image=spec["image"], workdir="/opt/are-sidecar")


class AreSidecar:
    def __init__(self, parent):
        self.parent = parent
        self.child = None
        self.pump = None
        self.failure = None
        self.seen = set()
        self.pending_responses = {}
        self.transport_events = []

    def _record_transport_error(self, stage, error, attempt):
        # SDK exceptions can contain authenticated request URLs. Redact known
        # secrets before saving bounded diagnostic messages in private trials.
        chain = []
        current = error
        for _ in range(4):
            if current is None:
                break
            message = str(current)
            for key, value in os.environ.items():
                if (
                    any(word in key.upper() for word in ("KEY", "TOKEN", "PASSWORD"))
                    and len(value) > 4
                ):
                    message = message.replace(value, "[redacted]")
            chain.append({"type": type(current).__name__, "message": message[:1500]})
            current = current.__cause__
        event = {
            "stage": stage,
            "attempt": attempt,
            "errors": chain,
            "at": datetime.now(UTC).isoformat(),
        }
        self.transport_events.append(event)
        path = self.parent.trial_paths.trial_dir / "infrastructure/mcp-transport.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.transport_events, indent=2))

    async def _io(self, stage, operation):
        # Only read-only filesystem operations and idempotent writes retry.
        # Never repeat an ARE action whose response may have been lost.
        for attempt in range(1, 4):
            try:
                return await asyncio.wait_for(operation(), timeout=45)
            except Exception as error:  # bounded I/O retries, diagnostics are redacted
                self._record_transport_error(stage, error, attempt)
                if attempt == 3:
                    raise
                await asyncio.sleep(attempt)

    async def start(self):
        context = self.parent.environment_dir
        compose = yaml.safe_load((context / "docker-compose.yaml").read_text())
        spec = compose["services"]["are-sidecar"]
        image = spec["image"]
        if "@sha256:" not in image:
            raise RuntimeError("ARE sidecar image must be digest-pinned")
        command = spec.get("command")
        if command not in (
            ["python", "are_mcp_server.py"],
            ["python", "are_mcp_server_soft_judge.py"],
        ):
            raise ValueError("Unsupported official ARE sidecar command")
        if self.parent.capabilities.docker_compose:
            child = ServiceEnvironment(self.parent, "are-sidecar")
            self.child = child
            self.managed = False
        else:
            child = type(self.parent)(
                environment_dir=context / "are-sidecar",
                environment_name=self.parent.environment_name + "-are",
                session_id=self.parent.session_id + "__are",
                trial_paths=self.parent.trial_paths,
                task_env_config=sidecar_config(spec),
                benchmark=self.parent.benchmark,
                role="are",
                **self.parent.child_kwargs(),
            )
            child.context_id = self.parent.context_id
            self.child = child
            self.managed = True
            await child.start(False)
            await child.exec("mkdir -p /opt/gaia2-task /logs", user="root")
            await child.upload_file(context / "scenario.json", "/opt/gaia2-task/scenario.json")
            await child.exec("chmod 444 /opt/gaia2-task/scenario.json", user="root")
            key = os.environ.get("JUDGE_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            if not key and command[-1] == "are_mcp_server_soft_judge.py":
                raise RuntimeError("ARE soft judge requires JUDGE_ANTHROPIC_API_KEY")
            env = {
                "SCENARIO_PATH": "/opt/gaia2-task/scenario.json",
                "DEMO_FS_PATH": "/opt/gaia2-filesystem/demo_filesystem",
                "EVENT_LOG_PATH": "/logs/are_event_log.json",
                "ANTHROPIC_API_KEY": key or "",
                "ANTHROPIC_BASE_URL": os.environ.get("JUDGE_ANTHROPIC_BASE_URL", ""),
                "ARE_JUDGE_MODEL": "claude-opus-5",
                "PYTHONUNBUFFERED": "1",
            }
            result = await child.exec(
                "nohup " + shlex.join(command) + " </dev/null >/logs/server.log 2>&1 & echo $!",
                env=env,
                user="root",
                timeout_sec=30,
            )
            if result.return_code:
                raise RuntimeError("Official ARE sidecar server launch failed")
            self.server_pid = result.stdout.strip()
        for _i in range(60):
            probe = await child.exec(
                "python -c \"import socket;s=socket.create_connection(('127.0.0.1',8000),timeout=2);s.close()\"",
                timeout_sec=5,
                user="root",
            )
            if not probe.return_code:
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError("Official ARE MCP server never became healthy")
        await self.parent.exec(
            "mkdir -p /opt/harbor-mcp/requests /opt/harbor-mcp/responses /logs/are-sidecar; chmod -R a+rwX /opt/harbor-mcp",
            user="root",
        )
        await self.parent.upload_file(
            Path(__file__).with_name("mcp_timeouts.py"), "/opt/harbor-mcp/mcp_timeouts.py"
        )
        await self.parent.upload_file(
            Path(__file__).with_name("mcp_shell_client.py"), "/opt/harbor-mcp/client.py"
        )
        self.pump = asyncio.create_task(self._pump())

    async def call(self, request):
        tool = request["tool"]
        arguments = request.get("arguments", {})
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            raise TypeError("Malformed MCP tool request")
        script = "import asyncio,json\nfrom fastmcp import Client\nasync def main():\n async with Client('http://127.0.0.1:8000/mcp') as c:\n"
        if tool == "list":
            script += "  result=await c.list_tools();print(json.dumps({'tools':[x.model_dump(mode='json') for x in result]}))\n"
        else:
            script += f"  result=await c.call_tool({tool!r},{arguments!r},raise_on_error=False);print(json.dumps({{'isError':result.is_error,'content':[x.model_dump(mode='json') for x in result.content]}},ensure_ascii=False))\n"
        script += "asyncio.run(main())"
        operation_timeout, _, _ = transport_timeouts(tool, arguments)
        result = await self.child.exec(
            "python -c " + shlex.quote(script), user="root", timeout_sec=operation_timeout
        )
        if result.return_code:
            raise RuntimeError("Official MCP call failed: " + result.stderr[-1500:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    async def _pump(self):
        try:
            while True:
                files = await self._io(
                    "search_requests",
                    lambda: list_requests(self.parent),
                )
                for name in files:
                    path = "/opt/harbor-mcp/requests/" + name
                    if name in self.seen:
                        continue
                    if name not in self.pending_responses:
                        request = await self._io(
                            "read_request",
                            lambda path=path: read_bytes(self.parent, path),
                        )
                        try:
                            response = await self.call(json.loads(request))
                        except Exception as e:  # noqa: BLE001 - do not retry potentially executed tools
                            self._record_transport_error("mcp_call", e, 1)
                            # Tool errors are structured responses. Exceptions here
                            # mean transport loss: retain artifacts, exclude the score.
                            self.failure = type(e).__name__
                            response = {"isError": True, "error_type": type(e).__name__}
                        self.pending_responses[name] = json.dumps(response, ensure_ascii=False)
                    await self._io(
                        "write_response",
                        lambda name=name: write_bytes(
                            self.parent,
                            "/opt/harbor-mcp/responses/" + name,
                            self.pending_responses[name],
                        ),
                    )
                    self.seen.add(name)
                    self.pending_responses.pop(name)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - record a safe transport failure type
            self.failure = type(e).__name__

    async def collect(self):
        for name in ["are_event_log.json", "provenance.json"]:
            data = await self._io(
                "collect_read_" + name,
                lambda name=name: read_bytes(self.child, "/logs/" + name),
            )
            await self._io(
                "collect_write_" + name,
                lambda name=name, data=data: write_bytes(
                    self.parent,
                    "/logs/are-sidecar/" + name,
                    data,
                ),
            )
        if self.failure:
            # Retain real artifacts before reporting an invalid transport.
            raise RuntimeError("MCP transport infrastructure failed: " + self.failure)

    async def stop(self):
        if self.pump:
            self.pump.cancel()
            try:
                await self.pump
            except asyncio.CancelledError:
                pass
        if self.child:
            logs = self.parent.trial_paths.trial_dir / "infrastructure/are"
            logs.mkdir(parents=True, exist_ok=True)
            try:
                await self.child.download_dir("/logs", logs)
            finally:
                if self.managed:
                    await self.child.stop(True)


class ServiceEnvironment:
    """Address a native Compose service through Harbor's public interface."""

    def __init__(self, parent, service):
        self.parent = parent
        self.service = service

    async def exec(self, *args, **kwargs):
        return await self.parent.service_exec(*args, service=self.service, **kwargs)

    async def download_file(self, source, target):
        return await self.parent.service_download_file(source, target, service=self.service)

    async def download_dir(self, source, target):
        return await self.parent.service_download_dir(source, target, service=self.service)
