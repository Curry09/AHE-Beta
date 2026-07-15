"""心跳（等待中的主动权）：send 阻塞超阈值 → 唤醒用户 agent 决策（继续等/动用控制/放弃）。

用一个支持 begin/poll/control 的受控 harness + 感知 <waiting> 的 stub client，验证：
- 继续等 → 续等到回复，唤醒轮以 phase='waiting' 记入观测；
- 动用控制 → 走通用 control(name)，其回复即本轮 harness_output（打断保留会话语义）；
- 放弃 → 会话 abandoned 并留退出 issue；
- 病态（一直继续等 + 永不回）→ 兜底强制放弃，唤醒次数受硬上限约束。
"""

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
    """受控 harness：poll 按脚本逐次弹 ('pending', waited) / ('reply', text)，耗尽后重复末项。

    progress_on_poll[i]：第 i 次 poll 结束后 last_progress 应变成的全量列表（模拟活动条累积）。
    """

    def __init__(
        self,
        poll_script: list[tuple[str, object]],
        control_reply: str = "[interrupted] stopped; session kept.",
        manual: str = "# Manual\nYou can interrupt a running request.",
        progress_on_poll: list[list[dict]] | None = None,
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
        self._inflight = False
        return self.control_reply


class WaitStubClient:
    """按脚本出主决策；<waiting> 轮出等待决策；<rate_experience>/<file_issue> 走兜底。"""

    def __init__(
        self,
        actions: list[str],
        waiting: list[dict],
        verdict: str = "unsure",
    ) -> None:
        self._actions = actions
        self._ai = 0
        self._waiting = waiting
        self._wi = 0
        self._verdict = verdict
        self.waiting_prompts: list[str] = []

    def respond(self, system: str, user: str) -> dict:  # noqa: ARG002
        if "<rate_experience>" in user:
            return {"score": 2, "reason": "slow"}
        if "<file_issue>" in user:
            return {"issue": "it hung forever with no visibility"}
        if "<waiting>" in user:
            self.waiting_prompts.append(user)
            w = self._waiting[min(self._wi, len(self._waiting) - 1)]
            self._wi += 1
            return w
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
    # 说要用控制却没点名 → 退回继续等，不瞎猜控制名
    assert _resolve_waiting({"action": "invoke_control", "control": ""}) == ("keep_waiting", "")
    # 非法动作 → 安全落继续等
    assert _resolve_waiting({"action": "panic"}) == ("keep_waiting", "")


def test_keep_waiting_then_reply_logs_waiting_turn() -> None:
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done at last!")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        waiting=[{"action": "keep_waiting", "perceive": "still working, I'll wait"}],
        verdict="satisfied",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    waiting_turns = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting_turns) == 1
    assert waiting_turns[0].action == "keep_waiting"
    assert waiting_turns[0].action_space == WAITING_ACTIONS
    # 续等拿到的回复成为该轮 harness_output（被下一轮 send_task 之后的 turn 携带）
    assert any(t.harness_output == "done at last!" for t in res.turns)
    # manual 进了心跳唤醒的 context（用户据此知道能打断）
    assert client.waiting_prompts and "interrupt" in client.waiting_prompts[0]


def test_keep_waiting_decay_follows_persona_coef() -> None:
    # 去重：keep_waiting 扣耐心口径与 apply_verdict 统一，按 persona 的 patience_decay 加权，非平扣 1。
    # FEEDBACK：基线 5、coef=1 → 一次 keep_waiting 后 4；GIVE_UP：基线 3、coef=2 → 一次后 1。
    def _waiting_patience_after_one_keep(d43: D43Correct) -> int:
        harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
        client = WaitStubClient(
            actions=["send_task", "accept"],
            waiting=[{"action": "keep_waiting"}],
            verdict="satisfied",
        )
        res = run_session(_persona(d43=d43), client, harness, TASK, manual=harness.manual)
        wt = [t for t in res.turns if t.phase == "waiting"]
        assert len(wt) == 1
        return wt[0].patience

    assert _waiting_patience_after_one_keep(D43Correct.FEEDBACK) == 4  # 5 - coef(1)
    assert _waiting_patience_after_one_keep(D43Correct.GIVE_UP) == 1  # 3 - coef(2)


def test_invoke_control_routes_through_generic_control() -> None:
    harness = HeartbeatHarness([("pending", 120.0)])
    client = WaitStubClient(
        actions=["send_task", "give_up"],
        waiting=[{"action": "invoke_control", "control": "interrupt"}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    # 框架通用投递：control 名原样透传，未写死 interrupt
    assert harness.controls == ["interrupt"]
    # 控制的回复成为本轮 harness_output（打断→保留会话的定型回复）
    assert any("[interrupted]" in t.harness_output for t in res.turns if t.harness_output)


def test_give_up_during_wait_abandons_with_issue() -> None:
    harness = HeartbeatHarness([("pending", 300.0)])
    client = WaitStubClient(
        actions=["send_task"],
        waiting=[{"action": "give_up", "message": "forget it, too slow"}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    assert res.end_reason == "abandoned"
    assert res.issue_artifact is not None
    assert any(t.phase == "waiting" and t.action == "give_up" for t in res.turns)


def test_pathological_keep_waiting_is_bounded_and_gives_up() -> None:
    # harness 永不回、用户一直"继续等" → 兜底（耐心耗尽 or 唤醒硬上限）强制收束为放弃，不无限等。
    harness = HeartbeatHarness([("pending", 90.0)])  # 永远 pending
    client = WaitStubClient(
        actions=["send_task"],
        waiting=[{"action": "keep_waiting"}],
        verdict="stuck",
    )
    res = run_session(_persona(), client, harness, TASK, manual=harness.manual)
    assert res.end_reason == "abandoned"
    waiting_turns = [t for t in res.turns if t.phase == "waiting"]
    assert 0 < len(waiting_turns) <= _MAX_HEARTBEATS


def test_visible_progress_skips_patience_tax_and_enters_waiting_prompt() -> None:
    """有新活动条时 keep_waiting 不扣耐心；等待 prompt 带上 <progress>。"""
    # FEEDBACK 基线 patience=5；两次 pending 各带更多 progress → 不应掉到 4/3。
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
        waiting=[
            {"action": "keep_waiting", "perceive": "it's reading files, I'll wait"},
            {"action": "keep_waiting", "perceive": "now running tests, still ok"},
        ],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK), client, harness, TASK, manual=harness.manual
    )
    waiting = [t for t in res.turns if t.phase == "waiting"]
    assert len(waiting) == 2
    # 两次 keep_waiting 都有新 progress → patience 仍为开局 5
    assert waiting[0].patience == 5
    assert waiting[1].patience == 5
    assert any("<progress>" in p for p in client.waiting_prompts)
    assert any("pytest" in p for p in client.waiting_prompts)


def test_silent_pending_still_taxes_patience() -> None:
    """无 progress 的黑盒等待：keep_waiting 仍按性格扣耐心（旧行为保留）。"""
    harness = HeartbeatHarness([("pending", 90.0), ("reply", "done")])
    client = WaitStubClient(
        actions=["send_task", "accept"],
        waiting=[{"action": "keep_waiting"}],
        verdict="satisfied",
    )
    res = run_session(
        _persona(d43=D43Correct.FEEDBACK), client, harness, TASK, manual=harness.manual
    )
    wt = [t for t in res.turns if t.phase == "waiting"]
    assert len(wt) == 1
    assert wt[0].patience == 4  # 5 - coef(1)
    assert "<progress>" not in client.waiting_prompts[0]
    assert "NOTHING visible" in client.waiting_prompts[0]