"""Official single-input policy: one user message and no follow-up."""

from __future__ import annotations

import time

from ..harness.protocol import TerminalKind
from .base import InteractionResult


class DirectInteraction:
    def run(self, session, task: str, timeout_seconds: float) -> InteractionResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        started = time.monotonic()
        session.write_message(task)
        kind, value = session.poll(timeout_seconds)
        if kind == "timer":
            return InteractionResult(
                end_reason="evaluator_deadline",
                progress=list(session.last_progress),
                elapsed_seconds=time.monotonic() - started,
            )
        reply = value
        return InteractionResult(
            end_reason=(
                "normal_reply"
                if reply.terminal_kind is TerminalKind.NORMAL
                else f"harness_{reply.terminal_kind.value}"
            ),
            replies=[reply],
            progress=list(session.last_progress),
            elapsed_seconds=time.monotonic() - started,
            normal_final_reply=reply.terminal_kind is TerminalKind.NORMAL,
        )
