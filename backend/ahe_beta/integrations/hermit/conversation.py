"""Adapt a host-owned conversation to the existing simulated-user interface."""

from __future__ import annotations

import time

from ahe_beta.user.sim.runtime import utc_now


class ConversationHandle:
    execution_record_source = "host_conversation"
    help_text = (
        "Send a message or follow-up, insert guidance while the agent works, or interrupt "
        "at its next tool boundary. Interrupt does not cancel a tool already running. "
        "Ending the session stops the agent and its children before final review."
    )

    def __init__(self, conversation):
        self.conversation = conversation
        self.in_flight = False
        self.last_progress = []
        self._started_at = time.monotonic()
        self.last_steps = []
        self.last_request_status = ""
        self.request_outcomes = []
        self._visible = []
        self.visible_events = []
        self._request = None
        self._used = False

    def reset(self):
        if self._used:
            raise RuntimeError("a host conversation cannot be reused for another session")
        self._used = True

    def write_message(self, message):
        if not self.in_flight:
            self.last_steps = []
            self.last_progress = []
            self._started_at = time.monotonic()
            self._request = {
                "request_id": str(len(self.request_outcomes) + 1),
                "started_at": utc_now(),
            }
        self.conversation.write(message)
        self.in_flight = True

    def _read_events(self):
        for event in self.conversation.events():
            self._visible.append(dict(event))
            self.visible_events.append(dict(event))
            if event.get("kind") in {"tool_start", "tool", "denied"}:
                step = {
                    "kind": "tool" if event["kind"] == "tool" else "progress",
                    "name": event.get("tool", ""),
                    "input": event.get("input", ""),
                    "output": event.get("output", ""),
                }
                self.last_steps.append(step)
                self.last_progress.append(
                    {"kind": event["kind"], "text": str(event.get("tool") or event["kind"])}
                )

    def poll(self, timeout=0.0):
        try:
            reply = self.conversation.poll(timeout)
        except Exception:
            self.last_request_status = "crashed"
            self.in_flight = False
            self.request_outcomes.append(
                {
                    **(self._request or {}),
                    "status": "crashed",
                    "finished_at": utc_now(),
                    "termination_reason": "host_exit",
                }
            )
            self._request = None
            self._read_events()
            raise
        self._read_events()
        if reply is None:
            return ("pending", time.monotonic() - self._started_at)
        self.in_flight = False
        self.last_request_status = "interrupted" if reply.get("interrupted") else "completed"
        self.request_outcomes.append(
            {
                **(self._request or {}),
                "status": self.last_request_status,
                "finished_at": utc_now(),
                "termination_reason": self.last_request_status,
            }
        )
        self._request = None
        return ("reply", str(reply.get("text") or ""))

    def try_reply(self):
        kind, value = self.poll(0.0)
        return value if kind == "reply" else None

    def send(self, message):
        self.write_message(message)
        while True:
            kind, value = self.poll(1.0)
            if kind == "reply":
                return value

    def drain_visible_events(self):
        self._read_events()
        events, self._visible = self._visible, []
        return events

    def control(self, action):
        if action != "interrupt":
            raise ValueError(f"unsupported conversation control: {action}")
        self.conversation.interrupt(timeout=0.0)
        return None

    def shutdown(self):
        self.close()

    def close(self):
        self.conversation.close()
        if self.in_flight:
            self.request_outcomes.append(
                {
                    **(self._request or {}),
                    "status": "interrupted",
                    "finished_at": utc_now(),
                    "termination_reason": "session_ended",
                }
            )
            self.in_flight = False
