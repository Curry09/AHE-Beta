"""把 spec-0005 控制信封 sim 用户 agent 接进 spec-0003/0007 闭环。

Orchestrator 只认 run_session_fn(persona, scenario, harness)（返回值不管，落盘/提交由实现负责）。
本模块产出这样一个 fn：内部跑 sim.loop.run_session（真 persona LLM × 真 harness），逐轮经 on_turn
回调供观测层（看板）实时展示；会话末把 issue_artifact 提交到真 tracker、SessionResult 转 models.Session
落 store。persona 以 9 维 sim persona 为准，展示用 models.Persona 由调用方反向派生后按 identity 配对传入。
"""

from __future__ import annotations

from collections.abc import Callable

from auto_designer.harness.interface import HarnessInterface
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    PersonaCallTrace,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
    Turn,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.dimensions import Persona as SimPersona
from auto_designer.user.sim.loop import SessionResult
from auto_designer.user.sim.loop import run_session as sim_run_session
from auto_designer.user.sim.persona_client import PersonaClient
from auto_designer.user.sim.workspace import materialize as materialize_workspace

# 观测回调：(identity, sim_persona, 进行中/最终的 SessionResult, running, *, session_id) -> None。
# session_id 仅收尾（running=False）时携带（session 已落 store），供看板归档关联全量会话。
SimTurnHook = Callable[..., None]


def result_to_turns(res: SessionResult) -> list[Turn]:
    """SessionResult → models.Turn 序列：每轮先 harness 文本、后 user 消息（空则跳过）。

    `TurnLog.harness_output` 是「本轮 persona 看到的*上一轮* harness 回复」快照，会跨非-EMIT
    轮（verify_self 等 silent 轮不重发 harness）重复携带同一值。故按「相邻去重」只在 harness
    回复真正变化（= 有新一轮回复）时记一条 harness 轮，否则同一条 completion 会被展开成多条、
    与 user 消息错位（曾使落盘 transcript 现 `user, harness×N, user` 的假象）。
    """
    turns: list[Turn] = []
    prev_ho: str | None = None
    for t in res.turns:
        ho = t.harness_output.strip()
        if ho and ho != prev_ho:  # 仅新一轮 harness 回复才记，连续相同快照视为同一条
            # steps = 该回复的内层迭代过程（观测层展开才看，persona 只吃 content）
            turns.append(Turn(role="harness", content=ho, steps=list(t.harness_steps or [])))
        if ho:
            prev_ho = ho
        if t.message.strip():
            turns.append(Turn(role="user", content=t.message.strip()))
    # 悬挂中的 harness 回复（已到手、尚未随下一条 TurnLog 落日志）：实时快照补上这半边
    pending = (res.pending_harness_output or "").strip()
    if pending and pending != prev_ho:
        turns.append(
            Turn(role="harness", content=pending, steps=list(res.pending_harness_steps or []))
        )
    return turns


def result_to_sim_trace(res: SessionResult) -> SimTrace:
    """SessionResult → 可落盘的 god-view：TurnLog 决策时间线原样投影，心路与对话片段同条共置。"""
    derived = None
    if res.feeling_derived is not None:
        derived = FeelingScore(score=res.feeling_derived.score, reason=res.feeling_derived.reason)
    return SimTrace(
        persona_id=res.persona_id,
        end_reason=res.end_reason,
        turns=[
            SimTurn(
                turn=t.turn,
                phase=t.phase,
                action_space=list(t.action_space),
                perceive=t.perceive,
                verdict=t.verdict,
                action=t.action,
                message=t.message,
                executor=t.executor,
                channel=t.channel,
                patience=t.patience,
                trust=t.trust,
                harness_output=t.harness_output,
                harness_steps=list(t.harness_steps or []),
                persona_trace=[
                    PersonaCallTrace.from_dict(c) if isinstance(c, dict) else c
                    for c in (t.persona_trace or [])
                ],
                utterance_id=getattr(t, "utterance_id", "") or "",
                delivery=getattr(t, "delivery", "") or "",
                queued_behind=getattr(t, "queued_behind", "") or "",
                answers_utterance_id=getattr(t, "answers_utterance_id", "") or "",
                answers_said=getattr(t, "answers_said", "") or "",
            )
            for t in res.turns
        ],
        signals=list(res.signals),
        feeling_derived=derived,
        persona_tail=[
            PersonaCallTrace.from_dict(c) if isinstance(c, dict) else c
            for c in (res.persona_tail or [])
        ],
    )


