"""τ³/Tau2-Bench half-duplex adapter for frozen harness v0.

The harness itself only knows its shell tool. A tiny request helper converts a
shell command into an explicit marker; this adapter converts that marker to a
native tau2 ``ToolCall``. The official orchestrator still executes every domain
tool and returns the resulting ``ToolMessage`` on the next turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shlex
import tarfile
import tempfile
from typing import Any, Optional
import uuid

from tau2.agent.base_agent import HalfDuplexAgent
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.tool import Tool

from .stdio import HarnessStdioSession, harness_environment


_CALL_PATTERN = re.compile(
    r"<TAU3_TOOL_CALL>\s*(\{.*?\})\s*</TAU3_TOOL_CALL>", re.DOTALL
)
_REQUEST_HELPER = r'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

manifest = json.loads(Path(__file__).with_name("tau3_tools.json").read_text())
if len(sys.argv) != 3:
    raise SystemExit("usage: tau3_tool_request.py TOOL_NAME JSON_ARGUMENT_OBJECT")
name = sys.argv[1]
if name not in manifest:
    raise SystemExit(f"unknown tool: {name}; available: {', '.join(sorted(manifest))}")
try:
    arguments = json.loads(sys.argv[2])
except json.JSONDecodeError as exc:
    raise SystemExit(f"arguments are not valid JSON: {exc}")
if not isinstance(arguments, dict):
    raise SystemExit("arguments must decode to a JSON object")
payload = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
print(f"<TAU3_TOOL_CALL>{payload}</TAU3_TOOL_CALL>")
print("Return the marker above exactly via complete_task; do not call another tool yet.")
'''


@dataclass
class HarnessV0TauState:
    session: HarnessStdioSession
    workspace_temp: tempfile.TemporaryDirectory[str]
    harness_temp: tempfile.TemporaryDirectory[str] | None
    initialized: bool = False
    turns: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)


class HarnessV0TauAgent(HalfDuplexAgent[HarnessV0TauState]):
    """Expose frozen harness v0 as a native τ³ text agent."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        llm: str | None = None,
        llm_args: Optional[dict[str, Any]] = None,
        *,
        harness_archive: str | Path | None = None,
        harness_dir: str | Path | None = None,
        harness_python: str | Path | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        turn_timeout_sec: float = 360.0,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.llm = llm
        self.llm_args = llm_args or {}
        self._harness_archive = Path(
            harness_archive
            or os.environ.get(
                "HARNESS_V0_ARCHIVE",
                "/opt/pilot/harness-v0.tar.gz",
            )
        )
        self._harness_dir = Path(harness_dir) if harness_dir else None
        self._harness_python = str(
            harness_python
            or os.environ.get(
                "HARNESS_V0_PYTHON", "/opt/harness-venv/bin/python"
            )
        )
        self._model = model or os.environ.get("LLM_MODEL") or self._model_from_llm(llm)
        self._base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or self._default_base_url(llm)
        )
        self._api_key = (
            api_key
            or os.environ.get("LLM_API_KEY")
            or self._provider_key(llm)
        )
        self._turn_timeout_sec = float(turn_timeout_sec)
        self._active_state: HarnessV0TauState | None = None
        self._tools_by_name = {tool.name: tool for tool in tools}
        if len(self._tools_by_name) != len(tools):
            raise ValueError("tau3 tool names must be unique")

    @staticmethod
    def _model_from_llm(llm: str | None) -> str | None:
        if not llm:
            return None
        return llm.split("/", 1)[-1] if "/" in llm else llm

    @staticmethod
    def _default_base_url(llm: str | None) -> str | None:
        provider = (llm or "").split("/", 1)[0]
        if provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        if provider == "openai":
            return "https://api.openai.com/v1"
        return None

    @staticmethod
    def _provider_key(llm: str | None) -> str | None:
        provider = (llm or "").split("/", 1)[0]
        if provider == "openrouter":
            return os.environ.get("OPENROUTER_API_KEY")
        if provider == "openai":
            return os.environ.get("OPENAI_API_KEY")
        return None

    def _resolve_harness_dir(
        self,
    ) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
        if self._harness_dir is not None:
            if not (self._harness_dir / "entry.py").is_file():
                raise FileNotFoundError(f"invalid harness directory: {self._harness_dir}")
            return self._harness_dir, None
        if not self._harness_archive.is_file():
            raise FileNotFoundError(f"harness archive not found: {self._harness_archive}")
        temp = tempfile.TemporaryDirectory(prefix="tau3-harness-v0-")
        destination = Path(temp.name)
        with tarfile.open(self._harness_archive, "r:gz") as archive:
            archive.extractall(destination, filter="data")
        if not (destination / "entry.py").is_file():
            temp.cleanup()
            raise RuntimeError("frozen harness archive has no entry.py")
        return destination, temp

    def _write_tool_bridge(self, workspace: Path) -> Path:
        schemas = {
            name: tool.openai_schema["function"]
            for name, tool in self._tools_by_name.items()
        }
        manifest = workspace / "tau3_tools.json"
        manifest.write_text(
            json.dumps(schemas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        helper = workspace / "tau3_tool_request.py"
        helper.write_text(_REQUEST_HELPER, encoding="utf-8")
        helper.chmod(0o755)
        return helper

    def _bootstrap_prompt(self, helper: Path, history: list[Message] | None) -> str:
        tool_docs = json.dumps(
            {
                name: tool.openai_schema["function"]
                for name, tool in self._tools_by_name.items()
            },
            ensure_ascii=False,
            indent=2,
        )
        history_text = ""
        if history:
            history_text = "\n\nExisting conversation context:\n" + "\n".join(
                str(message) for message in history
            )
        command = f"{shlex.quote(self._harness_python)} {shlex.quote(str(helper))} TOOL_NAME 'JSON_OBJECT'"
        return f"""You are acting as a customer-service agent in a τ³ benchmark.

Follow this domain policy exactly:
<DOMAIN_POLICY>
{self.domain_policy}
</DOMAIN_POLICY>

Available business tools (official schemas):
<TOOLS>
{tool_docs}
</TOOLS>

When a business tool is needed, use run_shell_command to run exactly one request of this form:
  {command}
The helper does not execute the business action. It prints a
<TAU3_TOOL_CALL>...</TAU3_TOOL_CALL> marker. Immediately return that marker exactly
through complete_task and stop the current turn. The official τ³ orchestrator will
execute it and the next user message will contain the real tool result. Never invent
a tool result, never place both user-facing prose and a tool call in one turn, and do
not use shell commands for anything except this helper during this benchmark.
{history_text}"""

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> HarnessV0TauState:
        if self._active_state is not None:
            self.stop(state=self._active_state)
        missing = [
            name
            for name, value in (
                ("model", self._model),
                ("base_url", self._base_url),
                ("api_key", self._api_key),
            )
            if not value
        ]
        if missing:
            raise ValueError("missing harness model configuration: " + ", ".join(missing))
        if not Path(self._harness_python).is_file():
            raise FileNotFoundError(f"harness Python not found: {self._harness_python}")

        workspace_temp = tempfile.TemporaryDirectory(prefix="tau3-harness-work-")
        workspace = Path(workspace_temp.name)
        helper = self._write_tool_bridge(workspace)
        harness_dir, harness_temp = self._resolve_harness_dir()
        (workspace / "bootstrap.txt").write_text(
            self._bootstrap_prompt(helper, message_history), encoding="utf-8"
        )
        env = harness_environment(
            work_dir=workspace,
            model=self._model,
            base_url=self._base_url,
            api_key=self._api_key,
            parent=os.environ,
        )
        session = HarnessStdioSession(
            [self._harness_python, "-u", str(harness_dir / "entry.py")],
            cwd=harness_dir,
            env=env,
            transcript_path=workspace / "harness-transcript.jsonl",
            stderr_path=workspace / "harness-stderr.log",
        )
        state = HarnessV0TauState(
            session=session,
            workspace_temp=workspace_temp,
            harness_temp=harness_temp,
        )
        self._active_state = state
        return state

    @staticmethod
    def _format_input(message: UserMessage | ToolMessage | MultiToolMessage) -> str:
        if isinstance(message, UserMessage):
            return message.content or ""
        if isinstance(message, MultiToolMessage):
            results = [HarnessV0TauAgent._format_input(item) for item in message.tool_messages]
            return "The official τ³ environment returned these tool results:\n" + "\n".join(results)
        status = "ERROR" if message.error else "SUCCESS"
        return (
            f"The official τ³ environment returned tool result {status} "
            f"for call id {message.id}:\n{message.content or ''}\n"
            "Continue the task. Call another business tool if required; otherwise answer the user."
        )

    def _parse_tool_call(self, reply: str) -> ToolCall | None:
        matches = list(_CALL_PATTERN.finditer(reply))
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("harness returned more than one τ³ tool request in a turn")
        try:
            payload = json.loads(matches[0].group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("harness returned malformed τ³ tool JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("τ³ tool request must be a JSON object")
        name = payload.get("name")
        arguments = payload.get("arguments")
        if name not in self._tools_by_name:
            raise ValueError(f"harness requested unknown τ³ tool: {name!r}")
        if not isinstance(arguments, dict):
            raise ValueError("τ³ tool arguments must be a JSON object")
        validated = self._tools_by_name[name].params.model_validate(arguments)
        return ToolCall(
            id=f"harness-v0-{uuid.uuid4().hex}",
            name=name,
            arguments=validated.model_dump(),
            requestor="assistant",
        )

    def generate_next_message(
        self,
        message: UserMessage | ToolMessage | MultiToolMessage,
        state: HarnessV0TauState,
    ) -> tuple[AssistantMessage, HarnessV0TauState]:
        incoming = self._format_input(message)
        if not state.initialized:
            bootstrap = Path(state.workspace_temp.name, "bootstrap.txt").read_text(
                encoding="utf-8"
            )
            incoming = bootstrap + "\n\nCurrent user message:\n" + incoming
            state.initialized = True
        reply = state.session.request(incoming, timeout=self._turn_timeout_sec)
        state.turns += 1
        state.transcript.append(
            {
                "turn": state.turns,
                "input_type": type(message).__name__,
                "reply": reply.text,
                "elapsed_seconds": reply.elapsed_seconds,
            }
        )
        tool_call = self._parse_tool_call(reply.text)
        if tool_call is not None:
            output = AssistantMessage(
                role="assistant",
                content=None,
                tool_calls=[tool_call],
                raw_data={"adapter": "harness-v0", "protocol_events": len(reply.events)},
            )
        else:
            if not reply.text.strip():
                raise ValueError("harness returned an empty user-facing reply")
            output = AssistantMessage.text(
                reply.text,
                raw_data={"adapter": "harness-v0", "protocol_events": len(reply.events)},
            )
        return output, state

    def stop(
        self,
        message: Optional[UserMessage | ToolMessage | MultiToolMessage] = None,
        state: Optional[HarnessV0TauState] = None,
    ) -> None:
        target = state or self._active_state
        if target is None:
            return
        target.session.close()
        if target.harness_temp is not None:
            target.harness_temp.cleanup()
        target.workspace_temp.cleanup()
        if target is self._active_state:
            self._active_state = None


def create_harness_v0_agent(
    tools: list[Tool], domain_policy: str, **kwargs: Any
) -> HarnessV0TauAgent:
    """Factory compatible with ``tau2.registry.register_agent_factory``."""

    allowed = {
        "llm",
        "llm_args",
        "harness_archive",
        "harness_dir",
        "harness_python",
        "model",
        "base_url",
        "api_key",
        "turn_timeout_sec",
    }
    return HarnessV0TauAgent(
        tools=tools,
        domain_policy=domain_policy,
        **{key: value for key, value in kwargs.items() if key in allowed},
    )


def register_harness_v0_agent(name: str = "harness_v0") -> None:
    """Register the factory in the process-local tau2 registry."""

    from tau2.registry import registry

    registry.register_agent_factory(create_harness_v0_agent, name)
