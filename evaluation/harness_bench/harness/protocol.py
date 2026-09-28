"""Versioned event types for the human-facing Harness boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProtocolError(RuntimeError):
    pass


class TerminalKind(StrEnum):
    NORMAL = "normal"
    SELF_TIMEOUT = "self_timeout"
    INTERRUPTED = "interrupted"
    REFUSED = "refused"


@dataclass(frozen=True)
class HarnessEvent:
    type: str
    payload: Mapping[str, Any]
    seq: int | None = None
    request_id: str | None = None

    @classmethod
    def parse(cls, value: object) -> HarnessEvent:
        if not isinstance(value, Mapping):
            raise ProtocolError("harness event must be an object")
        event_type = value.get("type")
        if not isinstance(event_type, str) or not event_type:
            if "reply" in value:
                event_type = "reply"
                value = {**value, "text": value.get("reply")}
            elif value.get("error") is not None:
                event_type = "error"
            else:
                raise ProtocolError("harness event has no type")
        seq = value.get("seq")
        if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int)):
            raise ProtocolError("event seq must be an integer")
        request_id = value.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise ProtocolError("event request_id must be a string")
        return cls(type=event_type, payload=dict(value), seq=seq, request_id=request_id)


@dataclass(frozen=True)
class HarnessReply:
    text: str
    terminal_kind: TerminalKind
    events: tuple[HarnessEvent, ...]
    elapsed_seconds: float
    request_id: str | None = None


def parse_terminal_kind(
    event: HarnessEvent,
    *,
    declared_timeout_prefixes: tuple[str, ...] = (),
    declared_interrupt_prefixes: tuple[str, ...] = (),
) -> TerminalKind:
    raw = event.payload.get("terminal_kind")
    if raw is not None:
        try:
            return TerminalKind(str(raw))
        except ValueError as exc:
            raise ProtocolError(f"invalid terminal_kind: {raw}") from exc
    text = event.payload.get("text", "")
    if not isinstance(text, str):
        raise ProtocolError("reply text must be a string")
    if any(text.startswith(prefix) for prefix in declared_timeout_prefixes):
        return TerminalKind.SELF_TIMEOUT
    if any(text.startswith(prefix) for prefix in declared_interrupt_prefixes):
        return TerminalKind.INTERRUPTED
    return TerminalKind.NORMAL
