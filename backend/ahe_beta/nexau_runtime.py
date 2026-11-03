"""Single nexau adapter (spec-0003/T2): load a role definition (prompt + tools) into a callable Agent.

Shared by all three roles (user/developer/test): load(agent_def_dir) reads the definition and builds
an Agent; Agent.run(input) makes one nexau call and returns output text. This thin wrapper retains
no session memory; consumers orchestrate multiple turns. The MVP supports nexau only; load will
later dispatch to CC/codex.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Required system prompt filename within the role definition directory.
_PROMPT_FILE = "prompt.md"
# Fallback retry count for the entire agent.run call when the gateway returns an occasional 502.
_RUN_RETRIES = 4
# Hard timeout per agent.run (seconds): nexau llm_config.timeout proved ineffective, so a thread prevents indefinite waits here.
_CALL_TIMEOUT = 240


def _run_with_timeout(call: Callable[[], object], timeout: int) -> object:
    """Run call in a daemon thread; raise TimeoutError after timeout seconds (abandon the thread without blocking process exit)."""
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = call()
        except Exception as exc:  # noqa: BLE001  Pass through for caller evaluation/retry
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"nexau call timeout >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


# nexau backend: (system_prompt, input) -> output_text. Injectable for test doubles.
Backend = Callable[[str, str], str]


def _default_nexau_backend(system_prompt: str, user_input: str) -> str:
    """Real nexau backend: build a tool-free nexau Agent from system_prompt and the LLM_* environment, then run once.

    Each call creates a fresh transient Agent to avoid history leakage; callers assemble context in user_input.
    Load nexau lazily and fail explicitly if it is missing. Retry the entire run to handle intermittent gateway 502s.
    """
    from nexau import Agent  # noqa: PLC0415  Runtime dependency, loaded lazily

    model = os.environ["LLM_MODEL"]
    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]

    last_err: Exception | None = None
    for attempt in range(_RUN_RETRIES):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "prompt.md").write_text(system_prompt, encoding="utf-8")
            (Path(tmp) / "agent.yaml").write_text(
                "type: agent\n"
                "name: role\n"
                "max_context_tokens: 256000\n"
                "system_prompt: ./prompt.md\n"
                "system_prompt_type: file\n"
                "llm_config:\n"
                f"  model: {model}\n"
                f"  base_url: {base_url}\n"
                f"  api_key: {api_key}\n"
                + (
                    f"  reasoning_effort: {os.environ['LLM_REASONING_EFFORT']}\n"
                    if os.environ.get("LLM_REASONING_EFFORT")
                    else ""
                )
                + "  max_tokens: 32768\n"
                # Per-call timeout: without it the openai client hangs indefinitely; a timeout triggers this module's retry.
                "  timeout: 300\n"
                "  api_type: openai_chat_completion\n",
                encoding="utf-8",
            )
            try:
                agent = Agent.from_yaml(Path(tmp) / "agent.yaml")
                out = _run_with_timeout(lambda a=agent: a.run(message=user_input), _CALL_TIMEOUT)
                return out if isinstance(out, str) else out[0]
            except Exception as exc:  # Gateway 502/timeout -> back off and retry
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"nexau call failed after {_RUN_RETRIES} retries: {last_err}") from last_err


class Agent:
    """Loaded callable role: run wraps nexau without prompt engineering, retries, or session memory."""

    def __init__(self, prompt: str, backend: Backend) -> None:
        self._prompt = prompt
        self._backend = backend

    @property
    def prompt(self) -> str:
        return self._prompt

    def run(self, user_input: str) -> str:
        return self._backend(self._prompt, user_input)  # Pass nexau call failures through unchanged


def load(agent_def_dir: str) -> Agent:
    """Read the role definition directory, parse the prompt, and build an Agent. Raise if the directory or prompt.md is missing."""
    root = Path(agent_def_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Role definition directory does not exist: {root}")
    prompt_path = root / _PROMPT_FILE
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Role definition is missing {_PROMPT_FILE}: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    return Agent(prompt=prompt, backend=_default_nexau_backend)
