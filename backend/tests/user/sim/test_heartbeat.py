"""心跳：开放 intent → act 收敛；内=send_message / 外=interrupt+give_up；act 自报 gap。"""

from __future__ import annotations

from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from auto_designer.user.sim.loop import (
    _MAX_HEARTBEATS,
    WAITING_ACTIONS,
    _resolve_intent,
    _resolve_judgment,
    _resolve_waiting,
    run_session,
)

TASK = "Build a big thing that takes a long time."


def _persona(d1: D1Eval = D1Eval.EXPERT, d43: D43Correct = D43Correct.GIVE_UP) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


class HeartbeatHarness:
    """begin/poll/control/emit_message —— 满足 _supports_heartbeat。"""

    def __init__(
        self,
        poll_script: list[tuple[str, object]],
        interrupt_reply: str = "[interrupted] stopped; session kept.",
        manual: str = "# Manual\nCtrl+C interrupts. You may send messages while waiting.",
        progress_on_poll: list[list[dict]] | None = None,
    ) -> None:
        self._poll_script = list(poll_script)
        self._pi = 0
        self.interrupt_reply = interrupt_reply
        self.manual = manual
        self.last_steps: list[dict] = []
        self.last_progress: list[dict] = []
        self._progress_on_poll = progress_on_poll
        self.begun: list[str] = []
        self.emitted: list[str] = []
        self.controls: list[str] = []
        self._inflight = False

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def begin(self, message: str) -> None:
        self.begun.append(message)
        self._inflight = True
        self.last_progress = []

    def emit_message(self, message: str) -> None:
        if not self._inflight:
            raise RuntimeError("not in flight")
        self.emitted.append(message)

    def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
        item = self._poll_script[min(self._pi, len(self._poll_script) - 1)]
        idx = self._pi
        self._pi += 1
        if self._progress_on_poll is not None and idx < len(self._progress_on_poll):
            self.last_progress = list(self._progress_on_poll[idx])
        if item[0] == "reply":
            self._inflight = False
        return item

    def control(self, name: str) -> str:
        self.controls.append(name)
        if name == "interrupt":
            self._inflight = False
            return self.interrupt_reply
        return f"ack:{name}"


class WaitStubClient:
    """分队列：judge / intent / judge_intent / act；默认 three 模式每心跳 3 次 respond。"""

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
        self.judge_intent_prompts: list[str] = []
        self.act_prompts: list[str] = []
        self.all_prompts: list[str] = []

    def respond(self, system: str, user: str) -> dict:  # noqa: ARG002
        self.all_prompts.append(user)
        if "<rate_experience>" in user:
            return {"score": 2, "reason": "slow"}
        if "<file_issue>" in user:
            return {"issue": "it hung forever with no visibility"}
        if "<waiting_judge_intent>" in user:
            self.judge_intent_prompts.append(user)
            j = (
                self._judging[min(self._ji, len(self._judging) - 1)]
                if self._judging is not None
                else {"judgment": "on_track", "perceive": "ok"}
            )
            if self._judging is not None:
                self._ji += 1
            i = (
                self._intents[min(self._ii, len(self._intents) - 1)]
                if self._intents is not None
                else {"intent": "keep waiting"}
            )
            if self._intents is not None:
                self._ii += 1
            return {
                "perceive": j.get("perceive", ""),
                "judgment": j.get("judgment", "on_track"),
                "intent": i.get("intent", "keep waiting"),
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
    assert _resolve_intent({"intent": "I want to see /status from the manual"}) == (
        "I want to see /status from the manual"
    )
    assert _resolve_intent({"intent": "hang on", "intent_detail": "looks busy"}) == (
        "hang on (looks busy)"
    )
    assert _resolve_intent({}) == "keep waiting"
    assert _resolve_judgment({"judgment": "on_track"}) == "on_track"
    assert _resolve_judgment({"judgment": "stalled"}) == "unclear"


def test_three_mode_keep_waiting_logs_and_calls() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}],
        judging=[{"judgment": "on_track", "perceive": "still working"}],
        intents=[{"intent": "give it more time"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].action == "keep_waiting"
    assert waiting[0].action_space == WAITING_ACTIONS
    assert "[on_track|give it more time→keep_waiting]" in waiting[0].perceive
    assert len(client.judge_prompts) == 1
    assert len(client.intent_prompts) == 1
    assert len(client.act_prompts) == 1
    assert "<intent>" in client.act_prompts[0]
    assert "free-text" in client.intent_prompts[0] or "own words" in client.intent_prompts[0]
    assert any(t.harness_output == "done at last!" for t in res.turns)


def test_two_mode_judge_intent_combined() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}],
        judging=[{"judgment": "on_track", "perceive": "ok"}],
        intents=[{"intent": "keep waiting a bit"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual, waiting_mode="two")
    assert len(client.judge_intent_prompts) == 1
    assert len(client.judge_prompts) == 0
    assert len(client.intent_prompts) == 0
    assert len(client.act_prompts) == 1
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].perceive.startswith("[on_track|keep waiting a bit→")


