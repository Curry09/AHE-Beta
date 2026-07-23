# Spec-0007/T2：去 release 链 + 会话级 main SHA 快照回灌。
"""闭环编排 orchestrator：a（用户产 issue+体感）→ d（创新者综合全局产结构性提案，可选）
→ b（开发者 agent 直推 main）→ c（回灌 main SHA）。

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
import tempfile
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from auto_designer.designer.designer import Designer
from auto_designer.dev.agentic_developer import AgenticDeveloper
from auto_designer.harness.interface import HarnessInterface
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.models import Persona, SeedScenario
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.workspace import materialize as materialize_workspace


class SessionRunner(Protocol):
    """跑一局会话：(persona, scenario, harness) -> 任意（产物由实现落盘/提交，编排不关心返回）。

    Spec-0008/T1 v2：可选 keyword `workspace_dir`——orchestrator 每局先 materialize 的共享工作区，
    既经 launcher 注入 harness，也由此传给会话实现绑定内层 client（缺省 None 退化为今天行为）。
    """

    def __call__(
        self,
        persona: Persona,
        scenario: SeedScenario,
        harness: HarnessInterface,
        *,
        workspace_dir: str | None = None,
    ) -> object: ...


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
        triagers: list | None = None,
        designers: list[Designer] | None = None,
        on_round_start: Callable[[int], None] | None = None,
        on_round_end: Callable[[int, str], None] | None = None,
        max_parallel_users: int = 1,
        integrity_guard: Callable[[], None] | None = None,
    ) -> None:
        self._launcher = launcher
        self._harness_repo = harness_repo  # Spec-0007/T2：解析 main HEAD SHA 用的 harness 仓
        self._fixed_set = fixed_set
        self._developers = developer_agents
        # Spec-0025/T6：d 段两 agent——先 triage（把本轮新 raw issue 规范化）、再 synthesize（在已
        # triaged backlog 上产 RFC）。都在 b 之前，让 triaged issue + RFC 一起进 dev 可领集合。
        self._triagers = triagers or []
        # synthesize（可选）：在 a、triage 之后、b 之前综合全局产结构性 RFC，供开发者领取。
        self._designers = designers or []
        self._run_session = run_session_fn
        self._initial_ref = initial_ref  # 跟踪的主干分支名（trunk = "main"），每局解析其 HEAD SHA
        # 轮次观测回调（可选）：round 从 1 起；end 时携带本轮 main 最新 SHA。看板运行态由此得知轮数。
        self._on_round_start = on_round_start
        self._on_round_end = on_round_end
        # Spec-0017/T3：a 段用户会话并发度（并发单元=整局会话）。默认 1 = 与旧串行行为等价；
        # d/b 段始终串行（同仓 push + 全局 env 的固有约束，见 spec-0017 Non-goal）。
        self._max_parallel_users = max(1, max_parallel_users)
        # Spec-0021/T1：编排仓完整性绊线（可选）。b 段后调用，dev agent 逃逸出沙箱改动编排仓即抛错
        # 中止本轮（fail-closed）。None 则跳过，退化为今天行为。
        self._integrity_guard = integrity_guard

    def run_round(self, ref: str) -> str:
        # Spec-0007/T2：传入的 ref 仅为「上一轮观测游标」透传（供 harbor runner 的 checkpoint 续跑链），
        # trunk 永远跟 live main、不据此 pin——本轮起始解析 main 当前 HEAD SHA 作会话级快照锚点。
        sha = self._resolve_head(ref=self._initial_ref)

        # a：固定集每个 (persona, scenario) 按该 main SHA launch 跑一局，产 issue（→tracker）+ 体感（→store）。
        #    launcher 按 SHA checkout → 同一会话内多轮 send 跑同一 SHA 快照，harness 不在脚下变。
        #    Spec-0008/T1 v2：每局先备一份**共享工作区**，同一目录既经 launcher 注入 harness
        #    （SANDBOX_WORK_DIR）又传给会话绑定内层 client——harness 改、用户 agent 同目录核实。
        #    git/fixture 型种子 materialize + ensure_deps；纯文本卡（workspace=None）也开一个空的
        #    scratch（每局新建、隔离），确保用户 agent 落到 harness 同一工作目录真核实，而非只凭
        #    harness 回复"嘴上验"（否则无环境时会脑补"测试通过"污染体感）。
        #    Spec-0017/T3：拆两阶段——阶段一串行备工作区（materialize/ensure_deps 走 git clone 缓存
        #    等共享资源，前移规避并发竞争）；阶段二线程池并行跑会话（launch + run_session 一整包，
        #    并发单元=整局会话，信封内部时序不动）。max_parallel_users=1 时行为与旧串行等价。
        prepared: list[tuple[Persona, SeedScenario, str]] = []
        for persona, scenario in self._fixed_set:
            if scenario.workspace is not None:
                workspace_dir = materialize_workspace(scenario.workspace)
                # Spec-0009/T3：materialize 之后、launch 之前按 scenario.workspace.setup 备好依赖
                # （约定建 per-workspace .venv）——两侧共享的这个目录开跑前就绪。
                ensure_deps(workspace_dir, scenario.workspace)
            else:
                workspace_dir = tempfile.mkdtemp(prefix="shared_ws_")
            prepared.append((persona, scenario, workspace_dir))

        def _one_session(persona: Persona, scenario: SeedScenario, workspace_dir: str) -> None:
            harness = self._launcher.launch(sha, workspace_dir=workspace_dir)
            self._run_session(persona, scenario, harness, workspace_dir=workspace_dir)

        if prepared:
            with ThreadPoolExecutor(
                max_workers=min(len(prepared), self._max_parallel_users)
            ) as pool:
                futures = {pool.submit(_one_session, p, s, ws): p for p, s, ws in prepared}
                for fut in as_completed(futures):
                    try:
                        fut.result()
                    except Exception:  # noqa: BLE001
                        # 0012 后 harness 故障已在会话内转 [harness error] 信号（不上抛），这里只剩
                        # launch/落盘类意外——单会话失败记日志跳过，不废整轮、不阻塞其余会话。
                        print(
                            f"[orchestrator] 用户会话异常（persona="
                            f"{futures[fut].identity}），跳过该局，同轮其余会话继续："
                        )
                        traceback.print_exc()

        # d1（triage，Spec-0025/T6）：把本轮新产的 raw issue（+ 上轮 carryover 里仍 needs-triage 的）
        #    逐条规范化（分类/定位/去重/驳回），就地增补为 triaged。跑在 synthesize 之前——让 synthesize
        #    的输入是已 groomed 的 backlog。无 triager 时跳过。
        for triager in self._triagers:
            triager.triage_once()

        # d2（synthesize，可选）：在**已 triaged** backlog（含跨轮积压）+ 体感曲线上综合产结构性 RFC
        #    （打 RFC 标签）写回 tracker。跑在 b 之前，让 RFC 与 triaged issue 一起进 dev 可领集合；
        #    synthesize 不碰 git、不改文件，只提方向。无 designer 时整段跳过。
        for designer in self._designers:
            designer.propose_once()

        # b：多个开发者 agent 依次各领一条不同 issue，自主改 harness 直推 main（无 branch/merge/门禁）。
        attempted: set[int] = set()
        for developer in self._developers:
            outcome = developer.work_one(attempted)
            if outcome.issue_number is not None:
                attempted.add(outcome.issue_number)

        # Spec-0021/T1：b 段后校验编排仓未被 dev agent 触碰（逃逸出沙箱改文件/提交/推送）。
        # 抛 RepoIntegrityError 即中止本轮并传播出 run()——安全事件 fail-closed，不继续跑累积污染。
        if self._integrity_guard is not None:
            self._integrity_guard()

        # c：回灌 = dev 推进后 main 的最新 HEAD SHA（观测游标；无 dev 推进则与本轮起始 SHA 相同，闭环不中断）。
        return self._resolve_head(ref=self._initial_ref)

    def run(self, n_rounds: int) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")
        refs: list[str] = []
        ref = self._initial_ref  # 起始游标 = main 分支名；首轮 run_round 即解析其 HEAD SHA
        for i in range(n_rounds):
            if self._on_round_start is not None:
                self._on_round_start(i + 1)
            ref = self.run_round(ref)  # 返回本轮 main 最新 SHA（观测）；不参与 trunk 解析
            refs.append(ref)
            if self._on_round_end is not None:
                self._on_round_end(i + 1, ref)
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
