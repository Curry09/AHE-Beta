"""spec-0001/T4：run_session 端到端编排、生命周期、提交、落盘、失败路径单测。"""

from __future__ import annotations

import pytest
from test_user_agent import FakeLLM

from auto_designer.harness.interface import FakeHarness
from auto_designer.models import Persona, SeedScenario
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session import run_session
from auto_designer.user.session_store import SessionStore
from auto_designer.user.user_agent import END_SENTINEL, UserAgent


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


class _LifecycleHarness(FakeHarness):
    """记录 reset/close 次数与相对 send 的调用顺序。"""

    def __init__(self, script: list[str]) -> None:
        super().__init__(script=script)
        self.events: list[str] = []

    def reset(self) -> None:
        super().reset()
        self.events.append("reset")

    def send(self, message: str) -> str:
        self.events.append("send")
        return super().send(message)

    def close(self) -> None:
        super().close()
        self.events.append("close")


def _agent(messages: list[str], issues: str = "[]") -> UserAgent:
    return UserAgent(llm=FakeLLM(messages, "3 还行", issues), persona=_persona(), max_turns=10)


def test_end_to_end_returns_full_session(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = run_session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        harness=FakeHarness(script=["r1", "r2"]),
        user_agent=_agent(["m1", "m2", f"{END_SENTINEL}"]),
        tracker=FakeTracker(),
        store=store,
    )
    assert session.feeling.score == 3
    assert len([t for t in session.transcript.turns if t.role == "user"]) == 2
    assert store.load(session.session_id) == session  # 已落盘可还原


def test_lifecycle_reset_run_close_order(tmp_path) -> None:
    harness = _LifecycleHarness(script=["r1"])
    run_session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        harness=harness,
        user_agent=_agent(["m1", f"{END_SENTINEL}"]),
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
    )
    assert harness.events[0] == "reset"
    assert harness.events[-1] == "close"
    assert harness.events.count("reset") == 1 and harness.events.count("close") == 1
    assert harness.events.index("reset") < harness.events.index("send") < harness.events.index("close")


def test_drafts_submitted_in_order(tmp_path) -> None:
    issues = '[{"title": "a", "body": "ba", "labels": []}, {"title": "b", "body": "bb", "labels": ["bug"]}]'
    tracker = FakeTracker()
    session = run_session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        harness=FakeHarness(script=["r1"]),
        user_agent=_agent(["m1", f"{END_SENTINEL}"], issues=issues),
        tracker=tracker,
        store=SessionStore(tmp_path),
    )
    assert [r.number for r in session.issue_refs] == [1, 2]
    assert tracker.issue(1)["title"] == "a"


def test_zero_drafts_still_persisted(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = run_session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        harness=FakeHarness(script=["r1"]),
        user_agent=_agent(["m1", f"{END_SENTINEL}"]),
        tracker=FakeTracker(),
        store=store,
    )
    assert session.issue_refs == []
    assert store.load(session.session_id) == session


def test_early_giveup_under_max_turns(tmp_path) -> None:
    session = run_session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        harness=FakeHarness(script=["r1"]),
        user_agent=_agent([f"算了 {END_SENTINEL}"]),  # 第一轮即放弃
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
    )
    assert len([t for t in session.transcript.turns if t.role == "user"]) == 0


def test_failure_path_closes_harness_no_persist_no_submit(tmp_path) -> None:
    def boom(_m: str) -> str:
        raise RuntimeError("崩了")

    harness = _LifecycleHarness(script=[])
    harness._callback = boom  # 让 send 抛异常
    tracker = FakeTracker()
    store = SessionStore(tmp_path)
    with pytest.raises(RuntimeError):
        run_session(
            persona=_persona(),
            scenario=SeedScenario(description="x"),
            harness=harness,
            user_agent=_agent(["m1"]),  # 不发结束信号 → 触发 send
            tracker=tracker,
            store=store,
        )
    assert "close" in harness.events  # 仍释放资源
    assert store.index() == []  # 未落盘
    assert tracker._counter == 0  # 未提交