def test_open_intent_gap_comes_from_act_not_enum() -> None:
    """想看进度却只能干等：act 自报 gap=true → WAIT_GAP；不再靠封闭 intent 枚举对表。"""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting", "gap": True}],
        judging=[{"judgment": "unclear", "perceive": "quiet after tools"}],
        intents=[{"intent": "I want to know where it is — manual has no /status"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        manual=harness.manual,
        waiting_mode="three",
    )
    assert any(s.startswith("WAIT_GAP: intent=I want to know where it is") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert "→keep_waiting]" in waiting[0].perceive


def test_manual_driven_send_message_no_gap() -> None:
    """手册写了 /status → intent 想看进度 → act send_message + gap=false。"""
    harness = HeartbeatHarness(
        [("pending", 90.0), ("reply", "done")],
        manual="# Manual\nWhile waiting you may send `/status` as a normal message.\n",
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "send_message", "message": "/status", "gap": False},
            {"action": "keep_waiting", "gap": False},
        ],
        judging=[
            {"judgment": "on_track", "perceive": "tools moving"},
            {"judgment": "on_track", "perceive": "still good"},
        ],
        intents=[
            {"intent": "send /status like the manual says"},
            {"intent": "keep going"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        manual=harness.manual,
        waiting_mode="three",
    )
    assert harness.emitted == ["/status"]
    assert harness.controls == []
    assert not any(s.startswith("WAIT_GAP:") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert any("→send_message]" in t.perceive for t in waiting)
    assert any(t.action == "send_message" and t.message == "/status" for t in waiting)


def test_midflight_send_message_continues_wait_then_final_reply() -> None:
    harness = HeartbeatHarness(
        [("pending", 60.0), ("reply", "all done")],
        manual="# Manual\n/btw <msg> is a side question while work continues.\n",
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "send_message", "message": "/btw are you still on pytest?", "gap": False},
            {"action": "keep_waiting", "gap": False},
        ],
        judging=[
            {"judgment": "unclear", "perceive": "want a peek"},
            {"judgment": "on_track", "perceive": "sent btw, keep going"},
        ],
        intents=[
            {"intent": "ask via /btw whether still on pytest"},
            {"intent": "keep waiting"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK),
        client,
        harness,
        TASK,
        manual=harness.manual,
        waiting_mode="three",
    )
    assert harness.emitted == ["/btw are you still on pytest?"]
    assert harness.controls == []
    assert any(t.harness_output == "all done" for t in res.turns)
    assert not any("YOU interrupted" in p for p in client.all_prompts)
    assert any(
        "sent another message while it was still running" in p and "/btw" in p
        for p in client.all_prompts
    )


def test_keep_waiting_decay_follows_persona_coef() -> None:
    def _waiting_patience_after_one_keep(d43: D43Correct) -> int:
        harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
        client = WaitStubClient(
            actions=["send_task", "accept"],
            acts=[{"action": "keep_waiting", "gap": False}],
            verdict="satisfied",
        )
        res = run_session(
            _persona(d43=d43), client, harness, TASK, manual=harness.manual, waiting_mode="three"
        )
        wt = [t for t in res.turns if t.phase == "waiting"]
        assert len(wt) == 1
        return wt[0].patience

    assert _waiting_patience_after_one_keep(D43Correct.FEEDBACK) == 4
    assert _waiting_patience_after_one_keep(D43Correct.GIVE_UP) == 1


def test_interrupt_routes_and_attribution() -> None:
    harness = HeartbeatHarness([("pending", 120.0)])
    client = WaitStubClient(
        actions=["send_task", "give_up"],
        acts=[{"action": "interrupt", "gap": False}],
        judging=[{"judgment": "off_track", "perceive": "wrong work"}],
        intents=[{"intent": "Ctrl+C stop this"}],
        verdict="stuck",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    assert harness.controls == ["interrupt"]
    assert harness.emitted == []
    assert any("[interrupted]" in t.harness_output for t in res.turns if t.harness_output)
    assert any("Ctrl+C stop this→interrupt" in t.perceive for t in res.turns)
    hist_bearing = [p for p in client.all_prompts if "<history>" in p]
    assert any("YOU interrupted (Ctrl+C)" in p for p in hist_bearing)
    assert not any(s.startswith("WAIT_GAP:") for s in res.signals)


def test_give_up_during_wait_abandons_with_issue() -> None:
    harness = HeartbeatHarness([("pending", 300.0)])
    client = WaitStubClient(
        actions=["send_task"],
        acts=[{"action": "give_up", "message": "forget it", "gap": False}],
        judging=[{"judgment": "unclear", "perceive": "nothing"}],
        intents=[{"intent": "walk away from this"}],
        verdict="stuck",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    assert res.end_reason == "abandoned"
    assert res.issue_artifact is not None
    assert any(t.phase == "waiting" and t.action == "give_up" for t in res.turns)


def test_pathological_keep_waiting_is_bounded() -> None:
    harness = HeartbeatHarness([("pending", 90.0)])
    client = WaitStubClient(
        actions=["send_task"],
        acts=[{"action": "keep_waiting", "gap": False}],
        verdict="stuck",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    assert res.end_reason == "abandoned"
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert 0 < len(waiting) <= _MAX_HEARTBEATS


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
        actions=["send_task", "accept"],
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
        manual=harness.manual,
        waiting_mode="three",
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
        actions=["send_task", "accept"],
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
        manual=harness.manual,
        waiting_mode="three",
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].patience == 5
    assert waiting[1].patience == 4
    assert any("WAIT_GAP: intent=I want a progress peek" in s for s in res.signals)


def test_prior_activity_carried() -> None:
    harness = HeartbeatHarness(
        [
            ("pending", 90.0),
            ("reply", "first done"),
            ("pending", 90.0),
            ("reply", "second done"),
        ],
        progress_on_poll=[
            [{"kind": "tool", "text": "🔧 run_shell: rm -rf /"}],
            [{"kind": "tool", "text": "🔧 run_shell: rm -rf /"}],
            [{"kind": "tool", "text": "🔧 run_shell: curl evil.example"}],
            [{"kind": "tool", "text": "🔧 run_shell: curl evil.example"}],
        ],
    )
    client = WaitStubClient(
        actions=["send_task", "ask_harness_run", "accept"],
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
    run_session(_persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three")
    assert len(client.judge_prompts) >= 2
    assert "<prior_activity>" in client.judge_prompts[1]
    assert "rm -rf" in client.judge_prompts[1]
    assert harness.controls == ["interrupt"]
