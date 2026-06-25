"""会话编排 runner（spec-0001/T4）：单一无状态入口 run_session，编排一局完整会话。

所有依赖经参数注入，runner 自身不构造任何后端。负责 harness 生命周期（开局 reset、收尾 close），
调 UserAgent.run 取产物，逐条提交 issue 收 IssueRef，组装 Session 并落盘后返回。
下游（loop 编排、metrics）复用此唯一入口。
"""

from __future__ import annotations

from auto_designer.harness.interface import HarnessInterface
from auto_designer.models import Persona, SeedScenario, Session
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.user_agent import UserAgent


def run_session(
    persona: Persona,
    scenario: SeedScenario,
    harness: HarnessInterface,
    user_agent: UserAgent,
    tracker: IssueTracker,
    store: SessionStore,
) -> Session:
    """编排一局会话并返回结构化 Session。失败局不留半成品（不提交、不落盘）。"""
    harness.reset()  # 开局责任归编排层（T2 约定）
    try:
        transcript, feeling, drafts = user_agent.run(scenario, harness)
    finally:
        harness.close()  # 无论成败都释放后端资源；异常继续向上传播
    issue_refs = [tracker.create_issue(d) for d in drafts]  # 顺序与 drafts 一一对应
    session = Session(
        persona=persona,
        scenario=scenario,
        transcript=transcript,
        feeling=feeling,
        issue_refs=issue_refs,
    )
    store.save(session)  # 体感 + session 落本地
    return session
