"""sim 用户 agent 接入闭环的适配器（loop/sim_user.py）。

用 Fake tracker + ScriptedPersonaClient + ScriptedHarness 离线验证：适配器跑 sim、把
issue_artifact 真落 tracker、SessionResult 转 models.Session 落 store、逐轮+收尾回调 on_turn。
"""

from __future__ import annotations

from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
from auto_designer.models import Persona, SeedScenario, Session
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.loop import SessionResult, TurnLog
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.run_live import expert


def _turn(turn: int, action: str, channel: str, message: str, harness_output: str) -> TurnLog:
    return TurnLog(
        turn=turn,
        phase="active",
        action_space=[],
        perceive="",
        verdict="unsure",
        action=action,
        message=message,
        executor="x",
        channel=channel,
        patience=3,
        trust="ok",
        harness_output=harness_output,
    )


def test_result_to_turns_dedupes_repeated_harness_snapshot() -> None:
    """harness_output 是「本轮 persona 看到的上轮回复」快照，会跨非-EMIT 轮重复携带。

    silent 轮（verify_self 等）不重发 harness，却各自快照同一条 completion；result_to_turns
    必须按「真有新 harness 回复」去重，否则同一条被展开成多条 harness 轮、与 user 错位。
    """
    completion = '{"result": "done: split_bill implemented"}'
    res = SessionResult(
        persona_id="P-0991",
        end_reason="accepted",
        turns=[
            _turn(0, "send_task", "emit", "Please inspect billing/core.py ...", ""),
            _turn(1, "verify_self", "silent", "", completion),  # 快照同一 completion
            _turn(2, "verify_self", "silent", "", completion),
            _turn(3, "verify_self", "silent", "", completion),
            _turn(4, "accept", "emit", "Looks good, thanks.", completion),
        ],
    )

    turns = result_to_turns(res)

    # harness 实际只回了 1 次 → 只应有 1 条 harness 轮，且严格 user/harness/user 交替
    roles = [t.role for t in turns]
    assert roles == ["user", "harness", "user"]
    assert turns[1].content == completion
    assert turns[0].content.startswith("Please inspect")
    assert turns[2].content == "Looks good, thanks."


def _model_persona(sp) -> Persona:
    return Persona(
        identity=sp.persona_id,
        level=sp.d1.value,
        domain="/".join(sp.d2.stack) or "general",
        goal="task",
        speaking_style="s",
    )


def test_sim_adapter_files_issue_saves_session_and_emits(tmp_path) -> None:
    sp = expert()  # 逼证据 -> file_issue（ScriptedPersonaClient×ScriptedHarness 下确定性提 issue）
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)
    seen: list[bool] = []

    fn = make_sim_run_session_fn(
        client=ScriptedPersonaClient(),
        tracker=tracker,
        store=store,
        sim_personas={mp.identity: sp},
        on_turn=lambda ident, sim_p, res, running: seen.append(running),
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert isinstance(session, Session)
    assert session.persona.identity == sp.persona_id
    # issue 真落 tracker，session 持回执
    open_issues = tracker.list_open_issues()
    assert len(open_issues) == 1
    assert "bug" in open_issues[0].labels
    assert session.issue_refs and session.issue_refs[0].number == open_issues[0].number
    # session 落盘可回读
    assert store.load(session.session_id).session_id == session.session_id
    # 逐轮回调(若干 True) + 收尾一次 False
    assert seen and seen[-1] is False and any(seen[:-1])


def test_sim_adapter_no_issue_when_not_filed(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)

    # 客户端始终满意 -> 不会 file_issue -> 不应有 issue 落库。
    class _HappyClient:
        def respond(self, system: str, user: str) -> dict:
            if "<rate_experience>" in user:
                return {"score": 4, "reason": "great"}
            return {"perceive": "", "verdict": "satisfied", "action": "accept", "message": "ok"}

    fn = make_sim_run_session_fn(
        client=_HappyClient(), tracker=tracker, store=store, sim_personas={mp.identity: sp}
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert session.issue_refs == []
    assert tracker.list_open_issues() == []
