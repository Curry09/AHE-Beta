"""sim 用户 agent 接入闭环的适配器（loop/sim_user.py）。

用 Fake tracker + ScriptedPersonaClient + ScriptedHarness 离线验证：适配器跑 sim、把
issue_artifact 真落 tracker、SessionResult 转 models.Session 落 store、逐轮+收尾回调 on_turn。
"""

from __future__ import annotations

from auto_designer.loop.sim_user import make_sim_run_session_fn, result_to_turns
from auto_designer.models import Persona, SeedScenario, Session, WorkspaceSpec
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


def test_result_to_turns_includes_pending_harness_reply() -> None:
    """实时快照：已到手、尚未随下一条 TurnLog 落日志的悬挂 harness 回复也要进对话，
    否则 harness 长任务期间看板只见用户消息不见回复；与末条已入日志回复相同时不重复。"""
    res = SessionResult(
        persona_id="P-0991",
        end_reason="max_turns",
        turns=[_turn(1, "send_task", "emit", "Implement the interpreter ...", "")],
        pending_harness_output="done: interpreter implemented",
    )
    turns = result_to_turns(res)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "Implement the interpreter ..."),
        ("harness", "done: interpreter implemented"),
    ]

    # 悬挂内容与最后一条已入日志的 harness 快照相同 → 视为同一条，不重复
    res.turns.append(_turn(2, "give_feedback", "emit", "again", "done: interpreter implemented"))
    roles = [t.role for t in result_to_turns(res)]
    assert roles == ["user", "harness", "user"]


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
    seen: list[tuple[bool, str | None]] = []

    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,  # Spec-0017/T2：工厂注入，每局新建
        tracker=tracker,
        store=store,
        sim_personas={mp.identity: sp},
        on_turn=lambda ident, sim_p, res, running, *, session_id=None: seen.append(
            (running, session_id)
        ),
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
    # 逐轮回调(若干 True，无 session_id) + 收尾一次 False（带 session_id 供看板归档关联）
    assert seen and seen[-1] == (False, session.session_id)
    assert any(running for running, _ in seen[:-1])
    assert all(sid is None for _, sid in seen[:-1])


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
        client_factory=_HappyClient, tracker=tracker, store=store, sim_personas={mp.identity: sp}
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert session.issue_refs == []
    assert tracker.list_open_issues() == []


def _fn(tmp_path):
    sp = expert()
    mp = _model_persona(sp)
    return make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
    ), mp


def test_client_factory_gives_each_session_its_own_instance(tmp_path) -> None:
    """Spec-0017/T2：每局一实例——工厂逐局调用，bind_session 互不覆盖（并发串台的根治点）。

    用记录型 fake：既记工厂产出的实例，也记每个实例 bind 到的 (persona, workspace)。
    并发跑两局（线程屏障齐射），断言两局各自的实例独立、各自 bind 各自的工作区。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    sp = expert()
    mp = _model_persona(sp)

    class _RecordingClient(ScriptedPersonaClient):
        def __init__(self) -> None:
            super().__init__()
            self.bound: list[tuple[object, str | None]] = []

        def bind_session(self, *, persona, workspace_dir) -> None:
            self.bound.append((persona, workspace_dir))

    made: list[_RecordingClient] = []

    def factory() -> _RecordingClient:
        c = _RecordingClient()
        made.append(c)
        return c

    fn = make_sim_run_session_fn(
        client_factory=factory,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
    )

    barrier = threading.Barrier(2)

    def one(ws: str) -> None:
        barrier.wait()
        fn(mp, SeedScenario(description="task"), ScriptedHarness(), workspace_dir=ws)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, ["/ws/a", "/ws/b"]))

    assert len(made) == 2 and made[0] is not made[1]  # 每局独立实例
    # 每个实例恰 bind 一次、且两局的 workspace 各归各（无后 bind 覆盖先 bind）
    all_bound = [c.bound for c in made]
    assert all(len(b) == 1 for b in all_bound)
    assert {b[0][1] for b in all_bound} == {"/ws/a", "/ws/b"}


def test_fallback_materialize_then_ensure_deps(tmp_path, monkeypatch) -> None:
    """Spec-0009/T3：不经 orchestrator 的直连回落——未传 workspace_dir 但 scenario 带 workspace 时，
    run() 自行 materialize，且必须在 materialize 之后对称调 ensure_deps（顺序：materialize 在前）。
    """
    events: list = []
    monkeypatch.setattr(
        "auto_designer.loop.sim_user.materialize_workspace",
        lambda spec: events.append(("materialize", spec.fixture)) or f"/ws/{spec.fixture}",
    )
    monkeypatch.setattr(
        "auto_designer.loop.sim_user.ensure_deps",
        lambda ws, spec: events.append(("ensure_deps", ws)),
    )
    fn, mp = _fn(tmp_path)
    scenario = SeedScenario(
        description="task",
        workspace=WorkspaceSpec(fixture="funcy", setup=["python -m venv .venv"]),
    )

    fn(mp, scenario, ScriptedHarness())  # 不传 workspace_dir → 走回落分支

    assert events == [("materialize", "funcy"), ("ensure_deps", "/ws/funcy")]


def test_main_path_does_not_ensure_deps_in_sim_user(tmp_path, monkeypatch) -> None:
    """传入 workspace_dir 的 orchestrator 主路径：依赖已由 orchestrator 就位，sim_user 不重复
    materialize/ensure_deps（反向断言）。"""
    monkeypatch.setattr(
        "auto_designer.loop.sim_user.materialize_workspace",
        lambda spec: (_ for _ in ()).throw(AssertionError("主路径不应 materialize")),
    )
    monkeypatch.setattr(
        "auto_designer.loop.sim_user.ensure_deps",
        lambda ws, spec: (_ for _ in ()).throw(AssertionError("主路径不应 ensure_deps")),
    )
    fn, mp = _fn(tmp_path)
    scenario = SeedScenario(
        description="task",
        workspace=WorkspaceSpec(fixture="funcy", setup=["python -m venv .venv"]),
    )

    # 传入 workspace_dir（orchestrator 已 materialize+ensure）→ sim_user 不再碰这两者，不抛即通过。
    fn(mp, scenario, ScriptedHarness(), workspace_dir="/given/ws")
