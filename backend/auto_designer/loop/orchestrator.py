"""闭环编排 orchestrator：a（用户产 issue+体感）→ b（开发者 agent 自主改+发版）→ c（回灌）。

无体感门禁：开发者 agent（带 git 工具）领 issue 后自己改 harness、commit、merge release、打 tag、
push Gitea，直接发版（体感退化为观测、benchmark held-out，多轮迭代回正——梯度下降式）。
run_round 输入输出皆为 release_ref，把版本回灌显式化为函数签名、无隐藏状态。多 dev 串行各领不同 issue，
后者基于前者已发版的 release。各部件依赖注入，便于 mock 整轮。
"""

from __future__ import annotations

from collections.abc import Callable

from auto_designer.dev.agentic_developer import AgenticDeveloper
from auto_designer.harness.interface import HarnessInterface
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.models import Persona, SeedScenario

# 跑一局会话：(persona, scenario, harness) -> 任意（产物由实现落盘/提交，编排不关心返回）。
SessionRunner = Callable[[Persona, SeedScenario, HarnessInterface], object]


class Orchestrator:
    """把 a→b→c 串成可重复进化轮次。各部件依赖注入。"""

    def __init__(
        self,
        launcher: HarnessLauncher,
        fixed_set: list[tuple[Persona, SeedScenario]],
        developer_agents: list[AgenticDeveloper],
        run_session_fn: SessionRunner,
        initial_ref: str,
    ) -> None:
        self._launcher = launcher
        self._fixed_set = fixed_set
        self._developers = developer_agents
        self._run_session = run_session_fn
        self._initial_ref = initial_ref

    def run_round(self, release_ref: str) -> str:
        # a：固定集每个 (persona, scenario) 用 release 版 harness 跑一局，产 issue（→tracker）+ 体感（→store）。
        for persona, scenario in self._fixed_set:
            harness = self._launcher.launch(release_ref)
            self._run_session(persona, scenario, harness)

        # b：多个开发者 agent 依次各领一条不同 issue，自主改 harness + 发版（无门禁）。
        #    后者从前者已发版的 release 切，避免两分支同改 main.md 冲突。
        ref = release_ref
        attempted: set[int] = set()
        for developer in self._developers:
            outcome = developer.work_one(attempted)
            if outcome.issue_number is not None:
                attempted.add(outcome.issue_number)
            if outcome.released and outcome.tag:
                ref = outcome.tag  # 直接发版 → 回灌新 tag，链式推进

        # c：返回本轮最终 release_ref（无发版则沿用旧 ref，闭环不中断）。
        return ref

    def run(self, n_rounds: int) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")
        refs: list[str] = []
        ref = self._initial_ref
        for _ in range(n_rounds):
            ref = self.run_round(ref)  # 上一轮返回值喂下一轮（闭环 c 段）
            refs.append(ref)
        return refs
