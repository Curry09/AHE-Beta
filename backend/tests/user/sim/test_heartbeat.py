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

    def try_reply(self) -> str | None:
        """非阻塞：脚本下一项若已是 reply，则取出（模拟 LLM 决策期间 reply 已进缓冲）。"""
        if self._pi >= len(self._poll_script):
            return None
        if self._poll_script[self._pi][0] != "reply":
            return None
        _kind, val = self._poll_script[self._pi]
        self._pi += 1
        self._inflight = False
        return str(val)

    def control(self, name: str) -> str:
        self.controls.append(name)
        if name == "interrupt":
            self._inflight = False
            return self.interrupt_reply
        return f"ack:{name}"


class WaitStubClient:
    """分队列：judge / intent / act；每心跳 3 次 respond（Spec-0023 three）。"""

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
    assert _resolve_intent({"intent": "I want to see /status from the manual"}) == (
        "I want to see /status from the manual"
    )
    assert _resolve_intent({"intent": "hang on", "intent_detail": "looks busy"}) == (
        "hang on (looks busy)"
    )
    assert _resolve_intent({}) == "keep waiting"
    assert _resolve_judgment({"judgment": "on_track"}) == "on_track"


def test_three_mode_keep_waiting_logs_and_calls() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting", "gap": False}],
        judging=[{"judgment": "on_track", "perceive": "still working"}],
        intents=[{"intent": "give it more time"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
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
    # 主 decide 的 <history>：统一 [+Ns] 时间轴 + 心跳记忆
    main_prompts = [p for p in client.all_prompts if "<action_space>" in p and "accept" in p]
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
    )
    assert any(s.startswith("WAIT_GAP: intent=I want to know where it is") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert "→keep_waiting]" in waiting[0].perceive


def test_manual_driven_send_message_no_gap() -> None:
    """手册写了 /status → send_message；若决策后仍无现成 reply，则 emit；否则见 abort 测试。"""
    harness = HeartbeatHarness(
        [("pending", 90.0), ("pending", 180.0), ("reply", "done")],
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
    )
    assert harness.emitted == ["/status"]
    assert harness.controls == []
    assert not any(s.startswith("WAIT_GAP:") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert any(t.action == "send_message" and t.message == "/status" for t in waiting)
    assert any(t.phase != "waiting" and t.harness_output == "done" for t in res.turns)


def test_send_message_then_reply_triggers_main_not_nested_wait() -> None:
    """插话成功 emit 后回 AwaitEvent；下一跳若已是 reply 则交主 loop（不再嵌套等待决策）。"""
    harness = HeartbeatHarness(
        [("pending", 60.0), ("pending", 120.0), ("reply", "all done")],
        manual="# Manual\n/btw <msg> is a side question while work continues.\n",
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "send_message", "message": "/btw are you still on pytest?", "gap": False},
            {"action": "keep_waiting", "gap": False},
            {"action": "interrupt", "gap": False},  # 不应被消费
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
        manual=harness.manual,
    )
    assert harness.emitted == ["/btw are you still on pytest?"]
    assert harness.controls == []
    assert len(client.act_prompts) == 2  # send_message + keep_waiting（后者被 reply 抢先 abort）
    assert any(t.action == "send_message" for t in res.turns if t.phase == "waiting")
    assert any(t.phase != "waiting" and t.harness_output == "all done" for t in res.turns)
    assert any(
        "[+60s] waiting:" in p and "send_message" in p and "/btw" in p for p in client.all_prompts
    )


def test_reply_ready_after_heartbeat_aborts_give_up() -> None:
    """心跳 LLM 期间 reply 已进缓冲：动作前检出 → 不作废会话，交主 loop，并写入 history。"""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "arrived while deciding")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "give_up", "gap": False}],
        judging=[{"judgment": "unclear", "perceive": "tired of waiting"}],
        intents=[{"intent": "walk away"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    assert res.end_reason == "accepted"  # 未 abandon
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
        actions=["send_task", "accept"],
        acts=[{"action": "interrupt", "gap": False}],
        judging=[{"judgment": "off_track", "perceive": "wrong"}],
        intents=[{"intent": "Ctrl+C"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    assert harness.controls == []  # 未真正 interrupt
    assert any(
        t.phase != "waiting" and t.harness_output == "done without interrupt" for t in res.turns
    )
    assert any(
        "waiting decision aborted before acting (interrupt)" in p for p in client.all_prompts
    )


def test_keep_waiting_is_one_shot_reply_wakes_main() -> None:
    """keep_waiting 也结束本次心跳；随后 reply 触发主 loop，不会连着再做一次等待决策。"""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "keep_waiting", "gap": False},
            {"action": "interrupt", "gap": False},  # 不应被消费
        ],
        judging=[
            {"judgment": "on_track", "perceive": "still working"},
            {"judgment": "off_track", "perceive": "should not run"},
        ],
        intents=[{"intent": "give it more time"}, {"intent": "stop"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].action == "keep_waiting"
    assert len(client.act_prompts) == 1
    assert harness.controls == []
    assert any(t.phase != "waiting" and t.harness_output == "done at last!" for t in res.turns)
    # 心跳记忆进 history，主 decide 能看见思考+动作+墙钟
    hist_bearing = [p for p in client.all_prompts if "<history>" in p and "<action_space>" in p]
    assert any("[+90s] waiting:" in p and "keep_waiting" in p for p in hist_bearing)


def test_keep_waiting_decay_follows_persona_coef() -> None:
    def _waiting_patience_after_one_keep(d43: D43Correct) -> int:
        harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
        client = WaitStubClient(
            actions=["send_task", "accept"],
            acts=[{"action": "keep_waiting", "gap": False}],
            verdict="satisfied",
        )
        res = run_session(_persona(d43=d43), client, harness, TASK, manual=harness.manual)
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
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
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
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
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
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
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
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].patience == 5
    assert waiting[1].patience == 4
    assert any("WAIT_GAP: intent=I want a progress peek" in s for s in res.signals)


def test_prior_activity_carried() -> None:
    # 第一跳：pending 后脚本下一项即 reply → keep_waiting 动作前 abort，交主 loop。
    # 第二跳：pending 后再 pending（非 reply）→ interrupt 才能真正执行 control。
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
    run_session(_persona(), client, harness, TASK, manual=harness.manual)
    assert len(client.judge_prompts) >= 2
    assert "<prior_activity>" in client.judge_prompts[1]
    assert "rm -rf" in client.judge_prompts[1]
    assert harness.controls == ["interrupt"]
