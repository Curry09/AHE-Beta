"""HarnessConnector: platform-side adapter to the human-facing harness interface."""

from __future__ import annotations

import pytest

from auto_designer.harness.connector import HarnessConnector
from auto_designer.harness.interface import FakeHarness, HarnessInterface


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
        self.begun: list[str] = []
        self.emitted: list[str] = []
        self.controls: list[str] = []
        self.last_progress = [{"kind": "tool", "text": "working"}]
        self.last_steps = [{"kind": "tool", "text": "read"}]
        self.last_sideband = [{"progress": {"kind": "tool", "text": "working"}}]
        self._inflight = False

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def begin(self, message: str) -> None:
        self.begun.append(message)
        self._inflight = True

    def poll(self, timeout: float) -> tuple[str, object]:
        return ("pending", timeout)

    def try_reply(self) -> str | None:
        return None

    def emit_message(self, message: str) -> None:
        self.emitted.append(message)

    def control(self, name: str) -> str:
        self.controls.append(name)
        self._inflight = False
        return f"[{name}]"


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


def test_connector_help_text_comes_from_wrapped_harness() -> None:
    wrapped = FakeHarness()
    wrapped.help_text = "User guide"

    assert HarnessConnector(wrapped).help_text == "User guide"


def test_connector_exposes_optional_heartbeat_surface_only_when_wrapped_has_it() -> None:
    plain = HarnessConnector(FakeHarness())
    assert not hasattr(plain, "begin")
    assert not hasattr(plain, "poll")

    advanced = _HeartbeatHarness()
    connector = HarnessConnector(advanced)
    connector.begin("work")
    connector.emit_message("more detail")

    assert hasattr(connector, "begin")
    assert not hasattr(connector, "control")
    assert connector.in_flight is True
    assert connector.poll(0.1) == ("pending", 0.1)
    assert connector.try_reply() is None
    assert connector.last_progress == [{"kind": "tool", "text": "working"}]
    assert advanced.begun == ["work"]
    assert advanced.emitted == ["more detail"]


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
