# Spec-0032/T4：需求面编排——生成段两拍（triage 分片∥divergent → synthesize）→ Owner 准入。
# Spec-0050/T3：非末轮准入后等本轮 admitted 票终态；末轮只跑用户，不再需求/交付。
"""闭环编排 orchestrator（需求面）。

非末轮：用户测当前 main → 生成两拍 → Owner 准入 → 等待本轮 admitted 票终态 → 回灌 sealed SHA。
末轮：只跑用户，不调生成/Owner/交付闸。卡死抛 RoundDeliveryBlocked，不开下一轮用户。
"""

from __future__ import annotations

import dataclasses
import subprocess
import threading
import traceback
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from auto_designer.designer.designer import Designer
from auto_designer.designer.divergent import Divergent
from auto_designer.harness.interface import HarnessInterface
from auto_designer.harness.launcher import HarnessLauncher
from auto_designer.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from auto_designer.loop.round_gate import RoundDeliveryBlocked, classify_issue, wait_round_delivery
from auto_designer.models import OpenIssue, Persona, SeedScenario
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.sim.deps import ensure_deps
from auto_designer.user.sim.runtime import WorkspaceRuntime, as_runtime, make_empty_runtime
from auto_designer.user.sim.workspace import materialize as materialize_workspace

type SessionPair = tuple[Persona, SeedScenario]
type SessionPlan = Sequence[SessionPair] | Callable[[], Sequence[SessionPair]]


