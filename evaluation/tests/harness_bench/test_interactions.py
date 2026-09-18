from __future__ import annotations

from evaluation.harness_bench.harness.protocol import HarnessEvent, HarnessReply, TerminalKind
from evaluation.harness_bench.interactions.base import UserAction, UserActionKind
from evaluation.harness_bench.interactions.direct import DirectInteraction
from evaluation.harness_bench.interactions.simulated_user import SimulatedUserInteraction


def reply(text: str = "done") -> HarnessReply:
    return HarnessReply(text, TerminalKind.NORMAL, (HarnessEvent("reply", {"text": text}),), 1)


class FakeSession:
    def __init__(self, polls):
        self.polls = list(polls)
        self.messages = []
        self.last_progress = [{"type": "progress", "text": "working"}]
        self.ready = None

    def write_message(self, message):
        self.messages.append(message)

    def poll(self, timeout):
        return self.polls.pop(0)

    def try_reply(self):
        value, self.ready = self.ready, None
        return value

    def interrupt(self, timeout=30):
        return None


class SequencePolicy:
    def __init__(self, actions):
        self.actions = list(actions)
        self.observations = []

    def decide(self, observation):
        self.observations.append(observation)
        return self.actions.pop(0)


def test_direct_sends_exactly_one_message() -> None:
    session = FakeSession([("reply", reply())])
    result = DirectInteraction().run(session, "task", 30)

    assert session.messages == ["task"]
    assert result.normal_final_reply


def test_simulated_user_can_send_during_heartbeat_then_accept() -> None:
    session = FakeSession([("timer", 1.0), ("reply", reply())])
    policy = SequencePolicy(
        [
            UserAction(UserActionKind.SEND_MESSAGE, "please verify"),
            UserAction(UserActionKind.ACCEPT),
        ]
    )
    result = SimulatedUserInteraction(policy, heartbeat_seconds=1, max_turns=4).run(
        session, "task", 30
    )

    assert session.messages == ["task", "please verify"]
    assert result.end_reason == "user_accept"
    assert result.user_actions[0]["phase"] == "waiting"


def test_reply_arriving_during_heartbeat_cancels_stale_action() -> None:
    session = FakeSession([("timer", 1.0)])
    session.ready = reply("already done")
    policy = SequencePolicy(
        [
            UserAction(UserActionKind.SEND_MESSAGE, "stale request"),
            UserAction(UserActionKind.ACCEPT),
        ]
    )
    result = SimulatedUserInteraction(policy, heartbeat_seconds=1).run(session, "task", 30)

    assert session.messages == ["task"]
    assert result.user_actions[0]["stale"] is True
    assert result.end_reason == "user_accept"
