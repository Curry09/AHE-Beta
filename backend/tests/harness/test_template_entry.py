"""Unit tests for the robustness of _reply in the harness seed entry.py: empty replies must not pass silently (no real nexau/network dependency).

entry.py lives in harness_template/ (not a package); load it by path with importlib and use a fake agent to verify retries and interrupts.
For actual NexAU terminal-state evidence and process-protocol verification, see test_seed_terminal_status.py.
"""

from __future__ import annotations

import importlib.util
import queue
import threading
from pathlib import Path
from types import ModuleType

import pytest

_ENTRY = Path(__file__).resolve().parents[2] / "harness_template" / "entry.py"
_TEMPLATE = _ENTRY.parent


def _load_entry() -> ModuleType:
    spec = importlib.util.spec_from_file_location("harness_template_entry", _ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Agent:
    """Returns items from a preset sequence one call at a time; Exception entries are raised, everything else is returned as-is. Records the call count."""

    def __init__(self, outs: list) -> None:
        self._outs = list(outs)
        self.calls = 0
        self.history: list = []

    def run(self, *, message: str):
        value = self._outs[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture()
def entry(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # Match `python entry.py`: sibling seed modules are on the entrypoint import path.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "harness_template"))
    module = _load_entry()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)  # Backoff does not actually sleep
    return module


def _no_rebuild(_stale):
    """Non-timeout cases must not trigger a rebuild; fails if it is ever called."""
    raise AssertionError("rebuild Should not be called")


def test_meta_spec_documents_baseline_and_changeability() -> None:
    """The Meta-Spec provides the project baseline, but does not freeze the current implementation as unmodifiable."""
    text = (_TEMPLATE / "META_SPEC.md").read_text(encoding="utf-8")
    assert "session_id" in text
    assert "Both the harness and NexAU can be modified" in text
    assert "neither an SDD Spec nor a frozen Implementation checklist" in text
    assert "Terminology and naming standard" in text
    assert "Spec topology" in text and "Execution DAG" in text
    assert "SDD Spec" in text and "Objective Contract" in text
    assert "MUST" in text and "OBSERVED" in text
    assert "Terminology is an evolution invariant" in text


def test_system_prompt_loads_instructions_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise NexAU's real prompt loader without a model call or template-root cwd."""
    from nexau import AgentConfig
    from nexau.archs.main_sub.prompt_builder import PromptBuilder

    monkeypatch.setenv("LLM_MODEL", "offline-test")
    monkeypatch.setenv("LLM_BASE_URL", "https://offline.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "offline-test")
    monkeypatch.chdir(tmp_path)

    config = AgentConfig.from_yaml(config_path=_TEMPLATE / "agent.yaml")
    parts = PromptBuilder().build_system_prompt(
        agent_config=config,
        runtime_context={"working_directory": str(tmp_path)},
        include_tool_instructions=False,
    )

    # The structured-tool runtime uses this base prompt as its system message.
    expected = (_TEMPLATE / "agents" / "main.md").read_text(encoding="utf-8").rstrip("\n")
    assert [part.text for part in parts] == [expected]


def test_reply_without_execution_facts_is_not_completed(entry: ModuleType) -> None:
    agent = _Agent(["hello"])
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild)
    assert text == "[incomplete: unavailable]\nhello"
    assert status == "incomplete"
    assert out_agent is agent  # No rebuild; the same instance is reused
    assert agent.calls == 1


def test_reply_retries_on_blank_then_succeeds(entry: ModuleType) -> None:
    agent = _Agent(["", "   ", "real answer"])
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild)
    assert text == "[incomplete: unavailable]\nreal answer"
    assert status == "incomplete"
    assert out_agent is agent  # Empty replies retry on the same agent, no rebuild
    assert agent.calls == 3  # Both empty strings and pure whitespace trigger a retry


def test_reply_all_blank_returns_explicit_marker(entry: ModuleType) -> None:
    agent = _Agent(["", "", "", ""])
    _, out, status = entry._reply(agent, "hi", _no_rebuild)
    assert out != ""  # Key point: never silently return empty
    assert out.startswith("[harness error]")
    assert status == "crashed"


def test_reply_exception_then_marker(entry: ModuleType) -> None:
    agent = _Agent(
        [RuntimeError("502"), RuntimeError("502"), RuntimeError("502"), RuntimeError("502")]
    )
    _, out, status = entry._reply(agent, "hi", _no_rebuild)
    assert out.startswith("[harness error]")
    assert status == "crashed"


def test_run_supervised_has_no_wall_clock_timeout(entry: ModuleType) -> None:
    """A slow agent can only be ended by completion or a persona interrupt; it is no longer dropped by the harness deadline."""

    release = threading.Event()

    class SlowAgent:
        def run(self, *, message: str):  # noqa: ARG002
            release.wait()
            return "finished"

    box: dict = {}
    worker = threading.Thread(
        target=lambda: box.setdefault("out", entry._run_supervised(SlowAgent(), "hi", None))
    )
    worker.start()
    assert worker.is_alive()
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert box["out"] == "finished"


def test_snapshot_and_restore_history_roundtrip(entry: ModuleType) -> None:
    """_snapshot_history / _restore_history: pure helpers for rebuild wiring, with no real nexau dependency."""
    src = _Agent([])
    src.history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    snap = entry._snapshot_history(src)
    dst = _Agent([])
    entry._restore_history(dst, snap)
    assert dst.history == src.history


class _StopExec:
    """Fake executor: force_stop sets the stopped event (simulating nexau's graceful-stop primitive; thread-safe)."""

    def __init__(self) -> None:
        self.stopped = threading.Event()

    def force_stop(self) -> None:
        self.stopped.set()


class _StoppableAgent:
    """agent.run blocks until executor.force_stop is set, then returns gracefully (simulating an interruptible run that preserves the session)."""

    def __init__(self) -> None:
        self.executor = _StopExec()
        self.calls = 0
        self.history: list = ["kept"]

    def run(self, *, message: str):  # noqa: ARG002
        self.calls += 1
        # Exits gracefully as soon as the stop signal is received
        self.executor.stopped.wait(timeout=5)
        return "partial work (discarded on interrupt)"


def test_reply_interrupt_gracefully_stops_and_keeps_agent(entry: ModuleType) -> None:
    """Interrupt: ctrl_q received interrupt → force_stop graceful shutdown → return to stable state [interrupted], no retry, preserve same agent (session retained)."""
    agent = _StoppableAgent()
    ctrl_q: queue.Queue = queue.Queue()
    threading.Timer(0.2, lambda: ctrl_q.put({"type": "interrupt"})).start()
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild, ctrl_q)
    assert text == entry._INTERRUPT_REPLY
    # Graceful shutdown preserves history → reuse same instance, no rebuild
    assert out_agent is agent
    assert agent.executor.stopped.is_set()  # Stop signal definitely set
    assert status == "interrupted"


