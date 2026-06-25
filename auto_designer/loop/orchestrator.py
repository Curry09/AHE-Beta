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
        developer_agent: DeveloperAgent,
        test_agent: TestAgent,
        release_fn: ReleaseFn,
        run_session_fn: SessionRunner,
        initial_ref: str,
    ) -> None:
        self._launcher = launcher
        self._fixed_set = fixed_set
        self._tracker = tracker
        self._store = store
        self._developer = developer_agent
        self._test = test_agent
        self._release = release_fn
        self._run_session = run_session_fn
        self._initial_ref = initial_ref

    def run_round(self, release_ref: str) -> str:
        # a：固定集每个 (persona, scenario) 用 release 版 harness 跑一局，产 issue（→tracker）+ 体感（→store）。
        for persona, scenario in self._fixed_set:
            harness = self._launcher.launch(release_ref)
            self._run_session(persona, scenario, harness)

        # b：开发者取一条 issue 改 harness；无 issue/无改动 → 本轮无候选、不发版。
        dev = self._developer.work_one()
        if dev.issue_number is None or not dev.changed or dev.branch is None:
            return release_ref
        verdict = self._test.evaluate(dev.branch)
        result = self._release(dev.branch, verdict, dev.issue_number)

        # c：发版则回灌新 tag，否则沿用旧 ref（闭环不因单轮未过门禁而中断）。
        if result.released and result.tag:
            return result.tag
        return release_ref

    def run(self, n_rounds: int) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")
        refs: list[str] = []
        ref = self._initial_ref
        for _ in range(n_rounds):
            ref = self.run_round(ref)  # 上一轮返回值喂下一轮（闭环 c 段）
            refs.append(ref)
        return refs
