"""
actions.py
Action model—the framework's core. Eliminate ambiguity in run_once ownership.

Three attribute axes (any action must declare all three):
  executor executor:  PERSONA_LOCAL / HARNESS / FRAMEWORK
  channel  channel:   EMIT (send B-line NL) / SILENT (internal action, no utterance)
  effect   effect:    ADVANCE (progress) / VERIFY (check) / TERMINATE (end)

Message is not synonymous with channel: a terminate action may have optional user explanation,
but that explanation should not be projected as a harness message. Therefore each action also
declares message_policy: required / optional / forbidden. Violations enforced by assert_channel().
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Executor(StrEnum):
    PERSONA_LOCAL = "persona_local"  # User local mental action (speak/accept/abandon)
    HARNESS = "harness"  # Drive harness execution via B-line
    FRAMEWORK = "framework"  # Framework executes on behalf of persona, filters ground truth by capability mask


class Channel(StrEnum):
    EMIT = "emit"  # Generate natural language utterance for harness
    SILENT = "silent"  # Internal action, no message on B-line


class MessagePolicy(StrEnum):
    """Action body policy, orthogonal to whether external channel exists."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


class Effect(StrEnum):
    ADVANCE = "advance"  # Advance conversation
    VERIFY = "verify"  # Verify action
    TERMINATE = "terminate"  # Terminate loop


class Phase(StrEnum):
    OPENING = "opening"  # First task not yet issued
    ACTIVE = "active"  # Already has exchanges


@dataclass(frozen=True)
class ActionSpec:
    id: str
    executor: Executor
    channel: Channel
    effect: Effect
    end_reason: str | None = None  # Only TERMINATE action has this
    message_policy: MessagePolicy = MessagePolicy.OPTIONAL


# --------------------------------------------------------------------------
# Action directory (six properties fixed: executor/channel/effect/end_reason/message_policy + id)
# --------------------------------------------------------------------------
CATALOG: dict[str, ActionSpec] = {
    # External interaction with harness is primarily natural language messages; 'verify/read file/run command' are
    # private inner behaviors of the user agent, not outer actions.
    "send_message": ActionSpec(
        "send_message",
        Executor.HARNESS,
        Channel.EMIT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.REQUIRED,
    ),
    # User can also wait without appending new messages like a real CLI, or interrupt harness work still running/queued.
    "keep_waiting": ActionSpec(
        "keep_waiting",
        Executor.PERSONA_LOCAL,
        Channel.SILENT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.FORBIDDEN,
    ),
    "interrupt": ActionSpec(
        "interrupt",
        Executor.HARNESS,
        Channel.SILENT,
        Effect.ADVANCE,
        message_policy=MessagePolicy.FORBIDDEN,
    ),
    # —— Terminate ——
    "accept": ActionSpec(
        "accept",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "accepted",
        message_policy=MessagePolicy.OPTIONAL,
    ),
    # Accept with reservations: deliver as is (end_reason=accepted), and leave an issue in first person about the experiential gap.
    # Decouple 'filing an issue' from 'failed termination'—completed but fell short of expectations, should still voice the experience (model decides whether to pick it).
    "accept_with_reservations": ActionSpec(
        "accept_with_reservations",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "accepted",
        message_policy=MessagePolicy.REQUIRED,
    ),
    "give_up": ActionSpec(
        "give_up",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "abandoned",
        message_policy=MessagePolicy.OPTIONAL,
    ),
    "file_issue": ActionSpec(
        "file_issue",
        Executor.PERSONA_LOCAL,
        Channel.EMIT,
        Effect.TERMINATE,
        "issue_filed",
        message_policy=MessagePolicy.REQUIRED,
    ),
}

TERMINAL_IDS = {aid for aid, s in CATALOG.items() if s.effect is Effect.TERMINATE}


def assert_channel(action_id: str, message: str) -> None:
    """Validate action body policy; optional message on terminate action does not route to harness."""
    spec = CATALOG[action_id]
    msg = (message or "").strip()
    if spec.message_policy is MessagePolicy.REQUIRED and not msg:
        raise ValueError(f"action '{action_id}' requires a non-empty message")
    if spec.message_policy is MessagePolicy.FORBIDDEN and msg:
        raise ValueError(f"action '{action_id}' forbids a message")
