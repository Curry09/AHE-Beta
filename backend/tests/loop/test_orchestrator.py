"""spec-0003/T6：Orchestrator 闭环编排单测（各部件 mock）。"""

from __future__ import annotations

import pytest

from auto_designer.dev.developer_agent import DevResult
from auto_designer.dev.release import ReleaseResult
from auto_designer.dev.test_agent import Verdict
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
    def __init__(self, events: list, result: DevResult, label: str = "work_one") -> None:
        self._events = events
        self._result = result
        self._label = label

    def work_one(self, skip: set[int] | None = None) -> DevResult:
        self._events.append(self._label)
        return self._result


class _Test:
    def __init__(self, events: list, verdict: Verdict) -> None:
        self._events = events
        self._verdict = verdict

    def evaluate(self, ref: str) -> Verdict:
        self._events.append(("evaluate", ref))
        return self._verdict


def _orch(
    events, dev_result, verdict=None, release_result=None, fixed_k=1, initial="v1", release_fn=None
):
    def default_release_fn(branch, verdict_, issue_number):
        events.append(("release", branch))
        return release_result

    def run_session_fn(persona, scenario, harness):
        events.append(("session", harness[1]))

    return Orchestrator(
        launcher=_Launcher(events),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(fixed_k)],
        tracker=None,
        store=None,
        developer_agents=[_Dev(events, dev_result)],
        test_agent=_Test(events, verdict) if verdict else None,
        release_fn=release_fn or default_release_fn,
        run_session_fn=run_session_fn,
        initial_ref=initial,
    )


def test_full_round_order_and_ref() -> None:
    events: list = []
    orch = _orch(
        events,
        dev_result=DevResult(issue_number=1, branch="fix/issue-1", commit="abc", changed=True),
        verdict=Verdict(passed=True, mean=3.0, baseline=2.0, n=1),
        release_result=ReleaseResult(released=True, tag="v2", ref="v2"),
        fixed_k=2,
    )
    new_ref = orch.run_round("v1")
    assert new_ref == "v2"
    # a 段两局先于 b 段
    assert events[:4] == [("launch", "v1"), ("session", "v1"), ("launch", "v1"), ("session", "v1")]
    assert events[4] == "work_one"
    assert events[5] == ("evaluate", "fix/issue-1")
    assert events[6] == ("release", "fix/issue-1")


def test_no_issue_returns_same_ref() -> None:
    events: list = []
    orch = _orch(events, dev_result=DevResult())  # 无 issue
    assert orch.run_round("v1") == "v1"
    assert "work_one" in events
    assert not any(isinstance(e, tuple) and e[0] in ("evaluate", "release") for e in events)


def test_verdict_fail_no_release_returns_old_ref() -> None:
    events: list = []
    orch = _orch(
        events,
        dev_result=DevResult(issue_number=1, branch="fix/issue-1", changed=True),
        verdict=Verdict(passed=False, mean=1.0, baseline=3.0, n=1),
        release_result=ReleaseResult(released=False),
    )
    assert orch.run_round("v1") == "v1"


def test_run_chains_refs() -> None:
    events: list = []
    counter = {"v": 1}

    def release_fn(branch, verdict_, issue_number):
        counter["v"] += 1
        return ReleaseResult(released=True, tag=f"v{counter['v']}", ref=f"v{counter['v']}")

    orch = _orch(
        events,
        dev_result=DevResult(issue_number=1, branch="fix/issue-1", changed=True),
        verdict=Verdict(passed=True, mean=3.0, baseline=2.0, n=1),
        release_fn=release_fn,
    )
    refs = orch.run(3)
    assert refs == ["v2", "v3", "v4"]
    launched = [e[1] for e in events if isinstance(e, tuple) and e[0] == "launch"]
    assert launched == ["v1", "v2", "v3"]  # 上一轮返回喂下一轮


def test_run_nonpositive_raises() -> None:
    orch = _orch([], dev_result=DevResult())
    with pytest.raises(ValueError):
        orch.run(0)


def test_b_phase_error_propagates() -> None:
    events: list = []

    class _BoomDev:
        def work_one(self, skip: set[int] | None = None):
            raise RuntimeError("dev 崩了")

    orch = Orchestrator(
        launcher=_Launcher(events),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        tracker=None,
        store=None,
        developer_agents=[_BoomDev()],
        test_agent=None,
        release_fn=lambda *a: None,
        run_session_fn=lambda p, s, h: None,
        initial_ref="v1",
    )
    with pytest.raises(RuntimeError):
        orch.run_round("v1")


def test_two_developers_two_releases_chain_ref() -> None:
    # 同轮 2 个 dev 各领一条 issue，各自过门禁发版，ref 链式推进 v1→v2→v3。
    events: list = []
    counter = {"v": 1}

    def release_fn(branch, verdict_, issue_number):
        events.append(("release", branch))
        counter["v"] += 1
        return ReleaseResult(released=True, tag=f"v{counter['v']}", ref=f"v{counter['v']}")

    dev1 = _Dev(events, DevResult(issue_number=1, branch="fix/issue-1", changed=True), label="dev1")
    dev2 = _Dev(events, DevResult(issue_number=2, branch="fix/issue-2", changed=True), label="dev2")
    orch = Orchestrator(
        launcher=_Launcher(events),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        tracker=None,
        store=None,
        developer_agents=[dev1, dev2],
        test_agent=_Test(events, Verdict(passed=True, mean=3.0, baseline=2.0, n=1)),
        release_fn=release_fn,
        run_session_fn=lambda p, s, h: events.append(("session", h[1])),
        initial_ref="v1",
    )
    assert orch.run_round("v1") == "v3"  # 两次发版后的最新 tag
    assert events.count(("release", "fix/issue-1")) == 1
    assert events.count(("release", "fix/issue-2")) == 1
    assert events.index("dev1") < events.index("dev2")  # 依次跑
