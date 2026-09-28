"""Adapter for benchmark-owned user simulators such as tau3."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..harness.protocol import TerminalKind
from .base import InteractionResult


class NativeUserInteraction:
    def __init__(
        self,
        next_message: Callable[[object | None], str | None],
        *,
        max_turns: int,
    ) -> None:
        self.next_message = next_message
        self.max_turns = max_turns

    def run(self, session, task: str, timeout_seconds: float) -> InteractionResult:
        started = time.monotonic()
        deadline = started + timeout_seconds
        result = InteractionResult(end_reason="evaluator_deadline")
        incoming: str | None = task
        for _ in range(self.max_turns):
            if incoming is None:
                result.end_reason = "native_user_terminal"
                result.normal_final_reply = bool(result.replies)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            session.write_message(incoming)
            kind, value = session.poll(remaining)
            if kind == "timer":
                break
            result.replies.append(value)
            if value.terminal_kind is not TerminalKind.NORMAL:
                result.end_reason = f"harness_{value.terminal_kind.value}"
                break
            incoming = self.next_message(value)
        else:
            result.end_reason = "max_turns"
        result.elapsed_seconds = time.monotonic() - started
        result.progress = list(session.last_progress)
        return result
