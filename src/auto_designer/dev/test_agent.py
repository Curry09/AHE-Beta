"""test_agent 体感门禁（spec-0003/T4）：候选 harness 跑固定集 N 局，平均体感不退化则放行。

门禁只用体感——benchmark 全程 held-out，不进入 Verdict（签名层即不接收 benchmark）。
评测即「让用户 agent 用候选 harness 跑几局看体感」：复用 run_session（经注入的 SessionRunner），
与训练信号同源。每场景每局新 launch 一个 harness（run_session 自带 reset/close）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from auto_designer.harness.interface import HarnessInterface
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.models import Persona, SeedScenario, Session

# 跑一局会话并返回 Session（绑定了 user_agent/tracker/store 的 run_session 偏函数）。
SessionRunner = Callable[[Persona, SeedScenario, HarnessInterface], Session]


@dataclass
class Verdict:
    passed: bool
    mean: float
    baseline: float | None
    n: int
    per_session: list[int] = field(default_factory=list)
    baseline_available: bool = True
    failures: int = 0


class TestAgent:
    """对候选 ref 跑 |fixed_set|×n 局算平均体感，与 baseline 比（持平放行）。"""

    __test__ = False  # 名字以 Test 开头但不是 pytest 测试类，避免被收集

    def __init__(
        self,
        launcher: HarnessLauncher,
        fixed_set: list[tuple[Persona, SeedScenario]],
        baseline: float | None,
        n: int,
        tol: float,
        run_session_fn: SessionRunner,
    ) -> None:
        if not fixed_set:
            raise ValueError("fixed_set 不能为空")
        if n <= 0:
            raise ValueError(f"n 须为正：{n}")
        self._launcher = launcher
        self._fixed_set = fixed_set
        self._baseline = baseline
        self._n = n
        self._tol = tol
        self._run_session = run_session_fn

    def evaluate(self, candidate_ref: str) -> Verdict:
        scores: list[int] = []
        failures = 0
        for persona, scenario in self._fixed_set:
            for _ in range(self._n):
                harness = self._launcher.launch(candidate_ref)  # launch 失败 → 上抛
                try:
                    session = self._run_session(persona, scenario, harness)
                    scores.append(session.feeling.score)
                except Exception:  # 崩溃局计最低分（1），不被无声忽略抬高均值
                    scores.append(1)
                    failures += 1
        mean = sum(scores) / len(scores)
        if self._baseline is None:  # 基线缺失（首轮）→ 放行，本版定为基线
            return Verdict(
                passed=True,
                mean=mean,
                baseline=None,
                n=self._n,
                per_session=scores,
                baseline_available=False,
                failures=failures,
            )
        passed = mean >= self._baseline - self._tol  # 持平即过，只挡退化
        return Verdict(
            passed=passed,
            mean=mean,
            baseline=self._baseline,
            n=self._n,
            per_session=scores,
            baseline_available=True,
            failures=failures,
        )
