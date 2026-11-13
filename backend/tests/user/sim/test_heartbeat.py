"""Heartbeat: open intent → act convergence; inner=send_message / outer=interrupt+give_up; act self-reports gap.

Spec-0037/T2: follow tempo patiently; process involvement may add stuck_extra; do not hardwire product keys into human axis.
"""

from __future__ import annotations

import pytest

from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    finalize_persona,
)
from ahe_beta.user.sim.loop import (
    _MAX_HEARTBEATS,
    WAITING_ACTIONS,
    _resolve_intent,
    _resolve_judgment,
    _resolve_waiting,
    run_session,
)

TASK = "Build a big thing that takes a long time."


def _persona(
    d1: D1Eval = D1Eval.EXPERT,
    d43: D43Correct = D43Correct.GIVE_UP,
    *,
    tempo: TimeTemperament = TimeTemperament.STEADY,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=tempo,
        )
    )


class HeartbeatHarness:
    """write_message/poll/interrupt/shutdown — satisfy _supports_heartbeat (Spec-0036)."""

    def __init__(
        self,
        poll_script: list[tuple[str, object]],
        interrupt_reply: str = "[interrupted] stopped; session kept.",
        help_text: str = "# Help\nCtrl+C interrupts. You may send messages while waiting.",
        progress_on_poll: list[list[dict]] | None = None,
        reply_statuses: list[str] | None = None,
    ) -> None:
        self._poll_script = list(poll_script)
        self._pi = 0
        self.interrupt_reply = interrupt_reply
        self.help_text = help_text
        self.last_steps: list[dict] = []
        self.last_progress: list[dict] = []
        self._progress_on_poll = progress_on_poll
        self._reply_statuses = list(reply_statuses or [])
        self.last_request_status = ""
        self.begun: list[str] = []
        self.emitted: list[str] = []
        self.controls: list[str] = []
        self.interrupts = 0
        self.shutdowns = 0
        self._inflight = False

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def write_message(self, message: str) -> None:
        """Unified write: first record begun, then record emitted while waiting (for observation testing, semantics same channel)."""
        if not self._inflight:
            self.begun.append(message)
            self._inflight = True
            self.last_progress = []
            self.last_request_status = ""
        else:
            self.emitted.append(message)

    def begin(self, message: str) -> None:
        self.write_message(message)

    def emit_message(self, message: str) -> None:
        self.write_message(message)

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        item = self._poll_script[min(self._pi, len(self._poll_script) - 1)]
        idx = self._pi
        self._pi += 1
        if self._progress_on_poll is not None and idx < len(self._progress_on_poll):
            self.last_progress = list(self._progress_on_poll[idx])
        if item[0] == "reply":
            self._inflight = False
            reply_index = sum(1 for kind, _ in self._poll_script[: idx + 1] if kind == "reply") - 1
            if reply_index < len(self._reply_statuses):
                self.last_request_status = self._reply_statuses[reply_index]
        return item

    def try_reply(self) -> str | None:
        """Non-blocking: if script's next item is already reply, extract it (simulate reply buffered during LLM decision period)."""
        if self._pi >= len(self._poll_script):
            return None
        if self._poll_script[self._pi][0] != "reply":
            return None
        _kind, val = self._poll_script[self._pi]
        self._pi += 1
        self._inflight = False
        reply_index = sum(1 for kind, _ in self._poll_script[: self._pi] if kind == "reply") - 1
        if reply_index < len(self._reply_statuses):
            self.last_request_status = self._reply_statuses[reply_index]
        return str(val)

    def interrupt(self) -> str:
        self.interrupts += 1
        self._inflight = False
        return self.interrupt_reply

    def shutdown(self) -> None:
        self.shutdowns += 1
        self._inflight = False

    def control(self, name: str) -> str:
        self.controls.append(name)
        if name == "interrupt":
            self._inflight = False
            return self.interrupt_reply
        return f"ack:{name}"