class _UnstoppableAgent:
    """No executor.force_stop (legacy nexau): interrupt cannot gracefully stop → must discard instance and rebuild to avoid self-deadlock."""

    def __init__(self) -> None:
        self.calls = 0
        self.history: list = ["from-stale"]
        self._never = threading.Event()

    def run(self, *, message: str):  # noqa: ARG002
        self.calls += 1
        # Use Event.wait for true blocking (time.sleep replaced with no-op by fixture)
        self._never.wait(timeout=5)
        return "x"


def test_reply_interrupt_without_stop_capability_rebuilds_with_history(entry: ModuleType) -> None:
    stale = _UnstoppableAgent()
    fresh = _Agent(["after rebuild interrupt"])
    ctrl_q: queue.Queue = queue.Queue()
    ctrl_q.put({"type": "interrupt"})  # Interrupt present from start

    def rebuild(old):
        fresh.history = list(getattr(old, "history", []) or [])
        return fresh

    out_agent, text, status = entry._reply(stale, "hi", rebuild, ctrl_q)
    assert text == entry._INTERRUPT_REPLY  # Interrupt still returns stable response, no retry
    assert out_agent is fresh  # No graceful shutdown capability → rebuild to avoid self-deadlock
    assert fresh.history == ["from-stale"]
    assert status == "interrupted"
