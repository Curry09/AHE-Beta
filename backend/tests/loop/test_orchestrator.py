"""Orchestrator 闭环编排单测（各部件 mock）：a 段跑会话 → b 段开发者 agent 自主发版 → 回灌 ref。"""

from __future__ import annotations

import pytest

from auto_designer.dev.agentic_developer import DevOutcome
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.models import Persona, SeedScenario


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


class _Launcher:
    def __init__(self, events: list) -> None:
        self._events = events

    def launch(self, ref: str):
        self._events.append(("launch", ref))
        return ("harness", ref)


class _Dev:
    """假开发者：按预设 outcome 返回；记录调用与收到的 skip。"""

    def __init__(self, events: list, outcome: DevOutcome, label: str = "dev") -> None:
        self._events = events
        self._outcome = outcome
        self._label = label

    def work_one(self, skip: set[int] | None = None) -> DevOutcome:
        self._events.append((self._label, frozenset(skip or set())))
        return self._outcome


def _orch(events, developers, fixed_k=1, initial="v1"):
    def run_session_fn(persona, scenario, harness):
        events.append(("session", harness[1]))

    return Orchestrator(
        launcher=_Launcher(events),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(fixed_k)],
        developer_agents=developers,
        run_session_fn=run_session_fn,
        initial_ref=initial,
    )


def test_round_runs_sessions_then_dev_releases() -> None:
    events: list = []
    dev = _Dev(events, DevOutcome(issue_number=1, branch="fix/issue-1", tag="v2", released=True))
    orch = _orch(events, [dev], fixed_k=2)
    assert orch.run_round("v1") == "v2"  # 发版 → 回灌新 tag
    # a 段两局先于 b 段
    assert events[:4] == [("launch", "v1"), ("session", "v1"), ("launch", "v1"), ("session", "v1")]
    assert events[4][0] == "dev"


def test_no_issue_keeps_ref() -> None:
    events: list = []
    orch = _orch(events, [_Dev(events, DevOutcome())])  # 无 issue / 未发版
    assert orch.run_round("v1") == "v1"


def test_two_devs_chain_ref_and_skip() -> None:
    events: list = []
    dev1 = _Dev(
        events, DevOutcome(issue_number=1, branch="fix/issue-1", tag="v2", released=True), "dev1"
    )
    dev2 = _Dev(
        events, DevOutcome(issue_number=2, branch="fix/issue-2", tag="v3", released=True), "dev2"
    )
    orch = _orch(events, [dev1, dev2])
    assert orch.run_round("v1") == "v3"  # 两次发版链式 v1→v2→v3
    # dev2 收到的 skip 含 dev1 已认领的 issue 1
    dev2_call = next(e for e in events if e[0] == "dev2")
    assert 1 in dev2_call[1]


def test_run_chains_refs_across_rounds() -> None:
    events: list = []
    counter = {"v": 1}

    class _Bump:
        def work_one(self, skip=None):
            counter["v"] += 1
            return DevOutcome(issue_number=1, branch="b", tag=f"v{counter['v']}", released=True)

    orch = Orchestrator(
        launcher=_Launcher(events),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        developer_agents=[_Bump()],
        run_session_fn=lambda p, s, h: events.append(("session", h[1])),
        initial_ref="v1",
    )
    assert orch.run(3) == ["v2", "v3", "v4"]
    launched = [e[1] for e in events if isinstance(e, tuple) and e[0] == "launch"]
    assert launched == ["v1", "v2", "v3"]  # 上一轮返回喂下一轮


def test_run_nonpositive_raises() -> None:
    with pytest.raises(ValueError):
        _orch([], [_Dev([], DevOutcome())]).run(0)


def test_b_phase_error_propagates() -> None:
    events: list = []

    class _BoomDev:
        def work_one(self, skip=None):
            raise RuntimeError("dev 崩了")

    with pytest.raises(RuntimeError):
        _orch(events, [_BoomDev()]).run_round("v1")
