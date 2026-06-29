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
    SeedScenario,
    Session,
    Transcript,
    Turn,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.dimensions import Persona as SimPersona
from auto_designer.user.sim.loop import SessionResult
from auto_designer.user.sim.loop import run_session as sim_run_session
from auto_designer.user.sim.persona_client import PersonaClient

# 观测回调：(identity, sim_persona, 进行中/最终的 SessionResult, running) -> None。
SimTurnHook = Callable[[str, SimPersona, SessionResult, bool], None]


def result_to_turns(res: SessionResult) -> list[Turn]:
    """SessionResult → models.Turn 序列：每轮先 harness 文本、后 user 消息（空则跳过）。"""
    turns: list[Turn] = []
    for t in res.turns:
        if t.harness_output.strip():
            turns.append(Turn(role="harness", content=t.harness_output.strip()))
        if t.message.strip():
            turns.append(Turn(role="user", content=t.message.strip()))
    return turns


def _issue_draft(res: SessionResult) -> IssueDraft:
    """sim 的 issue_artifact（markdown）→ Gitea 建 issue 入参。sim issue 均失败/不满驱动，打 bug。

    标题取正文首行（即用户第一人称原话的开头），不加框架前缀，读起来就是用户自己提的 issue；
    persona 身份等机器信息已在正文末的脚注里，开发者仍可分流。
    """
    body = res.issue_artifact or ""
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "simulated user issue")
    return IssueDraft(title=first[:80], body=body, labels=["bug"])


def make_sim_run_session_fn(
    *,
    client: PersonaClient,
    tracker: IssueTracker,
    store: SessionStore,
    sim_personas: dict[str, SimPersona],
    on_turn: SimTurnHook | None = None,
) -> Callable[[Persona, SeedScenario, HarnessInterface], Session]:
    """返回 Orchestrator 用的 run_session_fn。

    sim_personas: 展示用 models.Persona.identity -> 9 维 sim persona（权威画像）。
    on_turn: 逐轮（含终止轮）+ 收尾各回调一次，供调用方发 agent 活动到看板。
    """

    def run(persona: Persona, scenario: SeedScenario, harness: HarnessInterface) -> Session:
        sim_persona = sim_personas[persona.identity]

        def progress(partial: SessionResult) -> None:
            if on_turn is not None:
                on_turn(persona.identity, sim_persona, partial, True)

        harness.reset()  # 开局责任归编排层（对齐基础版 user/session.run_session）
        try:
            res = sim_run_session(
                sim_persona, client, harness, scenario.description, on_progress=progress
            )
        finally:
            harness.close()  # 无论成败都释放 harness 子进程

        issue_refs = [tracker.create_issue(_issue_draft(res))] if res.issue_artifact else []
        feel = res.feeling or res.feeling_derived
        session = Session(
            persona=persona,
            scenario=scenario,
            transcript=Transcript(turns=result_to_turns(res)),
            feeling=FeelingScore(score=feel.score, reason=feel.reason),
            issue_refs=issue_refs,
        )
        store.save(session)  # 体感 + session 落本地（issue 权威源在 Gitea）
        if on_turn is not None:
            on_turn(persona.identity, sim_persona, res, False)  # 收尾：标 running=False
        return session

    return run
