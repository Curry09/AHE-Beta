"""Platform-side connector from simulated users to the harness human-facing interface.

The harness is a human-runnable product: it accepts human-like messages and returns
progress/replies/errors. auto-designer owns the training/observation concepts around
that product. This connector is the thin adapter boundary: simulated-user actions go
through it, but persona, feeling, issue, round, and trace metadata stay on the
platform side.
"""

from __future__ import annotations

from typing import Any

from auto_designer.harness.interface import HarnessInterface

_HEARTBEAT_METHODS = frozenset({"begin", "poll", "try_reply", "emit_message"})
_OBSERVATION_ATTRS = frozenset(
    {"in_flight", "last_progress", "last_steps", "last_sideband", "help_text"}
)


class HarnessConnector:
    """Adapt platform callers to the harness's human-facing runtime interface.

    The required HarnessInterface surface is intentionally unchanged: send/reset/close.
    Optional streaming/heartbeat methods are exposed only when the wrapped harness
    already supports them, preserving existing feature detection via hasattr().
    """

    def __init__(self, harness: HarnessInterface) -> None:
        self._harness = harness

    @property
    def help_text(self) -> str:
        """Human-facing help text exposed by the harness version, if any."""
        return str(getattr(self._harness, "help_text", "") or "")

    def send(self, message: str) -> str:
        """Send one human-like message to the harness and return its final reply."""
        return self.send_user_message(message)

    def send_user_message(self, text: str) -> str:
        """Adapter entry for a simulated user's message action.

        Only the text a human could have typed crosses into the harness. Platform
        metadata remains outside this call.
        """
        return self._harness.send(text)

    def interrupt(self) -> str | None:
        """Adapter entry for a simulated user's interrupt action.

        If the harness exposes an in-flight control channel, use it. Otherwise close
        the process as a best-effort stop and leave interpretation to the platform.
        """
        control = getattr(self._harness, "control", None)
        if callable(control):
            return control("interrupt")
        self._harness.close()
        return None

    def shutdown(self) -> None:
        """Adapter entry for ending the human-facing harness process."""
        shutdown = getattr(self._harness, "shutdown", None)
        if callable(shutdown):
            shutdown()
            return
        self._harness.close()

    def reset(self) -> None:
        self._harness.reset()

    def close(self) -> None:
        self._harness.close()

    def __getattr__(self, name: str) -> Any:
        """Expose optional harness capabilities without lying to hasattr()."""
        if name in _HEARTBEAT_METHODS or name in _OBSERVATION_ATTRS:
            return getattr(self._harness, name)
        raise AttributeError(name)
