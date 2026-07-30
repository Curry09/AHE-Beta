# Spec-0032/T4：需求面编排——生成段两拍（triage 分片∥divergent → synthesize）→ Owner 准入；dev 拍退役。
"""闭环编排 orchestrator（需求面）：a（用户产 report+体感）→ 生成段两拍（第一拍 triage 分片∥
divergent、第二拍 synthesize）→ Owner 唯一准入（打 openagents 交接令牌）→ c（回灌 main SHA）。

交付面（Spec-0032）不在本进程内：Owner 准入的票由 OpenAgents vigil（常驻子进程，run.py 托管）
level-triggered 接手——分支/PR/CI/评审/合并全在交付面完成，票何时出现何时接，两面无需同步。
本编排因此不再有 b 段 dev 拍；c 步语义原样（spec-0007）：回灌 = harness 仓 main 当前 HEAD SHA
纯观测游标，谁推进 main 都兼容（现在的推进者是 vigil 的 merge）。

纯 trunk 语义不变：每局会话开始解析 main 当前 HEAD SHA、按该 SHA launch（会话级快照，harness 不在
脚下变）；交付面 merge 落 main 后，下一局自然解析到前进的 HEAD（对用户永远「最新 main」）。

生成段两拍（Spec-0029）：triage 分片与 divergent 都只依赖 a 段产物（report / 会话证据）→ 同拍并行；
synthesize 要看本轮新升的 from-triage 提案 → 第二拍。生成器产出全为不可领 proposal（重复无害、
分片自由），去重/合并/准入统一由 Owner 每轮一次批量裁决。
"""

from __future__ import annotations

import subprocess
import tempfile
import traceback
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol

from auto_designer.designer.designer import Designer
from auto_designer.designer.divergent import Divergent
from auto_designer.harness.interface import HarnessInterface
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.models import Persona, SeedScenario
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.workspace import materialize as materialize_workspace

