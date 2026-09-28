"""Interaction-policy contracts independent of a sandbox provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from ..harness.protocol import HarnessReply


class UserActionKind(StrEnum):
    KEEP_WAITING = "keep_waiting"
    SEND_MESSAGE = "send_message"
    INTERRUPT = "interrupt"
    GIVE_UP = "give_up"
    ACCEPT = "accept"


@dataclass(frozen=True)
class UserAction:
    kind: UserActionKind
    message: str = ""
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.kind is UserActionKind.SEND_MESSAGE and not self.message.strip():
            raise ValueError("send_message requires non-empty message text")
        if self.kind is not UserActionKind.SEND_MESSAGE and self.message:
            raise ValueError(f"{self.kind} cannot carry message text")


@dataclass(frozen=True)
class UserObservation:
    phase: str
    task: str
    history: tuple[dict[str, Any], ...]
    progress: tuple[dict[str, Any], ...]
    elapsed_seconds: float
    remaining_seconds: float
    reply: HarnessReply | None = None
    help_text: str = ""


class UserPolicy(Protocol):
    def decide(self, observation: UserObservation) -> UserAction: ...


@dataclass
class InteractionResult:
    end_reason: str
    replies: list[HarnessReply] = field(default_factory=list)
    user_actions: list[dict[str, Any]] = field(default_factory=list)
    progress: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    normal_final_reply: bool = False


class Interaction(Protocol):
    def run(self, session: Any, task: str, timeout_seconds: float) -> InteractionResult: ...
