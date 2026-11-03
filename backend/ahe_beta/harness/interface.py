"""Multi-turn harness protocol HarnessInterface and test backend FakeHarness (spec-0001/T2).

Callers depend on this protocol. The harness entry point controls its internal arrangement
of one or more nexau agents; see spec-0003 for the real launcher backend.
The three methods are send/reset/close, with lifecycle (reset? · send* · close).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

# Fixed placeholder reply when no script/callback is injected.
_PLACEHOLDER = "[fake-harness] no reply configured"


@runtime_checkable
class HarnessInterface(Protocol):
    """Black-box protocol for multi-turn harness conversations, using structural subtyping.

    Both the real launcher handle and FakeHarness expose an optional duck-typed `help_text: str`
    attribute containing the full HELP.md for that harness version. It is deliberately excluded
    from the protocol: runtime_checkable includes data members in isinstance checks, which would
    reject legacy stubs without this attribute. Read it with `getattr(harness, "help_text", "")`
    to support older backends.
    """

    def send(self, message: str) -> str:
        """Send a user message, return harness's complete reply for this turn (non-streaming, single complete str; can be empty)."""
        ...

    def reset(self) -> None:
        """Discard current session state, return to fresh start. Idempotent."""
        ...

    def close(self) -> None:
        """Release backend resources. Idempotent."""
        ...


class FakeHarness:
    """Deterministic test backend with either scripted replies or a reply callback, never both.

    Scripted replies are consumed in order. Received messages are recorded in sent for assertions.
    Calling send/reset after close raises RuntimeError.
    """

    def __init__(
        self,
        script: list[str] | None = None,
        callback: Callable[[str], str] | None = None,
    ) -> None:
        if script is not None and callback is not None:
            raise ValueError("script and callback are mutually exclusive; supply only one")
        self._script = list(script) if script is not None else None
        self._callback = callback
        self._cursor = 0
        self._sent: list[str] = []
        self._closed = False
        # Test backend has no help text by default; callers may assign it as needed
        self.help_text = ""

    @property
    def sent(self) -> list[str]:
        """Read-only: sequence of all received messages."""
        return list(self._sent)

    def send(self, message: str) -> str:
        self._ensure_open()
        self._sent.append(message)
        if self._callback is not None:
            return self._callback(message)
        if self._script is not None:
            # Raises IndexError when exhausted, exposing insufficient turn configuration
            reply = self._script[self._cursor]
            self._cursor += 1
            return reply
        return _PLACEHOLDER

    def reset(self) -> None:
        self._ensure_open()
        self._sent.clear()
        self._cursor = 0

    def close(self) -> None:
        self._closed = True  # Idempotent: repeated close does not raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("FakeHarness is closed; send/reset is unavailable")
