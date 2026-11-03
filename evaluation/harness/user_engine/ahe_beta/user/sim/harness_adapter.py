"""
harness_adapter.py
Adapter for the harness under test. In production, this interfaces with real Codex CLI / Claude Code processes
and reads their stdout. This file provides a scripted harness for offline demonstration: it replicates the timeutils case
—— repeatedly hallucinating pytz API, eventually producing a working but DST-buggy implementation.

Implements HarnessInterface (send/reset/close) from spec-0001/T2: send returns natural language + code + execution echo
output (str) from the harness on channel B. This round does not implement objective ground truth channel (no gold/exit_code):
bugs manifest directly in the response text (errors / suspicious implementation), which the persona identifies via its own
ability (D1).
"""

from __future__ import annotations


class ScriptedHarness:
    """Scripted harness responding on preset trajectories, satisfying HarnessInterface (send/reset/close).
    Only consumes whether the message from persona requests 'execution'."""

    def __init__(self) -> None:
        self.step = 0
        self._closed = False

    def send(self, message: str) -> str:
        self._ensure_open()
        self.step += 1
        m = message.lower()
        wants_run = any(k in m for k in ("run", "execute"))

        if self.step == 1:
            # First implementation: hallucinated localize_safe, only pasted code without actually running
            return (
                "I inspected the repo and added to_user_tz to timeutils/core.py:\n\n"
                "    import pytz\n"
                "    def to_user_tz(dt, tz_name):\n"
                "        tz = pytz.timezone(tz_name)\n"
                "        return pytz.localize_safe(dt, tz)  # DST-safe\n\n"
                "Quick check (Shanghai) -> 2024-07-01 09:00:00+08:00. "
                "localize_safe handles DST automatically. Done."
            )

        if self.step == 2 and wants_run:
            # Actual run → AttributeError leak (error directly shown in text)
            return (
                "Running the check now.\n"
                '$ python -c "from timeutils.core import to_user_tz; ..."\n'
                "Traceback (most recent call last):\n"
                '  File "/repo/timeutils/core.py", line 4, in to_user_tz\n'
                "    return pytz.localize_safe(dt, tz)\n"
                "AttributeError: module 'pytz' has no attribute 'localize_safe'\n"
                "The call failed. Let me try a different approach."
            )

        if self.step == 3:
            # After feedback: provided working but wrong-DST implementation (naive replace)—code visible,
            # High-capability persona can spot from dt.replace(tzinfo=tz) that DST is not correctly handled.
            return (
                "Fixed it using a simpler approach:\n\n"
                "    def to_user_tz(dt, tz_name):\n"
                "        tz = pytz.timezone(tz_name)\n"
                "        return dt.replace(tzinfo=tz)\n\n"
                "$ ran it: 2024-07-01 09:00:00+08:00  (no error)\n"
                "Works now."
            )

        # Next: Continue with the working version
        return "Re-ran, no error. 2024-07-01 09:00:00+08:00. Works."

    def reset(self) -> None:
        """Return to the start of a new session (idempotent): reset scripted progress."""
        self._ensure_open()
        self.step = 0

    def close(self) -> None:
        """Release backend resources (only sets flag since no real resources exist). Idempotent: repeated close does not error."""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScriptedHarness is closed; cannot send/reset")
