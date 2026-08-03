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

# Optional streaming surface (Spec-0036): unified write + reply soft-wake poll.
# begin/emit_message remain as deprecated aliases forwarded via __getattr__.
_HEARTBEAT_METHODS = frozenset(
    {
        "write_message",
        "begin",
        "poll",
        "try_reply",
        "emit_message",
        "drain_visible_events",
    }
)
_OBSERVATION_ATTRS = frozenset(
    {
        "in_flight",
        "last_progress",
        "last_steps",
        "last_sideband",
        "last_visible_events",
        "visible_events",
        "help_text",
    }
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

    def write_message(self, message: str) -> None:
        """Unified stdin write (Spec-0036): one message frame, no begin/emit split.

        Prefers harness.write_message; falls back to deprecated begin/emit_message.
        """
        for name in ("write_message", "begin", "emit_message"):
            fn = getattr(self._harness, name, None)
            if callable(fn):
                fn(message)
                return
        raise AttributeError("wrapped harness has no write_message/begin/emit_message")

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
