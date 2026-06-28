# Spec-0007/T2：去 release 链 + 会话级 main SHA 快照回灌。
"""闭环编排 orchestrator：a（用户产 issue+体感）→ b（开发者 agent 直推 main）→ c（回灌 main SHA）。

纯 trunk（单 main）：去掉 release_ref 链——run_round 不再把 outcome.tag 链式回灌。每局会话开始解析
harness 仓 **main 当前 HEAD SHA**、按该 SHA launch（launcher 已按 SHA checkout → 单会话内 harness 不在
脚下变 = 会话级快照）。dev 直推 main 后，下一局自然解析到更新后的 main HEAD（对用户永远「最新 main」）。
回灌语义从「release 链」简化为「main 最新 SHA」（纯观测游标，不据此 pin——trunk 永远跟 live main）。

无体感门禁：开发者 agent（带 git 工具）领 issue 后自己改 harness、commit、打 vK tag、push main，直接
推进（体感退化为观测、benchmark held-out，坏 commit 靠后续多轮迭代回正——梯度下降式）。多 dev 串行各领
不同 issue。各部件依赖注入，便于 mock 整轮。
"""

from __future__ import annotations

import subprocess
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
        harness_repo: str,
        fixed_set: list[tuple[Persona, SeedScenario]],
        developer_agents: list[AgenticDeveloper],
        run_session_fn: SessionRunner,
        initial_ref: str,
    ) -> None:
        self._launcher = launcher
        self._harness_repo = harness_repo  # Spec-0007/T2：解析 main HEAD SHA 用的 harness 仓
        self._fixed_set = fixed_set
        self._developers = developer_agents
        self._run_session = run_session_fn
        self._initial_ref = initial_ref  # 跟踪的主干分支名（trunk = "main"），每局解析其 HEAD SHA

    def run_round(self, ref: str) -> str:
        # Spec-0007/T2：传入的 ref 仅为「上一轮观测游标」透传（供 harbor runner 的 checkpoint 续跑链），
        # trunk 永远跟 live main、不据此 pin——本轮起始解析 main 当前 HEAD SHA 作会话级快照锚点。
        sha = self._resolve_head(ref=self._initial_ref)

        # a：固定集每个 (persona, scenario) 按该 main SHA launch 跑一局，产 issue（→tracker）+ 体感（→store）。
        #    launcher 按 SHA checkout → 同一会话内多轮 send 跑同一 SHA 快照，harness 不在脚下变。
        for persona, scenario in self._fixed_set:
            harness = self._launcher.launch(sha)
            self._run_session(persona, scenario, harness)

        # b：多个开发者 agent 依次各领一条不同 issue，自主改 harness 直推 main（无 branch/merge/门禁）。
        attempted: set[int] = set()
        for developer in self._developers:
            outcome = developer.work_one(attempted)
            if outcome.issue_number is not None:
                attempted.add(outcome.issue_number)

        # c：回灌 = dev 推进后 main 的最新 HEAD SHA（观测游标；无 dev 推进则与本轮起始 SHA 相同，闭环不中断）。
        return self._resolve_head(ref=self._initial_ref)

    def run(self, n_rounds: int) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")
        refs: list[str] = []
        ref = self._initial_ref  # 起始游标 = main 分支名；首轮 run_round 即解析其 HEAD SHA
        for _ in range(n_rounds):
            ref = self.run_round(ref)  # 返回本轮 main 最新 SHA（观测）；不参与 trunk 解析
            refs.append(ref)
        return refs

    def _resolve_head(self, *, ref: str) -> str:
        """解析 harness 仓某 ref（trunk 下恒为 main）的当前 HEAD commit SHA；非法 ref 抛 RuntimeError。"""
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"解析 main ref {ref!r} 失败：{result.stderr[:200]}")
        return result.stdout.strip()
