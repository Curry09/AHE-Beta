"""Heartbeat-supervised LLM user that can act while Harness work is in flight."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from typing import Any
from urllib.request import Request, urlopen

from ..harness.protocol import HarnessReply, TerminalKind
from .base import (
    InteractionResult,
    UserAction,
    UserActionKind,
    UserObservation,
    UserPolicy,
)


class OpenAICompatibleUserPolicy:
    """Small JSON action policy; it never receives grader-private information."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        persona: str,
        seed: int,
        temperature: float = 0.0,
        request_timeout_seconds: float = 120.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.persona = persona
        self.seed = seed
        self.temperature = temperature
        self.request_timeout_seconds = request_timeout_seconds
        self.calls: list[dict[str, Any]] = []

    def decide(self, observation: UserObservation) -> UserAction:
        allowed = (
            ["keep_waiting", "send_message", "interrupt", "give_up"]
            if observation.phase == "waiting"
            else ["send_message", "accept", "give_up"]
        )
        prompt = {
            "persona": self.persona,
            "phase": observation.phase,
            "task": observation.task,
            "history": list(observation.history),
            "visible_progress": list(observation.progress),
            "elapsed_seconds": observation.elapsed_seconds,
            "remaining_seconds": observation.remaining_seconds,
            "assistant_reply": observation.reply.text if observation.reply else None,
            "help": observation.help_text,
            "allowed_actions": allowed,
            "instruction": (
                "Choose one allowed action as JSON: "
                '{"action":"...","message":"only for send_message","rationale":"short"}. '
                "Act only on public conversation evidence; do not invent hidden tests."
            ),
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You simulate the task user and must return one JSON action.",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.temperature,
            "seed": self.seed,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        with urlopen(request, timeout=self.request_timeout_seconds) as response:
            raw = json.load(response)
        content = raw["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        action_text = str(parsed.get("action", ""))
        if action_text not in allowed:
            raise ValueError(f"user policy returned disallowed action: {action_text}")
        action = UserAction(
            kind=UserActionKind(action_text),
            message=str(parsed.get("message") or "").strip(),
            rationale=str(parsed.get("rationale") or "").strip(),
        )
        self.calls.append(
            {
                "observation": prompt,
                "action": asdict(action),
                "usage": raw.get("usage", {}),
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        return action


class SimulatedUserInteraction:
    def __init__(
        self,
        policy: UserPolicy,
        *,
        heartbeat_seconds: float = 90.0,
        max_turns: int = 40,
        max_heartbeats: int | None = None,
        help_text: str = "",
    ) -> None:
        if heartbeat_seconds <= 0 or max_turns <= 0:
            raise ValueError("heartbeat_seconds and max_turns must be positive")
        self.policy = policy
        self.heartbeat_seconds = heartbeat_seconds
        self.max_turns = max_turns
        self.max_heartbeats = max_heartbeats
        self.help_text = help_text

    def run(self, session, task: str, timeout_seconds: float) -> InteractionResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        started = time.monotonic()
        deadline = started + timeout_seconds
        heartbeat_limit = (
            self.max_heartbeats or math.ceil(timeout_seconds / self.heartbeat_seconds) + 1
        )
        result = InteractionResult(end_reason="evaluator_deadline")
        history: list[dict[str, Any]] = [{"role": "user", "content": task}]
        session.write_message(task)
        user_turns = 1
        heartbeats = 0

        def remaining() -> float:
            return deadline - time.monotonic()

        def record_action(action: UserAction, phase: str, *, stale: bool = False) -> None:
            result.user_actions.append(
                {
                    "phase": phase,
                    "kind": action.kind.value,
                    "message": action.message,
                    "rationale": action.rationale,
                    "stale": stale,
                    "elapsed_seconds": time.monotonic() - started,
                }
            )

        pending_reply: HarnessReply | None = None
        while remaining() > 0:
            if pending_reply is None:
                kind, value = session.poll(min(self.heartbeat_seconds, remaining()))
                if kind == "reply":
                    pending_reply = value
                else:
                    heartbeats += 1
                    if heartbeats > heartbeat_limit:
                        result.end_reason = "user_give_up_heartbeat_limit"
                        break
                    observation = UserObservation(
                        phase="waiting",
                        task=task,
                        history=tuple(history),
                        progress=tuple(session.last_progress),
                        elapsed_seconds=time.monotonic() - started,
                        remaining_seconds=max(0.0, remaining()),
                        help_text=self.help_text,
                    )
                    action = self.policy.decide(observation)
                    ready = session.try_reply()
                    if ready is not None:
                        record_action(action, "waiting", stale=True)
                        pending_reply = ready
                        continue
                    record_action(action, "waiting")
                    if action.kind is UserActionKind.KEEP_WAITING:
                        continue
                    if action.kind is UserActionKind.SEND_MESSAGE:
                        session.write_message(action.message)
                        history.append({"role": "user", "content": action.message})
                        user_turns += 1
                        continue
                    if action.kind is UserActionKind.INTERRUPT:
                        interrupt_budget = remaining()
                        if interrupt_budget <= 0:
                            result.end_reason = "evaluator_deadline"
                            break
                        interrupted = session.interrupt(timeout=min(30.0, interrupt_budget))
                        if interrupted is not None:
                            result.replies.append(interrupted)
                        result.end_reason = "user_interrupt"
                        break
                    result.end_reason = "user_give_up"
                    break

            if pending_reply is None:
                continue
            reply = pending_reply
            pending_reply = None
            result.replies.append(reply)
            history.append({"role": "assistant", "content": reply.text})
            if reply.terminal_kind is not TerminalKind.NORMAL:
                result.end_reason = f"harness_{reply.terminal_kind.value}"
                break
            if user_turns >= self.max_turns:
                result.end_reason = "max_turns"
                break
            action = self.policy.decide(
                UserObservation(
                    phase="reply",
                    task=task,
                    history=tuple(history),
                    progress=tuple(session.last_progress),
                    elapsed_seconds=time.monotonic() - started,
                    remaining_seconds=max(0.0, remaining()),
                    reply=reply,
                    help_text=self.help_text,
                )
            )
            record_action(action, "reply")
            if action.kind is UserActionKind.ACCEPT:
                result.end_reason = "user_accept"
                result.normal_final_reply = True
                break
            if action.kind is UserActionKind.GIVE_UP:
                result.end_reason = "user_give_up"
                break
            if action.kind is not UserActionKind.SEND_MESSAGE:
                raise ValueError(f"invalid reply-phase action: {action.kind}")
            session.write_message(action.message)
            history.append({"role": "user", "content": action.message})
            user_turns += 1

        result.elapsed_seconds = time.monotonic() - started
        result.progress = list(session.last_progress)
        return result