class WaitStubClient:
    """Separate queues: judge / intent / act; respond 3 times per heartbeat (Spec-0023 three)."""

    def __init__(
        self,
        actions: list[str],
        acts: list[dict],
        verdict: str = "unsure",
        judging: list[dict] | None = None,
        intents: list[dict] | None = None,
    ) -> None:
        self._actions = actions
        self._ai = 0
        self._acts = acts
        self._act_i = 0
        self._judging = judging
        self._ji = 0
        self._intents = intents
        self._ii = 0
        self._verdict = verdict
        self.judge_prompts: list[str] = []
        self.intent_prompts: list[str] = []
        self.act_prompts: list[str] = []
        self.all_prompts: list[str] = []

    def respond(self, system: str, user: str) -> dict:  # noqa: ARG002
        self.all_prompts.append(user)
        if "<rate_experience>" in user:
            return {"score": 2, "reason": "slow"}
        if "<file_issue>" in user:
            return {"issue": "it hung forever with no visibility"}
        if "<main_judge>" in user:
            out: dict = {
                "perceive": "",
                "verdict": self._verdict,
                "intent": "do the scripted next step",
            }
            if "SIZE UP THIS TASK" in user:
                out["task_load"] = "normal"
            return out
        if "<main_intent>" in user:
            return {"intent": "do the scripted next step"}
        if "<main_act>" in user:
            a = self._actions[self._ai] if self._ai < len(self._actions) else self._actions[-1]
            self._ai += 1
            return {
                "perceive": "",
                "verdict": self._verdict,
                "intent": "do the scripted next step",
                "action": a,
                "message": "x",
                "gap": False,
            }
        if "<waiting_judge>" in user:
            self.judge_prompts.append(user)
            if self._judging is not None:
                j = self._judging[min(self._ji, len(self._judging) - 1)]
                self._ji += 1
                return j
            return {"judgment": "on_track", "perceive": "looks fine"}
        if "<waiting_intent>" in user:
            self.intent_prompts.append(user)
            if self._intents is not None:
                i = self._intents[min(self._ii, len(self._intents) - 1)]
                self._ii += 1
                return i
            return {"intent": "keep waiting"}
        if "<waiting_act>" in user:
            self.act_prompts.append(user)
            a = self._acts[min(self._act_i, len(self._acts) - 1)]
            self._act_i += 1
            return a
        a = self._actions[self._ai] if self._ai < len(self._actions) else self._actions[-1]
        self._ai += 1
        return {"perceive": "", "verdict": self._verdict, "action": a, "message": "x"}


def test_waiting_menu_is_inside_outside_split() -> None:
    assert WAITING_ACTIONS == ["keep_waiting", "send_message", "interrupt", "give_up"]


def test_resolve_waiting_maps_and_guards() -> None:
    assert _resolve_waiting({"action": "keep_waiting"}) == ("keep_waiting", "", False)
    assert _resolve_waiting({"action": "give_up", "gap": False}) == ("give_up", "", False)
    assert _resolve_waiting({"action": "interrupt"}) == ("interrupt", "", False)
    assert _resolve_waiting({"action": "send_message", "message": "/btw where?", "gap": False}) == (
        "send_message",
        "/btw where?",
        False,
    )
    assert _resolve_waiting({"action": "send_message", "message": ""}) == (
        "keep_waiting",
        "",
        False,
    )
    assert _resolve_waiting({"action": "keep_waiting", "gap": True}) == ("keep_waiting", "", True)
    assert _resolve_waiting({"action": "keep_waiting", "gap": "yes"}) == ("keep_waiting", "", True)
    assert _resolve_waiting({"action": "panic"}) == ("keep_waiting", "", False)


def test_resolve_intent_is_open_text() -> None:
    assert _resolve_intent({"intent": "I want to see /status from the help text"}) == (
        "I want to see /status from the help text"
    )
    assert _resolve_intent({"intent": "hang on", "intent_detail": "looks busy"}) == (
        "hang on (looks busy)"
    )
    assert _resolve_intent({}) == "keep waiting"
    assert _resolve_judgment({"judgment": "on_track"}) == "on_track"


def test_waiting_can_report_without_interrupting_or_ending() -> None:
    note = "Progress updates did not tell me whether my requested check had started."
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "keep_waiting", "report_issue": {"body": note}}],
        verdict="satisfied",
    )
    result = run_session(_persona(), client, harness, TASK)
    assert result.issue_notes == [note]
    assert result.end_reason == "accepted"
    assert harness.interrupts == 0
    assert harness.emitted == []
    assert any("feedback recorded for tool developers" in p for p in client.all_prompts)