type SessionPair = tuple[Persona, SeedScenario]
type SessionPlan = Sequence[SessionPair] | Callable[[], Sequence[SessionPair]]


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
        fixed_set: SessionPlan,
        run_session_fn: SessionRunner,
        initial_ref: str,
        triagers: list | None = None,
        designers: list[Designer] | None = None,
        divergents: list[Divergent] | None = None,
        owner: object | None = None,
        on_round_start: Callable[[int], None] | None = None,
        on_round_end: Callable[[int, str], None] | None = None,
        max_parallel_users: int = 1,
        integrity_guard: Callable[[], None] | None = None,
    ) -> None:
        self._launcher = launcher
        self._harness_repo = harness_repo  # Spec-0007/T2：解析 main HEAD SHA 用的 harness 仓
        # 固定列表 = 每轮同一套；callable = 每轮重新抽（如有放回随机 persona×task）。
        self._fixed_set = fixed_set
        # 生成段两拍：第一拍 triage 分片 ∥ divergent；第二拍 synthesize；然后 Owner 唯一准入。
        self._triagers = triagers or []
        self._designers = designers or []
        self._divergents = divergents or []
        # Owner（Spec-0029/T6，恒 1）：None = 跳过准入段（提案积压，向后兼容旧测/无 Owner 场景）。
        self._owner = owner
        self._run_session = run_session_fn
        self._initial_ref = initial_ref  # 跟踪的主干分支名（trunk = "main"），每局解析其 HEAD SHA
        # 轮次观测回调（可选）：round 从 1 起；end 时携带本轮 main 最新 SHA。看板运行态由此得知轮数。
        self._on_round_start = on_round_start
        self._on_round_end = on_round_end
        # Spec-0017/T3：a 段用户会话并发度（并发单元=整局会话）。默认 1 = 与旧串行行为等价。
        # 注：生成段在同轮内线程池并行（只读 harness + 写 tracker），不碰 git push。
        self._max_parallel_users = max(1, max_parallel_users)
        # Spec-0021/T1：编排仓完整性绊线（可选）。每轮末调用一次——本进程内 agent（生成器/Owner）
        # 或同机交付面 agent 逃逸改动编排仓即抛错中止本轮（fail-closed）。None 则跳过。
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
        for persona, scenario in self._session_plan():
            try:
                if scenario.workspace is not None:
                    workspace_dir = materialize_workspace(scenario.workspace)
                    # Spec-0009/T3：materialize 之后、launch 之前按 scenario.workspace.setup 备好依赖
                    # （约定建 per-workspace .venv）——两侧共享的这个目录开跑前就绪。
                    ensure_deps(workspace_dir, scenario.workspace)
                else:
                    workspace_dir = tempfile.mkdtemp(prefix="shared_ws_")
            except Exception:  # noqa: BLE001
                # 单局 clone/setup 失败（如老仓 pip 装不上）不废整轮——记日志跳过，其余会话继续。
                print(
                    f"[orchestrator] 备工作区失败（persona={persona.identity}），"
                    "跳过该局，同轮其余会话继续："
                )
                traceback.print_exc()
                continue
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

        # 生成段·第一拍（Spec-0029/T8）：triage 分片 ∥ divergent，同一线程池并行。
        # 二者都只依赖 a 段产物（triage 吃 report、divergent 吃会话证据）、互不依赖；产出全为不可领
        # proposal（重复无害，判重归 Owner）→ 分片自由（第 k 个 triager 处理 pending[k::n]）。
        # 单个生成器崩溃记日志跳过、不废整轮。
        beat1: list[tuple[str, Callable[[], object]]] = []
        n_triagers = len(self._triagers)
        for idx, triager in enumerate(self._triagers):
            beat1.append(
                (
                    f"triage[{idx}]",
                    (lambda t=triager, k=idx: t.triage_once(shard=(k, n_triagers))),
                )
            )
        for divergent in self._divergents:
            beat1.append(("divergent", divergent.propose_once))
        self._run_parallel(beat1)

        # 生成段·第二拍：synthesize（跑在 triage 全部收尾之后——要看本轮新升的 from-triage 提案，
        # 结构综合不滞后一轮）。通常 0..1 个；多个也并行无妨（产出仍是提案）。
        beat2: list[tuple[str, Callable[[], object]]] = [
            ("synthesize", designer.propose_once) for designer in self._designers
        ]
        self._run_parallel(beat2)

        # Owner 唯一准入（Spec-0029/T6）：每轮一次批量裁决 proposal → ready/merged/declined/hold。
        # 崩溃记日志跳过（提案留存、下轮再审），不废整轮。
        if self._owner is not None:
            try:
                self._owner.admit_once()
            except Exception:  # noqa: BLE001
                print("[orchestrator] owner 准入异常，跳过，本轮继续：")
                traceback.print_exc()

        # 交付面（Spec-0032/T4）：不在本进程——Owner 打的 openagents 交接令牌由常驻 vigil 发现并
        # 推进到 PR/合并。这里只剩每轮一次的编排仓完整性绊线（Spec-0021，fail-closed）。
        if self._integrity_guard is not None:
            self._integrity_guard()

        # c：回灌 = main 当前最新 HEAD SHA（纯观测游标；交付面尚未合并时与本轮起始 SHA 相同，闭环不中断）。
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

    def _session_plan(self) -> Sequence[SessionPair]:
        """本轮要跑的 (persona, scenario) 列表；fixed_set 为 callable 时每轮重抽。"""
        plan = self._fixed_set
        return plan() if callable(plan) else plan

    @staticmethod
    def _run_parallel(jobs: list[tuple[str, Callable[[], object]]]) -> None:
        """线程池并行跑一拍生成器；单个崩溃记 traceback 跳过（产物是非约束提案，丢一路不废整轮）。"""
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {pool.submit(fn): name for name, fn in jobs}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                except Exception:  # noqa: BLE001
                    print(f"[orchestrator] {name} 异常，跳过，本轮继续：")
                    traceback.print_exc()

    def _resolve_head(self, *, ref: str) -> str:
        """解析 harness 仓某 ref（trunk 下恒为 main）的当前 HEAD commit SHA；非法 ref 抛 RuntimeError。

        Spec-0033/T3：先 fetch origin 再**优先解析 origin/<ref>**——spec-0032 后推进 main 的是 Gitea
        上的 server-side merge，本地 main 停在 seed 不再是真身；fetch 同时把远端对象取回本地，launcher
        按该 SHA checkout 才解析得到。无 origin（Fake/单仓测试）或 fetch 失败（离线）→ 退化本地 <ref>，
        行为与旧实现等价；fetch 失败只告警不抛——观测游标宁可停滞也不废轮。
        """
        remotes = subprocess.run(
            ["git", "-C", self._harness_repo, "remote"], capture_output=True, text=True
        ).stdout.split()
        if "origin" in remotes:
            fetched = subprocess.run(
                ["git", "-C", self._harness_repo, "fetch", "origin", ref],
                capture_output=True,
                text=True,
            )
            if fetched.returncode != 0:
                print(
                    f"[orchestrator] fetch origin {ref} 失败（游标可能停滞）："
                    f"{fetched.stderr.strip()[:200]}"
                )
        for candidate in (f"refs/remotes/origin/{ref}", ref):
            result = subprocess.run(
                ["git", "-C", self._harness_repo, "rev-parse", "--verify", f"{candidate}^{{commit}}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        raise RuntimeError(f"解析 main ref {ref!r} 失败：{result.stderr[:200]}")
