"""心跳：judge/intent/act（2 跳或 3 跳）+ gap 信号。"""

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
    _intent_has_gap,
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
    def __init__(
        self,
        poll_script: list[tuple[str, object]],
        control_reply: str = "[interrupted] stopped; session kept.",
        manual: str = "# Manual\nYou can interrupt a running request.",
        progress_on_poll: list[list[dict]] | None = None,
        sideband_controls: frozenset[str] | None = None,
    ) -> None:
        self._poll_script = list(poll_script)
        self._pi = 0
        self.control_reply = control_reply
        self.manual = manual
        self.last_steps: list[dict] = []
        self.last_progress: list[dict] = []
        self._progress_on_poll = progress_on_poll
        self.begun: list[str] = []
        self.controls: list[str] = []
        self._inflight = False
        # 旁路型控制（peek/status）：不结束本轮；其余（interrupt）结束。
        self._sideband_controls = (
            frozenset({"status", "peek"}) if sideband_controls is None else sideband_controls
        )

    @property
    def in_flight(self) -> bool:
        return self._inflight

    def begin(self, message: str) -> None:
        self.begun.append(message)
        self._inflight = True
        self.last_progress = []

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
        if name in self._sideband_controls:
            out = self.control_reply
            self.last_progress = [
                *self.last_progress,
                {"kind": "status", "text": out.splitlines()[0][:200]},
            ]
            return out  # 保持 in_flight
        self._inflight = False
        return self.control_reply


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
                else {"intent": "keep_waiting"}
            )
            if self._intents is not None:
                self._ii += 1
            return {
                "perceive": j.get("perceive", ""),
                "judgment": j.get("judgment", "on_track"),
                "intent": i.get("intent", "keep_waiting"),
                "intent_detail": i.get("intent_detail", ""),
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
            return {"intent": "keep_waiting", "intent_detail": ""}
        if "<waiting_act>" in user:
            self.act_prompts.append(user)
            a = self._acts[min(self._act_i, len(self._acts) - 1)]
            self._act_i += 1
            return a
        a = self._actions[self._ai] if self._ai < len(self._actions) else self._actions[-1]
        self._ai += 1
        return {"perceive": "", "verdict": self._verdict, "action": a, "message": "x"}


def test_resolve_waiting_maps_and_guards() -> None:
    assert _resolve_waiting({"action": "keep_waiting"}) == ("keep_waiting", "")
    assert _resolve_waiting({"action": "give_up"}) == ("give_up", "")
    assert _resolve_waiting({"action": "invoke_control", "control": "interrupt"}) == (
        "invoke_control",
        "interrupt",
    )
    assert _resolve_waiting({"action": "invoke_control", "control": ""}) == ("keep_waiting", "")
    assert _resolve_waiting({"action": "panic"}) == ("keep_waiting", "")


def test_resolve_judgment_and_intent() -> None:
    assert _resolve_judgment({"judgment": "on_track"}) == "on_track"
    assert _resolve_judgment({"judgment": "OFF-TRACK"}) == "off_track"
    assert _resolve_judgment({"judgment": "stalled"}) == "unclear"  # 旧标签降级
    assert _resolve_judgment({}) == "unclear"
    assert _resolve_intent({"intent": "check_status", "intent_detail": "peek"}) == (
        "check_status",
        "peek",
    )
    assert _resolve_intent({}) == ("keep_waiting", "")
    assert _intent_has_gap("check_status", "keep_waiting") is True
    assert _intent_has_gap("check_status", "invoke_control") is False
    assert _intent_has_gap("interrupt", "invoke_control") is False
    assert _intent_has_gap("keep_waiting", "keep_waiting") is False


def test_three_mode_keep_waiting_logs_and_calls() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting"}],
        judging=[{"judgment": "on_track", "perceive": "still working"}],
        intents=[{"intent": "keep_waiting", "intent_detail": "fine"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 1
    assert waiting[0].action == "keep_waiting"
    assert waiting[0].action_space == WAITING_ACTIONS
    assert "[on_track|keep_waiting→keep_waiting]" in waiting[0].perceive
    assert len(client.judge_prompts) == 1
    assert len(client.intent_prompts) == 1
    assert len(client.act_prompts) == 1
    assert "<intent>" in client.act_prompts[0]
    assert any(t.harness_output == "done at last!" for t in res.turns)


def test_two_mode_judge_intent_combined() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting"}],
        judging=[{"judgment": "on_track", "perceive": "ok"}],
        intents=[{"intent": "keep_waiting"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual, waiting_mode="two")
    assert len(client.judge_intent_prompts) == 1
    assert len(client.judge_prompts) == 0
    assert len(client.intent_prompts) == 0
    assert len(client.act_prompts) == 1
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert waiting[0].perceive.startswith("[on_track|keep_waiting→")


def test_check_status_intent_records_gap() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting"}],
        judging=[{"judgment": "unclear", "perceive": "quiet after tools"}],
        intents=[{"intent": "check_status", "intent_detail": "where is it"}],
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
    assert any(s.startswith("WAIT_GAP: intent=check_status") for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert "check_status→keep_waiting" in waiting[0].perceive


def test_check_status_via_invoke_control_has_no_gap() -> None:
    """手册有 status 时，check_status → invoke_control:status 算兑到，不记 WAIT_GAP。"""
    harness = HeartbeatHarness(
        [("pending", 90.0), ("reply", "done")],
        control_reply="phase=running; elapsed=1",
        manual='# Manual\nSend {"control":"status"} to peek.\n',
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "invoke_control", "control": "status"},
            {"action": "keep_waiting"},
        ],
        judging=[
            {"judgment": "on_track", "perceive": "tools moving"},
            {"judgment": "on_track", "perceive": "status looks fine"},
        ],
        intents=[
            {"intent": "check_status", "intent_detail": "peek"},
            {"intent": "keep_waiting", "intent_detail": "ok keep going"},
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
    assert harness.controls == ["status"]
    assert not any("WAIT_GAP: intent=check_status" in s for s in res.signals)
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert any("check_status→invoke_control:status" in t.perceive for t in waiting)
    assert any("keep_waiting→keep_waiting" in t.perceive for t in waiting)


def test_status_peek_continues_wait_then_final_reply() -> None:
    """旁路 status：不结束本轮、不记 YOU stopped；写入上下文后再决策；终态仍是正常 reply。"""
    harness = HeartbeatHarness(
        [("pending", 60.0), ("reply", "all done")],
        control_reply="phase=running; step=pytest",
        manual='# Manual\n{"control":"status"} peeks; {"control":"interrupt"} stops.\n',
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[
            {"action": "invoke_control", "control": "status"},
            {"action": "keep_waiting"},
        ],
        judging=[
            {"judgment": "unclear", "perceive": "want a peek"},
            {"judgment": "on_track", "perceive": "saw status, still good"},
        ],
        intents=[
            {"intent": "check_status"},
            {"intent": "keep_waiting"},
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
    assert harness.controls == ["status"]
    assert any(t.harness_output == "all done" for t in res.turns)
    # peek 不得记成「你停了请求」
    assert not any(
        "YOU stopped the in-flight request" in p and "`status`" in p for p in client.all_prompts
    )
    # 再决策时历史里应有 peek 旁路笔记
    assert any("peek/status" in p and "NOT stopped" in p for p in client.all_prompts)
    # 第二次 act 应能看到 status（progress 或 history）
    assert len(client.act_prompts) >= 2
    second = client.act_prompts[1]
    assert "phase=running" in second or "status" in second.lower()


def test_keep_waiting_decay_follows_persona_coef() -> None:
    def _waiting_patience_after_one_keep(d43: D43Correct) -> int:
        harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
        client = WaitStubClient(
            actions=["send_task", "accept"],
            acts=[{"action": "keep_waiting"}],
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


def test_invoke_control_routes_and_attribution() -> None:
    harness = HeartbeatHarness([("pending", 120.0)])
    client = WaitStubClient(
        actions=["send_task", "give_up"],
        acts=[{"action": "invoke_control", "control": "interrupt"}],
        judging=[{"judgment": "off_track", "perceive": "wrong work"}],
        intents=[{"intent": "interrupt"}],
        verdict="stuck",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    assert harness.controls == ["interrupt"]
    assert any("[interrupted]" in t.harness_output for t in res.turns if t.harness_output)
    assert any("off_track|interrupt→invoke_control:interrupt" in t.perceive for t in res.turns)
    hist_bearing = [p for p in client.all_prompts if "<history>" in p]
    assert any("YOU stopped" in p and "interrupt" in p for p in hist_bearing)
    # interrupt 兑到 invoke_control → 无 gap
    assert not any("WAIT_GAP: intent=interrupt" in s for s in res.signals)


def test_give_up_during_wait_abandons_with_issue() -> None:
    harness = HeartbeatHarness([("pending", 300.0)])
    client = WaitStubClient(
        actions=["send_task"],
        acts=[{"action": "give_up", "message": "forget it"}],
        judging=[{"judgment": "unclear", "perceive": "nothing"}],
        intents=[{"intent": "walk_away"}],
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
        acts=[{"action": "keep_waiting"}],
        verdict="stuck",
    )
    res = run_session(
        _persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three"
    )
    assert res.end_reason == "abandoned"
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert 0 < len(waiting) <= _MAX_HEARTBEATS
    assert len(client.judge_prompts) == len(waiting)
    assert len(client.intent_prompts) == len(waiting)
    assert len(client.act_prompts) == len(waiting)


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
        acts=[{"action": "keep_waiting"}, {"action": "keep_waiting"}],
        judging=[
            {"judgment": "on_track", "perceive": "read"},
            {"judgment": "on_track", "perceive": "pytest"},
        ],
        intents=[{"intent": "keep_waiting"}, {"intent": "keep_waiting"}],
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


def test_stale_progress_taxes_patience() -> None:
    same = [{"kind": "tool", "text": "🔧 run_shell: sleep 999"}]
    harness = HeartbeatHarness(
        [("pending", 90.0), ("pending", 180.0), ("reply", "done")],
        progress_on_poll=[same, same, same],
    )
    client = WaitStubClient(
        actions=["send_task", "accept"],
        acts=[{"action": "keep_waiting"}, {"action": "keep_waiting"}],
        judging=[
            {"judgment": "off_track", "perceive": "sleep"},
            {"judgment": "off_track", "perceive": "still sleep"},
        ],
        intents=[{"intent": "keep_waiting"}, {"intent": "check_status"}],
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
    assert any("WAIT_GAP: intent=check_status" in s for s in res.signals)


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
            {"action": "keep_waiting"},
            {"action": "invoke_control", "control": "interrupt"},
        ],
        judging=[
            {"judgment": "on_track", "perceive": "first"},
            {"judgment": "off_track", "perceive": "curl"},
        ],
        intents=[{"intent": "keep_waiting"}, {"intent": "interrupt"}],
        verdict="unsure",
    )
    run_session(_persona(), client, harness, TASK, manual=harness.manual, waiting_mode="three")
    assert len(client.judge_prompts) >= 2
    assert "<prior_activity>" in client.judge_prompts[1]
    assert "rm -rf" in client.judge_prompts[1]
    assert harness.controls == ["interrupt"]