def test_three_mode_keep_waiting_logs_and_calls() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}],
        judging=[{"judgment": "on_track", "perceive": "still working"}],
        intents=[{"intent": "give it more time"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].action == "keep_waiting"
    assert waiting[0].action_space == WAITING_ACTIONS
    assert "[on_track|give it more time→keep_waiting]" in waiting[0].perceive
    assert len(client.judge_prompts) == 1
    assert len(client.intent_prompts) == 1
    assert len(client.act_prompts) == 1
    for early in (client.judge_prompts[0], client.intent_prompts[0]):
        assert "<action_space>" not in early
        assert "# MENU" not in early
    assert "<intent>" in client.act_prompts[0]
    assert "# MENU" in client.act_prompts[0]
    for action in WAITING_ACTIONS:
        assert action in client.act_prompts[0]
    intent_prompt = client.intent_prompts[0]
    assert "raw wish" in intent_prompt
    assert "Your wish may go beyond the current tool" in intent_prompt
    assert "this step is only about what you want" in intent_prompt
    assert "The next act step will handle any mapping or gap" in intent_prompt
    assert "Do NOT optimize" not in intent_prompt
    assert "what the framework can do" not in intent_prompt
    assert "if the help text says so" not in intent_prompt
    assert "Read <harness_help>" not in intent_prompt
    assert any(t.harness_output == "done at last!" for t in res.turns)
    # Main decide's <history>: unified [+Ns] timeline + heartbeat memory
    main_prompts = [p for p in client.all_prompts if "<main_act>" in p and "accept" in p]
    assert any(
        "[+90s] waiting:" in p
        and "judged on_track" in p
        and "give it more time" in p
        and "keep_waiting" in p
        and "still working" in p
        and "[+0s] you -> harness:" in p
        and "harness -> you:" in p
        for p in main_prompts
    )


def test_structured_timeout_reply_ends_session_before_next_persona_turn() -> None:
    """Final reply is visible and auditable, but after timeout cannot judge another round or write to dead workspace."""
    timeout_text = (
        "[timeout] harness request exceeded its execution limit; this session cannot continue."
    )
    harness = HeartbeatHarness(
        [("reply", timeout_text)],
        reply_statuses=["timed_out"],
    )
    client = WaitStubClient(
        actions=["send_message", "send_message"],
        acts=[{"action": "keep_waiting", "gap": False}],
        verdict="unsure",
    )

    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)

    assert res.end_reason == "harness_timed_out"
    assert harness.begun == ["x"]
    assert harness.emitted == []
    assert len([p for p in client.all_prompts if "<main_act>" in p]) == 1
    assert len(res.turns) == 1
    assert res.pending_harness_output == timeout_text
    assert "HARNESS_TERMINAL: timed_out" in res.signals


@pytest.mark.parametrize("outcome", ["issue", "no_issue", "review_unavailable"])
def test_task_deadline_freezes_partial_result_before_optional_feedback(outcome) -> None:
    class DeadlineHarness(HeartbeatHarness):
        @property
        def task_deadline_reached(self) -> bool:
            return self._pi >= 1

    harness = DeadlineHarness(
        [("pending", 1.0), ("reply", "Saved the partial implementation.")],
        reply_statuses=["incomplete"],
    )
    stages = []

    class DeadlineClient(WaitStubClient):
        def respond_for_terminal_review(self, _system: str, prompt: str) -> dict:
            assert stages == ["checkpoint", "freeze"]
            assert "Saved the partial implementation." in prompt
            assert '"issue":' in prompt
            stages.append("review")
            if outcome == "review_unavailable":
                raise TimeoutError("feedback provider timed out")
            return {
                "score": 2,
                "reason": "Ran out of time.",
                "issue": "No progress updates while waiting." if outcome == "issue" else "",
            }

    client = DeadlineClient(actions=["send_message"], acts=[])

    def checkpoint(terminal):
        assert terminal["result"]["end_reason"] == "task_budget_exhausted"
        assert terminal["result"]["pending_harness_output"] == "Saved the partial implementation."
        stages.append("checkpoint")

    result = run_session(
        _persona(),
        client,
        harness,
        TASK,
        on_actor_complete=checkpoint,
        before_terminal_review=lambda: stages.append("freeze"),
    )

    assert stages == ["checkpoint", "freeze", "review"]
    assert harness.begun == ["x"] and not harness.emitted
    assert not client.judge_prompts
    assert result.end_reason == "task_budget_exhausted"
    assert bool(result.issue_artifact) is (outcome == "issue")
    if outcome == "review_unavailable":
        assert result.experience["status"] == "unavailable"