def _issue_draft_from_body(body: str) -> IssueDraft:
    """markdown/正文 → Gitea 建 issue 入参。sim issue 均失败/不满驱动，打 bug。

    标题取正文首行（即用户第一人称原话的开头），不加框架前缀。
    """
    text = body or ""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "simulated user issue")
    return IssueDraft(title=first[:80], body=text, labels=["bug"])


def _issue_draft(res: SessionResult) -> IssueDraft:
    """兼容旧单测：仅从终结收场的 issue_artifact 建 draft。"""
    return _issue_draft_from_body(res.issue_artifact or "")


def _flush_issues(tracker: IssueTracker, res: SessionResult) -> list:
    """中途 report_issue notes + 终结 issue_artifact 一并建单（顺序：先中途、后收场）。"""
    refs = []
    for body in res.issue_notes:
        refs.append(tracker.create_issue(_issue_draft_from_body(body)))
    if res.issue_artifact:
        refs.append(tracker.create_issue(_issue_draft_from_body(res.issue_artifact)))
    return refs


def make_sim_run_session_fn(
    *,
    client_factory: Callable[[], PersonaClient],
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    on_turn: SimTurnHook | None = None,
) -> Callable[..., Session]:
    """返回 Orchestrator 用的 run_session_fn。

    client_factory: 每局新建 persona client（Spec-0017/T2）。AgenticPersonaClient 是会话级
    有状态的（bind_session 写 _persona/_workspace_dir），a 段多用户会话并行后跨局复用单实例
    必串台（后 bind 覆盖先 bind）；底层 ApiPersonaClient.complete 无会话态可全局共享，工厂
    只新建外壳。
    sim_personas: 展示用 models.Persona.identity -> 9 维 sim persona（权威画像）。
    on_turn: 逐轮（含终止轮）+ 收尾各回调一次，供调用方发 agent 活动到看板。
    """

    def run(
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: str | None = None,
    ) -> Session:
        sim_persona = sim_personas[persona.identity]
        client = client_factory()  # Spec-0017/T2：每局独立实例，bind 互不覆盖

        # spec-0008/T1 v2：共享工作区。orchestrator 每局先 materialize 一份工作区，经 launcher 注入
        # harness（SANDBOX_WORK_DIR）并把同一目录 workspace_dir 传到这里——两侧 cwd 同指一处，harness
        # 改、用户 agent 同目录核实。这里复用传入目录绑定内层 client，不再自行 materialize。
        # 兼容直连调用（不经 orchestrator）：未传 workspace_dir 但 scenario 带 workspace 时，回落自行
        # materialize（等价 v1）。守卫式 bind_session：仅 AgenticPersonaClient 暴露，Scripted/Api 跳过。
        ws = workspace_dir
        if ws is None and scenario.workspace is not None:
            ws = materialize_workspace(scenario.workspace)
            # Spec-0009/T3：回落路径 materialize 后对称调 ensure_deps（与 orchestrator 主路径同构），
            # 使这条生产接缝「建了工作区即备好依赖」，不静默缺依赖。orchestrator 已传 workspace_dir
            # 的主路径依赖由 orchestrator 就位，故仅在此回落分支 ensure，不重复调。
            ensure_deps(ws, scenario.workspace)
        if ws is not None and hasattr(client, "bind_session"):
            client.bind_session(persona=sim_persona, workspace_dir=ws)

        def progress(partial: SessionResult) -> None:
            if on_turn is not None:
                on_turn(persona.identity, sim_persona, partial, True, session_id=None)

        harness.reset()  # 开局责任归编排层
        try:
            res = sim_run_session(
                sim_persona,
                client,
                harness,
                scenario.description,
                # 该版本 harness 的用户手册：让 persona 的能力预期锚定"这工具文档说的"，
                # 而非空泛先验；缺省空串（老后端无 manual 属性）。
                manual=getattr(harness, "manual", ""),
                on_progress=progress,
            )
        finally:
            harness.close()  # 无论成败都释放 harness 子进程

        issue_refs = _flush_issues(tracker, res)
        feel = res.feeling or res.feeling_derived
        session = Session(
            persona=persona,
            scenario=scenario,
            transcript=Transcript(turns=result_to_turns(res)),
            feeling=FeelingScore(score=feel.score, reason=feel.reason),
            issue_refs=issue_refs,
            sim_trace=result_to_sim_trace(res),
        )
        store.save(session)  # 体感 + session 落本地（issue 权威源在 Gitea）
        if on_turn is not None:
            # 收尾：标 running=False，带 session_id 供看板归档关联全量会话。
            on_turn(persona.identity, sim_persona, res, False, session_id=session.session_id)
        return session

    return run