def _result_payload(value: Any) -> Any:
    """Convert role/session returns into deterministic JSON receipts."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _result_payload(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _result_payload(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_result_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    for method_name in ("model_dump", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            return _result_payload(method())
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _issue_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("name") or "") if isinstance(item, Mapping) else str(item) for item in value
    ]


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
        workspace_dir: WorkspaceRuntime | None = None,
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
        fetch_issue: Callable[[int], Mapping[str, Any]] | None = None,
        wait_delivery: Callable[..., None] | None = None,
        recovery: RecoveryStore | None = None,
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
        # Spec-0050/T3：读单票状态供交付闸；测试可注入 wait_delivery 避免真轮询。
        self._fetch_issue = fetch_issue
        self._wait_delivery = wait_delivery
        # Spec-0064/T2: when present, run_round delegates to the durable stage
        # machine.  None preserves the established in-process behavior.
        self._recovery = recovery

    @property
    def recovery_enabled(self) -> bool:
        return self._recovery is not None

    @property
    def recovery_revision(self) -> int:
        return self._recovery.revision if self._recovery is not None else 0

    def refresh_recovery(self) -> None:
        """Reopen the ledger after Harbor restored its containing checkpoint."""
        if self._recovery is None:
            return
        identity = RecoveryIdentity(**self._recovery.snapshot()["identity"])
        self._recovery = RecoveryStore.open(root=self._recovery.root, identity=identity)

    def recovery_phase(self, *, round_no: int) -> str:
        """Return the first incomplete durable stage for the legacy RunState projection."""
        if self._recovery is None:
            return "a"
        round_state = self._recovery.round_state(round_no=round_no)
        if round_state is None:
            return "round_started"
        order = (
            "round_started",
            "users",
            "triage",
            "divergent",
            "designer",
            "owner",
            "delivery_wait",
            "round_sealed",
        )
        return next(
            (
                stage
                for stage in order
                if (round_state.get("stages") or {}).get(stage, {}).get("status") != "completed"
            ),
            "completed",
        )

    def run_round(self, ref: str, *, deliver: bool = True, round_no: int | None = None) -> str:
        if self._recovery is not None:
            number = round_no or current_usage_context().round_no
            if number is None:
                raise ValueError("recoverable run_round requires round_no or a bound round context")
            return self._run_recoverable_round(ref=ref, deliver=deliver, round_no=number)
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
        prepared: list[tuple[Persona, SeedScenario, WorkspaceRuntime]] = []
        planned = list(self._session_plan())
        for persona, scenario in planned:
            try:
                if scenario.workspace is not None:
                    workspace_dir = as_runtime(
                        materialize_workspace(scenario.workspace), owns_tmp=True
                    )
                    # Spec-0009/T3：materialize 之后、launch 之前按 scenario.workspace.setup 备好依赖
                    # （约定建 per-workspace .venv）——两侧共享的这个目录开跑前就绪。
                    ensure_deps(workspace_dir, scenario.workspace)
                else:
                    workspace_dir = make_empty_runtime()
            except Exception:  # noqa: BLE001
                # 单局 clone/setup 失败（如老仓 pip 装不上）先记日志跳过；若整轮都失败，
                # 下面的 all-user-sessions-failed 闸会阻止本轮继续。
                print(
                    f"[orchestrator] 备工作区失败（persona={persona.identity}），"
                    "跳过该局，同轮其余会话继续："
                )
                traceback.print_exc()
                continue
            prepared.append((persona, scenario, workspace_dir))

        successful_sessions = 0
        session_lock = threading.Lock()

        def _one_session(
            persona: Persona, scenario: SeedScenario, workspace_dir: WorkspaceRuntime
        ) -> None:
            nonlocal successful_sessions
            try:
                harness = self._launcher.launch(sha, workspace_dir=workspace_dir)
                self._run_session(persona, scenario, harness, workspace_dir=workspace_dir)
                with session_lock:
                    successful_sessions += 1
            finally:
                workspace_dir.close()

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

        if planned and successful_sessions == 0:
            raise RoundDeliveryBlocked(numbers=[], reason="all-user-sessions-failed")

        # Spec-0050/T3：末轮只测用户，跳过提案/准入/交付闸。
        if not deliver:
            if self._integrity_guard is not None:
                self._integrity_guard()
            return self._resolve_head(ref=self._initial_ref)

        # 生成段·第一拍（Spec-0029/T8）：triage 分片 ∥ divergent，同一线程池并行。
        # 二者都只依赖 a 段产物（triage 吃 report、divergent 吃会话证据）、互不依赖；产出全为不可领
        # proposal（PM 独立交给 Owner，Designer 仅吸收非 PM 来源）→ 分片自由。
        # 单个生成器崩溃记日志跳过、不废整轮。
        beat1: list[tuple[str, Callable[[], object]]] = []
        n_triagers = len(self._triagers)
        triage_shards: list[list] | None = None
        if n_triagers and hasattr(self._triagers[0], "snapshot_pending"):
            # Snapshot once before any triager can mutate report labels.  Passing
            # explicit subsets makes ownership stable for the whole parallel beat.
            pending = self._triagers[0].snapshot_pending()
            triage_shards = [pending[idx::n_triagers] for idx in range(n_triagers)]
        for idx, triager in enumerate(self._triagers):
            if triage_shards is None:
                beat1.append(
                    (
                        f"triage[{idx}]",
                        (lambda t=triager, k=idx: t.triage_once(shard=(k, n_triagers))),
                    )
                )
            else:
                beat1.append(
                    (
                        f"triage[{idx}]",
                        (lambda t=triager, p=triage_shards[idx]: t.triage_once(pending=p)),
                    )
                )
        for divergent in self._divergents:
            beat1.append(("divergent", divergent.propose_once))
        self._run_parallel(beat1)

        # 生成段·第二拍：synthesize（跑在 triage 全部收尾之后——要看本轮新升的 from-triage 提案，
        # 结构综合不滞后一轮）。启用分组时，入口提供一个协调器：全池只分类一次，
        # 再由已有 Designer workers 领取互斥组，避免多个 worker 各自处理整池。
        beat2: list[tuple[str, Callable[[], object]]] = [
            ("synthesize", designer.propose_once) for designer in self._designers
        ]
        self._run_parallel(beat2)

        # Owner 汇合独立 PM 与交付路线，标注交付重叠但保留独立验收；Designer 仅处理非 PM covers。
        # Owner 是唯一准入权威；其失败必须阻断本轮，不能以空等待集伪装成功。
        admitted: list[int] = []
        if self._owner is not None:
            try:
                outcome = self._owner.admit_once()
                admitted = [int(n) for n in (getattr(outcome, "admitted", None) or [])]
            except Exception as exc:  # noqa: BLE001
                print("[orchestrator] owner 准入异常，跳过，本轮继续：")
                traceback.print_exc()
                # Owner is the sole admission authority.  Continuing with an
                # empty wait set would incorrectly mark the round successful
                # and start the next user round with proposals still blocked.
                raise RoundDeliveryBlocked(
                    numbers=[], reason="owner-failed:admission did not complete"
                ) from exc

        # Spec-0050/T3：等本轮准入票终态。空名单立即成功。卡死向上抛，不开下一轮用户。
        self._await_round_delivery(numbers=admitted)

        # 编排仓完整性绊线（Spec-0021，fail-closed）。
        if self._integrity_guard is not None:
            self._integrity_guard()

        # 闸成功后的 origin/main = 本轮 sealed SHA（空等待集时可能仍是 user SHA）。
        return self._resolve_head(ref=self._initial_ref)

    def run(self, n_rounds: int) -> list[str]:
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")
        refs: list[str] = []
        ref = self._initial_ref  # 起始游标 = main 分支名；首轮 run_round 即解析其 HEAD SHA
        for i in range(n_rounds):
            is_last = i == n_rounds - 1
            with bind_usage_context(round_no=i + 1):
                if self._on_round_start is not None:
                    self._on_round_start(i + 1)
                # Spec-0050/T3：末轮 deliver=False。闸抛错则本循环不再进入下一轮。
                if getattr(self, "_recovery", None) is not None:
                    ref = self.run_round(ref, deliver=not is_last, round_no=i + 1)
                else:
                    ref = self.run_round(ref, deliver=not is_last)
                refs.append(ref)
                if self._on_round_end is not None:
                    self._on_round_end(i + 1, ref)
        return refs

    def _run_recoverable_round(self, *, ref: str, deliver: bool, round_no: int) -> str:
        """Spec-0064/T2: execute one round as a resumable stage DAG."""
        recovery = self._recovery
        assert recovery is not None
        saved_round = recovery.round_state(round_no=round_no)
        if saved_round is not None and saved_round.get("status") == "completed":
            sealed = str(saved_round.get("sealed_sha") or "")
            if not sealed:
                raise RecoveryConflictError(f"completed round {round_no} has no sealed SHA")
            return sealed

        if saved_round is None:
            user_sha = self._resolve_head(ref=self._initial_ref)
            planned = list(self._session_plan())
            plan_payload = [
                {"persona": persona.to_dict(), "scenario": scenario.to_dict()}
                for persona, scenario in planned
            ]
            saved_round = recovery.freeze_round(
                round_no=round_no,
                user_sha=user_sha,
                plan=plan_payload,
            )
        else:
            user_sha = str(saved_round.get("user_sha") or "")
            if not user_sha:
                raise RecoveryConflictError(f"round {round_no} has no frozen user SHA")
            planned = [
                (
                    Persona.from_dict(item["persona"]),
                    SeedScenario.from_dict(item["scenario"]),
                )
                for item in saved_round.get("plan") or []
            ]
        self._assert_commit_available(user_sha)
        self._mark_recovery_stage(
            round_no=round_no,
            stage="round_started",
            input_value={"user_sha": user_sha, "plan": saved_round.get("plan") or []},
        )
        self._run_recovery_users(round_no=round_no, user_sha=user_sha, planned=planned)

        if deliver:
            self._run_recovery_demand(round_no=round_no)
            admitted = self._run_recovery_owner(round_no=round_no)
            self._run_recovery_delivery(round_no=round_no, admitted=admitted)
            seal_dependencies = ("delivery_wait",)
        else:
            seal_dependencies = ("users",)

        if self._integrity_guard is not None:
            self._integrity_guard()
        sealed_sha = self._resolve_head(ref=self._initial_ref)
        self._assert_descendant(ancestor=user_sha, descendant=sealed_sha)
        self._mark_recovery_stage(
            round_no=round_no,
            stage="round_sealed",
            input_value={"user_sha": user_sha, "sealed_sha": sealed_sha},
            dependencies=seal_dependencies,
        )
        recovery.seal_round(round_no=round_no, sealed_sha=sealed_sha)
        return sealed_sha

    def _run_recovery_users(
        self, *, round_no: int, user_sha: str, planned: Sequence[SessionPair]
    ) -> None:
        recovery = self._require_recovery()
        if recovery.stage_status(round_no=round_no, stage="users") == "completed":
            return
        if not planned:
            self._mark_recovery_stage(
                round_no=round_no,
                stage="users",
                input_value={"sessions": []},
                dependencies=("round_started",),
            )
            return

        failures: list[str] = []
        for index, (persona, scenario) in enumerate(planned):
            key = operation_key(round_no, "users", index, persona.to_dict(), scenario.to_dict())
            input_value = {
                "index": index,
                "persona": persona.to_dict(),
                "scenario": scenario.to_dict(),
                "user_sha": user_sha,
            }
            unit = recovery.begin_unit(
                round_no=round_no,
                stage="users",
                key=key,
                input_value=input_value,
                expected_postconditions={"completed": True},
                dependencies=("round_started",),
            )
            if unit.get("status") == "completed":
                continue
            workspace_dir: WorkspaceRuntime | None = None
            try:
                load_completed = getattr(self._run_session, "load_completed_session", None)
                existing = load_completed(key) if callable(load_completed) else None
                if existing is not None:
                    recovery.save_output(
                        round_no=round_no,
                        stage="users",
                        key=key,
                        output=_result_payload(existing),
                    )
                    recovery.complete_unit(
                        round_no=round_no,
                        stage="users",
                        key=key,
                        observed_postconditions={"completed": True, "session_id": key},
                    )
                    continue
                if scenario.workspace is not None:
                    workspace_dir = as_runtime(
                        materialize_workspace(scenario.workspace), owns_tmp=True
                    )
                    ensure_deps(workspace_dir, scenario.workspace)
                else:
                    workspace_dir = make_empty_runtime()
                harness = self._launcher.launch(user_sha, workspace_dir=workspace_dir)
                with bind_usage_context(session_id=key, round_no=round_no):
                    result = self._run_session(
                        persona,
                        scenario,
                        harness,
                        workspace_dir=workspace_dir,
                    )
                recovery.save_output(
                    round_no=round_no,
                    stage="users",
                    key=key,
                    output=_result_payload(result),
                )
                recovery.complete_unit(
                    round_no=round_no,
                    stage="users",
                    key=key,
                    observed_postconditions={"completed": True},
                )
            except Exception as exc:  # noqa: BLE001
                recovery.fail_unit(
                    round_no=round_no,
                    stage="users",
                    key=key,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failures.append(key)
                traceback.print_exc()
            finally:
                if workspace_dir is not None:
                    workspace_dir.close()
        if failures:
            raise RoundDeliveryBlocked(numbers=[], reason="user-sessions-incomplete")
        recovery.complete_stage(round_no=round_no, stage="users")

    def _run_recovery_demand(self, *, round_no: int) -> None:
        recovery = self._require_recovery()
        triage_jobs: list[tuple[str, str, Any, Callable[[], object]]] = []
        n_triagers = len(self._triagers)
        pending_shards: list[list[OpenIssue]] | None = None
        if n_triagers and recovery.stage_status(round_no=round_no, stage="triage") == "pending":
            if hasattr(self._triagers[0], "snapshot_pending"):
                pending = self._triagers[0].snapshot_pending()
                pending_shards = [pending[index::n_triagers] for index in range(n_triagers)]
        for index, triager in enumerate(self._triagers):
            key = operation_key(round_no, "triage", index)
            existing = recovery.unit(round_no=round_no, stage="triage", key=key)
            if existing is not None:
                triage_input = existing["input"]
            elif pending_shards is not None:
                triage_input = {
                    "worker": index,
                    "mode": "snapshot",
                    "pending": [issue.to_dict() for issue in pending_shards[index]],
                }
            else:
                triage_input = {
                    "worker": index,
                    "mode": "shard",
                    "shard": [index, n_triagers],
                }
            if triage_input["mode"] == "snapshot":
                frozen_pending = [OpenIssue.from_dict(item) for item in triage_input["pending"]]

                def call(t=triager, p=frozen_pending):
                    return t.triage_once(pending=p)

            else:
                shard = tuple(triage_input["shard"])

                def call(t=triager, s=shard):
                    return t.triage_once(shard=s)

            triage_jobs.append((f"triage[{index}]", key, triage_input, call))
        self._run_recovery_jobs(
            round_no=round_no,
            stage="triage",
            jobs=triage_jobs,
            dependencies=("users",),
        )

        divergent_jobs = [
            (
                f"divergent[{index}]",
                operation_key(round_no, "divergent", index),
                {"worker": index},
                divergent.propose_once,
            )
            for index, divergent in enumerate(self._divergents)
        ]
        self._run_recovery_jobs(
            round_no=round_no,
            stage="divergent",
            jobs=divergent_jobs,
            dependencies=("users",),
        )

        designer_jobs = [
            (
                f"designer[{index}]",
                operation_key(round_no, "designer", index),
                {"worker": index},
                designer.propose_once,
            )
            for index, designer in enumerate(self._designers)
        ]
        self._run_recovery_jobs(
            round_no=round_no,
            stage="designer",
            jobs=designer_jobs,
            dependencies=("triage",),
        )

    def _run_recovery_owner(self, *, round_no: int) -> list[int]:
        recovery = self._require_recovery()
        round_state = recovery.round_state(round_no=round_no) or {}
        if recovery.stage_status(round_no=round_no, stage="owner") == "completed":
            return [int(number) for number in round_state.get("admitted_issue_ids") or []]
        if self._owner is None:
            recovery.set_admitted_issue_ids(round_no=round_no, issue_ids=[])
            self._mark_recovery_stage(
                round_no=round_no,
                stage="owner",
                input_value={"owner": None},
                dependencies=("divergent", "designer"),
            )
            return []
        key = operation_key(round_no, "owner")
        unit = recovery.begin_unit(
            round_no=round_no,
            stage="owner",
            key=key,
            input_value={"round": round_no},
            expected_postconditions={"completed": True},
            dependencies=("divergent", "designer"),
        )
        if unit.get("status") == "completed":
            return [int(number) for number in round_state.get("admitted_issue_ids") or []]
        try:
            outcome = self._owner.admit_once()
            admitted = sorted(set(int(n) for n in (getattr(outcome, "admitted", None) or [])))
            recovery.save_output(
                round_no=round_no,
                stage="owner",
                key=key,
                output=_result_payload(outcome),
            )
            recovery.set_admitted_issue_ids(round_no=round_no, issue_ids=admitted)
            recovery.complete_unit(
                round_no=round_no,
                stage="owner",
                key=key,
                observed_postconditions={"completed": True},
            )
            recovery.complete_stage(round_no=round_no, stage="owner")
            return admitted
        except Exception as exc:  # noqa: BLE001
            recovery.fail_unit(
                round_no=round_no,
                stage="owner",
                key=key,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise RoundDeliveryBlocked(
                numbers=[], reason="owner-failed:admission did not complete"
            ) from exc

    def _run_recovery_delivery(self, *, round_no: int, admitted: Sequence[int]) -> None:
        recovery = self._require_recovery()
        if recovery.stage_status(round_no=round_no, stage="delivery_wait") == "completed":
            return
        if not admitted:
            self._mark_recovery_stage(
                round_no=round_no,
                stage="delivery_wait",
                input_value={"issues": []},
                dependencies=("owner",),
            )
            return
        inflight: list[tuple[int, str]] = []
        for number in admitted:
            key = operation_key(round_no, "delivery", int(number))
            unit = recovery.begin_unit(
                round_no=round_no,
                stage="delivery_wait",
                key=key,
                input_value={"issue": int(number)},
                expected_postconditions={"classification": "done"},
                dependencies=("owner",),
            )
            if unit.get("status") == "completed":
                continue
            if self._fetch_issue is not None:
                snapshot = self._fetch_issue(int(number))
                classification = classify_issue(
                    state=str(snapshot.get("state") or ""),
                    labels=_issue_labels(snapshot.get("labels")),
                )
                if classification == "done":
                    recovery.complete_unit(
                        round_no=round_no,
                        stage="delivery_wait",
                        key=key,
                        observed_postconditions={"classification": "done", "issue": snapshot},
                    )
                    continue
                if classification == "blocked":
                    recovery.fail_unit(
                        round_no=round_no,
                        stage="delivery_wait",
                        key=key,
                        error="delivery terminal failure",
                        blocked=True,
                    )
                    raise RoundDeliveryBlocked(numbers=[int(number)], reason="delivery-failed")
            inflight.append((int(number), key))
        if inflight:
            try:
                self._await_round_delivery(numbers=[number for number, _ in inflight])
            except RoundDeliveryBlocked as exc:
                blocked = exc.reason != "timeout"
                for number, key in inflight:
                    recovery.fail_unit(
                        round_no=round_no,
                        stage="delivery_wait",
                        key=key,
                        error=f"delivery {exc.reason} for issue #{number}",
                        blocked=blocked,
                    )
                raise
            for number, key in inflight:
                observed: dict[str, Any] = {"classification": "done"}
                if self._fetch_issue is not None:
                    snapshot = self._fetch_issue(number)
                    classification = classify_issue(
                        state=str(snapshot.get("state") or ""),
                        labels=_issue_labels(snapshot.get("labels")),
                    )
                    if classification != "done":
                        recovery.fail_unit(
                            round_no=round_no,
                            stage="delivery_wait",
                            key=key,
                            error=f"delivery wait returned before issue #{number} was done",
                            blocked=True,
                        )
                        raise RoundDeliveryBlocked(
                            numbers=[number], reason="postcondition-mismatch"
                        )
                    observed["issue"] = snapshot
                recovery.complete_unit(
                    round_no=round_no,
                    stage="delivery_wait",
                    key=key,
                    observed_postconditions=observed,
                )
        recovery.complete_stage(round_no=round_no, stage="delivery_wait")

    def _run_recovery_jobs(
        self,
        *,
        round_no: int,
        stage: str,
        jobs: Sequence[tuple[str, str, Any, Callable[[], object]]],
        dependencies: Sequence[str],
    ) -> None:
        recovery = self._require_recovery()
        if recovery.stage_status(round_no=round_no, stage=stage) == "completed":
            return
        if not jobs:
            self._mark_recovery_stage(
                round_no=round_no,
                stage=stage,
                input_value={"jobs": []},
                dependencies=dependencies,
            )
            return
        failures: list[str] = []
        for name, key, input_value, call in jobs:
            unit = recovery.begin_unit(
                round_no=round_no,
                stage=stage,
                key=key,
                input_value=input_value,
                expected_postconditions={"completed": True},
                dependencies=dependencies,
            )
            if unit.get("status") == "completed":
                continue
            try:
                result = call()
                recovery.save_output(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    output=_result_payload(result),
                )
                recovery.complete_unit(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    observed_postconditions={"completed": True},
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[orchestrator] {name} 异常，恢复账本保留该工作项：")
                traceback.print_exc()
                recovery.fail_unit(
                    round_no=round_no,
                    stage=stage,
                    key=key,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failures.append(key)
        if failures:
            raise RoundDeliveryBlocked(numbers=[], reason=f"{stage}-incomplete")
        recovery.complete_stage(round_no=round_no, stage=stage)

    def _mark_recovery_stage(
        self,
        *,
        round_no: int,
        stage: str,
        input_value: Any,
        dependencies: Sequence[str] = (),
    ) -> None:
        recovery = self._require_recovery()
        key = operation_key(round_no, stage, "stage-marker")
        unit = recovery.begin_unit(
            round_no=round_no,
            stage=stage,
            key=key,
            input_value=input_value,
            expected_postconditions={"completed": True},
            dependencies=dependencies,
        )
        if unit.get("status") != "completed":
            recovery.complete_unit(
                round_no=round_no,
                stage=stage,
                key=key,
                observed_postconditions={"completed": True},
            )
        recovery.complete_stage(round_no=round_no, stage=stage)

    def _require_recovery(self) -> RecoveryStore:
        if self._recovery is None:
            raise RuntimeError("recovery store is not configured")
        return self._recovery

    def _assert_commit_available(self, sha: str) -> None:
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RecoveryConflictError(f"frozen user SHA is unavailable: {sha}")

    def _assert_descendant(self, *, ancestor: str, descendant: str) -> None:
        result = subprocess.run(
            ["git", "-C", self._harness_repo, "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RecoveryConflictError(
                f"remote main {descendant} does not descend from frozen user SHA {ancestor}"
            )

    def _await_round_delivery(self, *, numbers: list[int]) -> None:
        """Wait for this round's admitted issues; no-op when the wait set is empty."""
        if self._wait_delivery is not None:
            self._wait_delivery(numbers=numbers)
            return
        fetch = self._fetch_issue
        if fetch is None:
            if numbers:
                raise RuntimeError(
                    "round delivery wait needs fetch_issue when Owner admitted tickets"
                )
            return
        wait_round_delivery(numbers=numbers, fetch_issue=fetch)

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
        按该 SHA checkout 才解析得到。无 origin 或无可用远端跟踪 ref 时退化本地 <ref>；但若已有
        origin/<ref> 且本次 fetch 失败，拒绝使用可能过期的远端游标，避免静默重复旧轮次。
        """
        remotes = subprocess.run(
            ["git", "-C", self._harness_repo, "remote"], capture_output=True, text=True
        ).stdout.split()
        fetch_failed = False
        if "origin" in remotes:
            fetched = subprocess.run(
                ["git", "-C", self._harness_repo, "fetch", "origin", ref],
                capture_output=True,
                text=True,
            )
            if fetched.returncode != 0:
                fetch_failed = True
                print(
                    f"[orchestrator] fetch origin {ref} 失败（游标可能停滞）："
                    f"{fetched.stderr.strip()[:200]}"
                )
        for candidate in (f"refs/remotes/origin/{ref}", ref):
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    self._harness_repo,
                    "rev-parse",
                    "--verify",
                    f"{candidate}^{{commit}}",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                if fetch_failed and candidate.startswith("refs/remotes/origin/"):
                    raise RuntimeError(f"origin/{ref} fetch 失败，拒绝使用可能过期的远端游标")
                return result.stdout.strip()
        raise RuntimeError(f"解析 main ref {ref!r} 失败：{result.stderr[:200]}")