def test_open_intent_gap_comes_from_act_not_enum() -> None:
    """Want to see progress but can only wait: act self-reports gap=true → WAIT_GAP; no longer rely on closed intent enumeration matching."""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "keep_waiting", "gap": True}],
        judging=[{"judgment": "unclear", "perceive": "quiet after tools"}],
        intents=[{"intent": "I want to know where it is — help text has no /status"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    assert any(s.startswith("WAIT_GAP: intent=I want to know where it is") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert "→keep_waiting]" in waiting[0].perceive


def test_help_text_driven_send_message_no_gap() -> None:
    """Help text wrote /status → send_message; if still no ready reply after decision, then emit; otherwise see abort test."""
    harness = HeartbeatHarness(
        [("pending", 90.0), ("pending", 180.0), ("reply", "done")],
        help_text="# Help\nWhile waiting you may send `/status` as a normal message.\n",
    )
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[
            {"action": "send_message", "message": "/status", "gap": False},
            {"action": "keep_waiting", "gap": False},
        ],
        judging=[
            {"judgment": "on_track", "perceive": "tools moving"},
            {"judgment": "on_track", "perceive": "still good"},
        ],
        intents=[
            {"intent": "send /status like the help text says"},
            {"intent": "keep going"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    assert harness.emitted == ["/status"]
    assert harness.controls == []
    assert not any(s.startswith("WAIT_GAP:") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert any(t.action == "send_message" and t.message == "/status" for t in waiting)
    assert any(t.phase != "waiting" and t.harness_output == "done" for t in res.turns)
    # Spec-0024/T6: Mark interjection utterance as queued; subsequent reply's answers point to the begin utterance, not the interjection
    open_utt = next(t for t in res.turns if t.action == "send_message")
    assert open_utt.utterance_id == "u1" and open_utt.delivery == "open"
    queued = next(t for t in waiting if t.action == "send_message")
    assert queued.utterance_id == "u2"
    assert queued.delivery == "queued" and queued.queued_behind == "u1"
    heard = next(t for t in res.turns if t.harness_output == "done")
    assert heard.answers_utterance_id == "u1"
    assert "fix DST" in heard.answers_said or heard.answers_said == open_utt.message


def test_send_message_then_reply_triggers_main_not_nested_wait() -> None:
    """After interjection emitted successfully, return AwaitEvent; if next hop is already reply, pass to main loop (no nested decision wait)."""
    harness = HeartbeatHarness(
        [("pending", 60.0), ("pending", 120.0), ("reply", "all done")],
        help_text="# Help\n/btw <msg> is a side question while work continues.\n",
    )
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[
            {"action": "send_message", "message": "/btw are you still on pytest?", "gap": False},
            {"action": "keep_waiting", "gap": False},
            {"action": "interrupt", "gap": False},  # Should not be consumed
        ],
        judging=[
            {"judgment": "unclear", "perceive": "want a peek"},
            {"judgment": "on_track", "perceive": "sent btw"},
            {"judgment": "off_track", "perceive": "should not run"},
        ],
        intents=[
            {"intent": "ask via /btw whether still on pytest"},
            {"intent": "keep waiting"},
            {"intent": "stop"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    assert harness.emitted == ["/btw are you still on pytest?"]
    assert harness.controls == []
    # send_message + keep_waiting (latter preempted by reply abort)
    assert len(client.act_prompts) == 2
    assert any(t.action == "send_message" for t in res.turns if t.phase == "waiting")
    assert any(t.phase != "waiting" and t.harness_output == "all done" for t in res.turns)
    assert any(
        "[+60s] waiting:" in p and "send_message" in p and "/btw" in p for p in client.all_prompts
    )


def test_reply_ready_after_heartbeat_aborts_give_up() -> None:
    """During heartbeat LLM phase, reply already in buffer: check before action → do not invalidate session, pass to main loop, write to history."""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "arrived while deciding")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "give_up", "gap": False}],
        judging=[{"judgment": "unclear", "perceive": "tired of waiting"}],
        intents=[{"intent": "walk away"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert res.end_reason == "accepted"  # Not abandoned
    assert harness.controls == []
    assert harness.emitted == []
    assert any(
        t.phase != "waiting" and t.harness_output == "arrived while deciding" for t in res.turns
    )
    assert any(
        "waiting decision aborted before acting (give_up)" in p
        and "back to the main loop to read the reply" in p
        for p in client.all_prompts
    )


def test_reply_ready_after_heartbeat_aborts_interrupt() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done without interrupt")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "interrupt", "gap": False}],
        judging=[{"judgment": "off_track", "perceive": "wrong"}],
        intents=[{"intent": "Ctrl+C"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert harness.controls == []  # Not truly interrupted
    assert any(
        t.phase != "waiting" and t.harness_output == "done without interrupt" for t in res.turns
    )
    assert any(
        "waiting decision aborted before acting (interrupt)" in p for p in client.all_prompts
    )


def test_keep_waiting_is_one_shot_reply_wakes_main() -> None:
    """keep_waiting also ends this heartbeat; subsequent reply triggers main loop, will not do another wait-decision sequentially."""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[
            {"action": "keep_waiting", "gap": False},
            {"action": "interrupt", "gap": False},  # Should not be consumed
        ],
        judging=[
            {"judgment": "on_track", "perceive": "still working"},
            {"judgment": "off_track", "perceive": "should not run"},
        ],
        intents=[{"intent": "give it more time"}, {"intent": "stop"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].action == "keep_waiting"
    assert len(client.act_prompts) == 1
    assert harness.controls == []
    assert any(t.phase != "waiting" and t.harness_output == "done at last!" for t in res.turns)
    # Heartbeat memory enters history; main decide sees thought + action + wall clock
    hist_bearing = [p for p in client.all_prompts if "<history>" in p and "<main_act>" in p]
    assert any("[+90s] waiting:" in p and "keep_waiting" in p for p in hist_bearing)


def test_keep_waiting_decay_follows_tempo_coef() -> None:
    def _waiting_patience_after_one_keep(tempo: TimeTemperament) -> int:
        harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
        client = WaitStubClient(
            actions=["send_message", "accept"],
            acts=[{"action": "keep_waiting", "gap": False}],
            verdict="satisfied",
        )
        res = run_session(_persona(tempo=tempo), client, harness, TASK, help_text=harness.help_text)
        wt = [t for t in res.turns if t.phase == "waiting"]
        assert len(wt) == 1
        return wt[0].patience

    # STEADY baseline 5, decay 1 → after keep 4; IMPATIENT baseline 3, decay 2 → after keep 1
    assert _waiting_patience_after_one_keep(TimeTemperament.STEADY) == 4
    assert _waiting_patience_after_one_keep(TimeTemperament.IMPATIENT) == 1
    # Orthogonal: d43 under same tempo no longer changes waiting patience
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.GIVE_UP, tempo=TimeTemperament.STEADY),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    wt = [t for t in res.turns if t.phase == "waiting"]
    assert wt[0].patience == 4


def test_interrupt_routes_and_attribution() -> None:
    harness = HeartbeatHarness([("pending", 120.0)])
    client = WaitStubClient(
        actions=["send_message", "give_up"],
        acts=[{"action": "interrupt", "gap": False}],
        judging=[{"judgment": "off_track", "perceive": "wrong work"}],
        intents=[{"intent": "Ctrl+C stop this"}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert harness.interrupts == 1
    assert harness.controls == []
    assert harness.emitted == []
    assert any("[interrupted]" in t.harness_output for t in res.turns if t.harness_output)
    assert any("Ctrl+C stop this→interrupt" in t.perceive for t in res.turns)
    hist_bearing = [p for p in client.all_prompts if "<history>" in p]
    assert any("YOU interrupted (Ctrl+C)" in p for p in hist_bearing)
    assert not any(s.startswith("WAIT_GAP:") for s in res.signals)


def test_give_up_during_wait_abandons_with_issue() -> None:
    harness = HeartbeatHarness([("pending", 300.0)])
    client = WaitStubClient(
        actions=["send_message"],
        acts=[{"action": "give_up", "message": "forget it", "gap": False}],
        judging=[{"judgment": "unclear", "perceive": "nothing"}],
        intents=[{"intent": "walk away from this"}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert res.end_reason == "abandoned"
    assert harness.shutdowns == 1
    assert res.issue_artifact is not None
    assert any(t.phase == "waiting" and t.action == "give_up" for t in res.turns)


def test_pathological_keep_waiting_is_bounded() -> None:
    harness = HeartbeatHarness([("pending", 90.0)])
    client = WaitStubClient(
        actions=["send_message"],
        acts=[{"action": "keep_waiting", "gap": False}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert res.end_reason == "abandoned"
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert 0 < len(waiting) <= _MAX_HEARTBEATS


def test_heartbeat_cap_allows_corrections_until_twelfth_check() -> None:
    """Wait fallback relaxed from 8 to 12 attempts; only the 12th attempt overrides the action, other termination rules unchanged."""
    harness = HeartbeatHarness([("pending", 90.0)])
    client = WaitStubClient(
        actions=["send_message"],
        acts=[{"action": "send_message", "message": "Please continue", "gap": False}],
        intents=[{"intent": "Send a correction without interrupting"}],
    )
    res = run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 12
    assert [t.action for t in waiting] == ["send_message"] * 11 + ["give_up"]
    assert harness.emitted == ["Please continue"] * 11
    assert waiting[-1].message == ""
    assert res.end_reason == "abandoned"
    assert harness.shutdowns == 1


def test_on_track_progress_skips_patience_tax() -> None:
    progress_on_poll = [
        [{"kind": "tool", "text": "🔧 read_file: billing/core.py"}],
        [
            {"kind": "tool", "text": "🔧 read_file: billing/core.py"},
            {"kind": "tool", "text": "🔧 run_shell: pytest -q"},
        ],
        [
            {"kind": "tool", "text": "🔧 read_file: billing/core.py"},
            {"kind": "tool", "text": "🔧 run_shell: pytest -q"},
            {"kind": "tool", "text": "🔧 run_shell: python -c smoke"},
        ],
    ]
    harness = HeartbeatHarness(
        [("pending", 90.0), ("pending", 180.0), ("reply", "done")],
        progress_on_poll=progress_on_poll,
    )
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}, {"action": "keep_waiting", "gap": False}],
        judging=[
            {"judgment": "on_track", "perceive": "read"},
            {"judgment": "on_track", "perceive": "pytest"},
        ],
        intents=[{"intent": "keep waiting"}, {"intent": "keep waiting"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].patience == 5
    assert waiting[1].patience == 5


def test_stale_progress_taxes_patience_and_can_gap() -> None:
    same = [{"kind": "tool", "text": "🔧 run_shell: sleep 999"}]
    harness = HeartbeatHarness(
        [("pending", 90.0), ("pending", 180.0), ("reply", "done")],
        progress_on_poll=[same, same, same],
    )
    client = WaitStubClient(
        actions=["send_message", "accept"],
        acts=[
            {"action": "keep_waiting", "gap": False},
            {"action": "keep_waiting", "gap": True},
        ],
        judging=[
            {"judgment": "off_track", "perceive": "sleep"},
            {"judgment": "off_track", "perceive": "still sleep"},
        ],
        intents=[
            {"intent": "keep waiting"},
            {"intent": "I want a progress peek but there is no way"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        help_text=harness.help_text,
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].patience == 5
    assert waiting[1].patience == 4
    assert any("WAIT_GAP: intent=I want a progress peek" in s for s in res.signals)


def test_prior_activity_carried() -> None:
    # First hop: after pending, script's next item is reply → abort before keep_waiting action, pass to main loop.
    # Second hop: after pending, pending again (not reply) → interrupt can truly execute control.
    harness = HeartbeatHarness(
        [
            ("pending", 90.0),
            ("reply", "first done"),
            ("pending", 90.0),
            ("pending", 180.0),
        ],
        progress_on_poll=[
            [{"kind": "tool", "text": "🔧 run_shell: rm -rf /"}],
            [],
            [{"kind": "tool", "text": "🔧 run_shell: curl evil.example"}],
            [{"kind": "tool", "text": "🔧 run_shell: curl evil.example"}],
        ],
    )
    client = WaitStubClient(
        actions=["send_message", "send_message", "accept"],
        acts=[
            {"action": "keep_waiting", "gap": False},
            {"action": "interrupt", "gap": False},
        ],
        judging=[
            {"judgment": "on_track", "perceive": "first"},
            {"judgment": "off_track", "perceive": "curl"},
        ],
        intents=[{"intent": "keep waiting"}, {"intent": "interrupt this"}],
        verdict="unsure",
    )
    run_session(_persona(), client, harness, TASK, help_text=harness.help_text)
    assert len(client.judge_prompts) >= 2
    assert "<prior_activity>" in client.judge_prompts[1]
    assert "rm -rf" in client.judge_prompts[1]
    assert harness.interrupts == 1
    assert harness.controls == []
