"""闭环编排 orchestrator（spec-0003/T6）：把 a（用户产 issue+体感）→ b（开发改+门禁+发版）→ c（回灌）串成可重复轮次。

run_round 输入输出皆为 release_ref，把「版本回灌」显式化为函数签名、无隐藏状态。顺序单轮（a 全跑完再 b），
MVP 不做流水线。门禁只用体感，benchmark 不进入控制流。可恢复运行与 checkpoint 由 spec-0004 在外层包裹，
本编排保持纯逻辑（run_session/release 等部件全部依赖注入，便于 mock 整轮）。
"""

from __future__ import annotations

from collections.abc import Callable

from auto_designer.dev.developer_agent import DeveloperAgent
from auto_designer.dev.release import ReleaseResult
from auto_designer.dev.test_agent import SessionRunner, TestAgent, Verdict
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.models import Persona, SeedScenario
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# 发版偏函数：(candidate_branch, verdict, issue_number) -> ReleaseResult（绑定 harness_repo/tracker）。
ReleaseFn = Callable[[str, Verdict, int | None], ReleaseResult]


class Orchestrator:
    """把 a→b→c 串成可重复进化轮次。各部件依赖注入。"""

    def __init__(
        self,
        launcher: HarnessLauncher,
        fixed_set: list[tuple[Persona, SeedScenario]],
        tracker: IssueTracker,
        store: SessionStore,
        developer_agents: list[DeveloperAgent],
        test_agent: TestAgent,
        release_fn: ReleaseFn,
        run_session_fn: SessionRunner,
        initial_ref: str,
    ) -> None:
        self._launcher = launcher
        self._fixed_set = fixed_set
        self._tracker = tracker
        self._store = store
        self._developers = developer_agents
        self._test = test_agent
        self._release = release_fn
        self._run_session = run_session_fn
        self._initial_ref = initial_ref

    def run_round(self, release_ref: str) -> str:
        # a：固定集每个 (persona, scenario) 用 release 版 harness 跑一局，产 issue（→tracker）+ 体感（→store）。
        for persona, scenario in self._fixed_set:
            harness = self._launcher.launch(release_ref)
            self._run_session(persona, scenario, harness)

        # b：多个开发者依次各领一条不同 issue 改 harness。每个候选过门禁后即发版、release 前进，
        #    下一个开发者从已前进的 release 切分支（避免两分支同改 main.md 合并冲突）。
        ref = release_ref
        attempted: set[int] = set()
        for developer in self._developers:
            dev = developer.work_one(attempted)
            if dev.issue_number is not None:
                attempted.add(dev.issue_number)  # 占位，后续 dev 不再领这条
            if dev.issue_number is None or not dev.changed or dev.branch is None:
                continue  # 无可领 issue / 无改动 → 该 dev 本轮无候选
            verdict = self._test.evaluate(dev.branch)
            result = self._release(dev.branch, verdict, dev.issue_number)
            if result.released and result.tag:
                ref = result.tag  # 过门禁则回灌新 tag，链式推进

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
