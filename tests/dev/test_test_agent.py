"""spec-0003/T4：TestAgent 体感门禁单测（FakeHarness + 注入体感分，不依赖真 launcher/模型）。"""

from __future__ import annotations

import pytest

from auto_designer.dev.test_agent import TestAgent
from auto_designer.models import (
    FeelingScore,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _fixed_set(k: int = 1):
    return [(_persona(), SeedScenario(description=f"s{i}")) for i in range(k)]


def _session(score: int) -> Session:
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(),
        feeling=FeelingScore(score=score, reason="r"),
    )


class _FakeLauncher:
    def __init__(self) -> None:
        self.launches = 0

    def launch(self, ref: str):
        self.launches += 1
        return object()  # 哑 harness（run_session_fn 被 mock，不真正使用）


class _ScriptRunner:
    """按脚本返回各局 Session；脚本元素为 int(体感分) 或 Exception(该局崩溃)。"""

    def __init__(self, scores: list) -> None:
        self._scores = scores
        self._i = 0
        self.calls = 0

    def __call__(self, persona, scenario, harness) -> Session:
        self.calls += 1
        item = self._scores[self._i]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return _session(item)


def _agent(scores, baseline, n=1, tol=0.0, fixed=None):
    return TestAgent(
        launcher=_FakeLauncher(),
        fixed_set=fixed or _fixed_set(1),
        baseline=baseline,
        n=n,
        tol=tol,
        run_session_fn=_ScriptRunner(scores),
    )


def test_mean_above_baseline_passes() -> None:
    v = _agent([4], baseline=2.0).evaluate("cand")
    assert v.passed is True and v.mean == 4.0


def test_boundary_equals_baseline_minus_tol_passes() -> None:
    # 两局均 3、再降 tol：mean=3.0, baseline=3.1, tol=0.1 → 3.0 >= 3.0 放行
    v = _agent([3, 3], baseline=3.1, n=2, tol=0.1).evaluate("cand")
    assert v.passed is True


def test_below_baseline_minus_tol_fails() -> None:
    v = _agent([1], baseline=3.0, tol=0.1).evaluate("cand")
    assert v.passed is False


def test_n_controls_session_count() -> None:
    runner = _ScriptRunner([4, 4, 4, 4])
    agent = TestAgent(
        launcher=_FakeLauncher(), fixed_set=_fixed_set(2), baseline=1.0, n=2, tol=0.0,
        run_session_fn=runner,
    )
    v = agent.evaluate("cand")
    assert runner.calls == 4  # |fixed_set|(2) × n(2)
    assert len(v.per_session) == 4


def test_missing_baseline_passes_and_flagged() -> None:
    v = _agent([2], baseline=None).evaluate("cand")
    assert v.passed is True and v.baseline_available is False


def test_failed_session_scores_one_and_counts() -> None:
    v = _agent([RuntimeError("崩了"), 4], baseline=1.0, n=2).evaluate("cand")
    assert v.per_session == [1, 4] and v.failures == 1
    assert v.passed is True  # 未中断整次评测


def test_empty_fixed_set_or_bad_n_raises() -> None:
    with pytest.raises(ValueError):
        TestAgent(_FakeLauncher(), [], 1.0, 1, 0.0, _ScriptRunner([]))
    with pytest.raises(ValueError):
        TestAgent(_FakeLauncher(), _fixed_set(1), 1.0, 0, 0.0, _ScriptRunner([]))


def test_launch_failure_propagates() -> None:
    class _BoomLauncher:
        def launch(self, ref: str):
            raise RuntimeError("launch 失败")

    agent = TestAgent(_BoomLauncher(), _fixed_set(1), 1.0, 1, 0.0, _ScriptRunner([4]))
    with pytest.raises(RuntimeError):
        agent.evaluate("cand")
