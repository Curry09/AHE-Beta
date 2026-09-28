"""HarnessConnector: platform-side adapter to the human-facing harness interface."""

from __future__ import annotations

import pytest

from auto_designer.harness.connector import HarnessConnector
from auto_designer.harness.interface import FakeHarness, HarnessInterface
from auto_designer.usage import bind_usage_context, current_usage_context


class _ShutdownHarness(FakeHarness):
    def __init__(self) -> None:
        super().__init__()
        self.shutdowns = 0

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.close()


class _HeartbeatHarness(FakeHarness):
    def __init__(self) -> None:
        super().__init__(script=["reply"])
        self.writes: list[str] = []
        self.controls: list[str] = []
        self.last_progress = [{"kind": "tool", "text": "working"}]
        self.last_steps = [{"kind": "tool", "text": "read"}]
        self.last_sideband = [{"progress": {"kind": "tool", "text": "working"}}]
        self._inflight = False

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def write_message(self, message: str) -> None:
        self.writes.append(message)
        self._inflight = True

    def begin(self, message: str) -> None:
        self.write_message(message)

    def emit_message(self, message: str) -> None:
        self.write_message(message)

    def poll(self, timeout: float) -> tuple[str, object]:
        return ("pending", timeout)

    def try_reply(self) -> str | None:
        return None

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return f"[{name}]"


class _UsageHarness(FakeHarness):
    def __init__(self) -> None:
        super().__init__(script=["ok"])
        self.events = [
            {
                "provider": "nexau",
                "model": "m",
                "input_tokens": 2,
                "output_tokens": 1,
                "total_tokens": 3,
                "agent_run_id": "ha",
            }
        ]

    def drain_usage_events(self):
        events, self.events = self.events, []
        return events


def test_connector_satisfies_harness_interface_and_forwards_plain_message() -> None:
    wrapped = FakeHarness(callback=lambda msg: f"echo:{msg}")
    connector = HarnessConnector(wrapped)

    assert isinstance(connector, HarnessInterface)
    assert connector.send("hello") == "echo:hello"
    assert wrapped.sent == ["hello"]


def test_connector_keeps_platform_metadata_out_of_harness_message() -> None:
    wrapped = FakeHarness(callback=lambda msg: msg)
    connector = HarnessConnector(wrapped)

    connector.send_user_message("human text only")

    assert wrapped.sent == ["human text only"]


def test_connector_attributes_harness_usage_without_exposing_it(monkeypatch) -> None:
    recorded = []
    monkeypatch.setattr(
        "auto_designer.harness.connector.record_usage", lambda **event: recorded.append(event)
    )
    connector = HarnessConnector(_UsageHarness())
    with bind_usage_context(session_id="s", instance_id="i", interaction_id="turn-0"):
        assert connector.send("hello") == "ok"
    assert len(recorded) == 1
    assert recorded[0]["usage"]["total_tokens"] == 3
    assert not hasattr(connector, "last_progress")


def test_connector_close_attributes_late_usage_to_explicit_session_context(monkeypatch) -> None:
    class LateUsageHarness(FakeHarness):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        def drain_usage_events(self):
            if not self.closed:
                return []
            self.closed = False
            return [{"total_tokens": 5, "agent_run_id": "harness-run"}]

        def close(self) -> None:
            self.closed = True

    recorded = []

    def capture(**event):
        recorded.append((event, current_usage_context()))

    monkeypatch.setattr("auto_designer.harness.connector.record_usage", capture)
    connector = HarnessConnector(LateUsageHarness())
    with bind_usage_context(
        session_id="session-1",
        instance_id="instance-1",
        interaction_id="turn-2",
        turn_no=2,
    ):
        connector.close()

    assert len(recorded) == 1
    event, context = recorded[0]
    assert event["usage"]["total_tokens"] == 5
    assert context.session_id == "session-1"
    assert context.instance_id == "instance-1"
    assert context.interaction_id == "turn-2"
    assert context.turn_no == 2
    assert context.role == "harness"
    assert context.agent_id == "harness-run"


def test_connector_interrupt_drains_usage_immediately(monkeypatch) -> None:
    class InterruptUsageHarness(FakeHarness):
        def __init__(self) -> None:
            super().__init__()
            self.pending = []

        def control(self, name: str) -> str:
            assert name == "interrupt"
            self.pending.append({"total_tokens": 8})
            return "stopped"

        def drain_usage_events(self):
            pending, self.pending = self.pending, []
            return pending

    recorded = []
    monkeypatch.setattr(
        "auto_designer.harness.connector.record_usage", lambda **event: recorded.append(event)
    )
    connector = HarnessConnector(InterruptUsageHarness())

    assert connector.interrupt() == "stopped"
    assert [event["usage"]["total_tokens"] for event in recorded] == [8]


def test_connector_poll_wrapper_drains_usage_immediately(monkeypatch) -> None:
    class PollUsageHarness(_HeartbeatHarness):
        def __init__(self) -> None:
            super().__init__()
            self.pending = []

        def poll(self, timeout: float) -> tuple[str, object]:
            self.pending.append({"total_tokens": 13})
            return ("pending", timeout)

        def drain_usage_events(self):
            pending, self.pending = self.pending, []
            return pending

    recorded = []
    monkeypatch.setattr(
        "auto_designer.harness.connector.record_usage", lambda **event: recorded.append(event)
    )
    connector = HarnessConnector(PollUsageHarness())

    assert connector.poll(0.1) == ("pending", 0.1)
    assert [event["usage"]["total_tokens"] for event in recorded] == [13]


def test_connector_help_text_comes_from_wrapped_harness() -> None:
    wrapped = FakeHarness()
    wrapped.help_text = "User guide"

    assert HarnessConnector(wrapped).help_text == "User guide"


def test_connector_exposes_unified_write_and_optional_poll() -> None:
    plain = HarnessConnector(FakeHarness())
    assert hasattr(plain, "write_message")  # connector always exposes unified write
    assert not hasattr(plain, "poll")

    advanced = _HeartbeatHarness()
    connector = HarnessConnector(advanced)
    connector.write_message("work")
    connector.write_message("more detail")

    assert hasattr(connector, "poll")
    assert not hasattr(connector, "control")
    assert connector.in_flight is True
    assert connector.poll(0.1) == ("pending", 0.1)
    assert connector.try_reply() is None
    assert connector.last_progress == [{"kind": "tool", "text": "working"}]
    assert advanced.writes == ["work", "more detail"]


def test_connector_interrupt_uses_control_when_available() -> None:
    wrapped = _HeartbeatHarness()
    connector = HarnessConnector(wrapped)

    assert connector.interrupt() == "[interrupt]"
    assert wrapped.controls == ["interrupt"]


def test_connector_interrupt_closes_when_no_control_channel() -> None:
    wrapped = FakeHarness()
    connector = HarnessConnector(wrapped)

    assert connector.interrupt() is None
    with pytest.raises(RuntimeError):
        wrapped.send("after close")


def test_connector_shutdown_uses_wrapped_shutdown_when_available() -> None:
    wrapped = _ShutdownHarness()
    connector = HarnessConnector(wrapped)

    connector.shutdown()

    assert wrapped.shutdowns == 1
    with pytest.raises(RuntimeError):
        wrapped.reset()


def test_connector_shutdown_closes_wrapped_harness() -> None:
    wrapped = FakeHarness()
    connector = HarnessConnector(wrapped)

    connector.shutdown()

    with pytest.raises(RuntimeError):
        wrapped.reset()
