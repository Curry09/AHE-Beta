# Spec-0032/T4：Orchestrator 需求面编排单测——会话级 main SHA 快照 + 生成两拍 + Owner 准入；dev 拍退役。
"""mock launcher + 临时 git 仓：

- 每局 launch 的 ref 解析自 harness 仓 main 当前 HEAD SHA；
- 交付面（进程外 vigil）推进 main 由「会话中直接 commit 模拟」——c 步回灌读到前进的 live SHA；
- 生成段两拍（triage 分片∥divergent → synthesize）→ Owner 准入 → 绊线，无 b 段 dev 拍。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
from auto_designer.models import Persona, SeedScenario, WorkspaceSpec
from auto_designer.usage import current_usage_context


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> Path:
    """只含 main 的本地 harness 仓（trunk 模型，无 release）。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


def _advance_main(repo: Path, n: int) -> None:
    """模拟交付面（进程外 vigil merge）推进 main：直接落一个 commit。"""
    (repo / "f").write_text(f"advanced {n}\n", encoding="utf-8")
    _git(repo, "commit", "-am", f"delivery advance {n}")


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


class _Launcher:
    def __init__(self, events: list) -> None:
        self._events = events

    def launch(self, ref: str, workspace_dir: str | None = None):
        self._events.append(("launch", ref))
        return ("harness", ref)


def _orch(repo, events, fixed_k=1, **kw):
    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))

    return Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(fixed_k)],
        run_session_fn=run_session_fn,
        initial_ref="main",
        **kw,
    )


def _recovery(tmp_path) -> RecoveryStore:
    return RecoveryStore.initialize(
        root=tmp_path / "checkpoints",
        identity=RecoveryIdentity(
            experiment_id="exp-1",
            run_id="run-1",
            config_hash="config-1",
            controller_sha="controller-1",
            plan_hash="plan-1",
        ),
    )


def test_round_launches_main_head_sha(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    orch = _orch(repo, events, fixed_k=2)

    out = orch.run_round("ignored-cursor")  # 传入游标被忽略，解析 live main
    assert out == head  # 无交付面推进 → 回灌仍是当前 main HEAD
    # a 段两局都按 main HEAD SHA launch（非 release_ref/tag）
    assert events == [
        ("launch", head),
        ("session", head),
        ("launch", head),
        ("session", head),
    ]


def test_no_delivery_keeps_main_latest(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    orch = _orch(repo, [])
    assert orch.run_round("c") == head  # 下一局仍取 main 最新（未变）


def test_external_delivery_advances_cursor(tmp_path) -> None:
    """交付面在轮中推进 main（进程外 vigil merge 的等价模拟）→ c 步回灌读到前进的 SHA。"""
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    events: list = []

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))
        _advance_main(repo, 1)  # 会话期间交付面合并落 main

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    out = orch.run_round("c")
    assert ("launch", head_before) in events  # a 段按起始 SHA launch（会话级快照）
    assert out == _git(repo, "rev-parse", "main") != head_before  # 回灌 = 前进后的 live main


def test_run_resolves_live_main_each_round(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    counter = {"n": 0}

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))
        counter["n"] += 1
        _advance_main(repo, counter["n"])  # 每轮交付面各推进一次

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    refs = orch.run(3)
    launched = [e[1] for e in events if e[0] == "launch"]
    assert len(launched) == 3  # 三轮各一次 launch
    assert len(set(refs)) == 3  # 每轮回灌 SHA 前进、互不相同
    # 第 k+1 轮按第 k 轮回灌的 SHA launch（next 局取到上轮交付面推进后的 main）
    assert launched[1:] == refs[:2]


# Spec-0033/T3：游标改跟 origin/main——server-side merge 后本地 main 不再是真身。


def _seed_with_origin(tmp_path: Path) -> tuple[Path, Path]:
    """本地 harness 仓 + bare origin：返回 (repo, writer)。writer 是另一份 clone，模拟交付面
    （vigil worker）向 origin 推进 main——本地 repo 不知情，恰是 spec-0032 后的真实拓扑。"""
    repo = _seed_repo(tmp_path)
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True
    )
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    writer = tmp_path / "writer"
    subprocess.run(["git", "clone", str(bare), str(writer)], check=True, capture_output=True)
    return repo, writer


def test_cursor_follows_origin_main_after_remote_merge(tmp_path) -> None:
    """交付面在 origin 上推进 main（本地仓不知情）→ 游标解析到新 SHA，launcher 也按新 SHA 起。"""
    repo, writer = _seed_with_origin(tmp_path)
    (writer / "f").write_text("merged by vigil\n", encoding="utf-8")
    _git(writer, "commit", "-am", "delivery merge on origin")
    _git(writer, "push", "origin", "main")
    remote_head = _git(writer, "rev-parse", "main")

    events: list = []
    orch = _orch(repo, events)
    out = orch.run_round("c")
    assert out == remote_head  # 游标 = origin/main（非停滞的本地 seed）
    assert ("launch", remote_head) in events  # fetch 已取回对象，launcher 按新 SHA 起


def test_cursor_falls_back_to_local_when_origin_unreachable(tmp_path) -> None:
    """origin 不可达（离线）→ 告警不抛，退化解析本地 main（游标停滞但闭环不废）。"""
    repo = _seed_repo(tmp_path)
    _git(repo, "remote", "add", "origin", str(tmp_path / "no-such-remote.git"))
    head = _git(repo, "rev-parse", "main")
    assert _orch(repo, []).run_round("c") == head


def test_cursor_refuses_stale_remote_tracking_head_after_fetch_failure(tmp_path) -> None:
    """已有 origin/main 但 fetch 失败时，不能静默使用可能过期的远端跟踪游标。"""
    repo, _writer = _seed_with_origin(tmp_path)
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(RuntimeError, match="拒绝使用可能过期"):
        _orch(repo, []).run_round("c")


def test_run_nonpositive_raises(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    with pytest.raises(ValueError):
        _orch(repo, []).run(0)


# Spec-0017/T3：a 段并行化——线程池并发跑会话、单会话异常不废整轮。


def test_parallel_sessions_all_run(tmp_path) -> None:
    """max_parallel_users=4 并发 8 局：全部会话都跑到。"""
    import threading

    repo = _seed_repo(tmp_path)
    events: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)  # 4 个 worker 齐射，证明确实并发（串行会在此死锁超时）

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        barrier.wait(timeout=10)  # 若实际串行（并发度<4），首局在此卡死 → BrokenBarrierError
        with lock:
            events.append(("session", scenario.description))

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(8)],
        run_session_fn=run_session_fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    sessions = [e for e in events if e[0] == "session"]
    assert len(sessions) == 8  # 8 局全部跑到
    assert {d for _, d in sessions} == {f"s{i}" for i in range(8)}


def test_parallel_one_session_failure_does_not_kill_round(tmp_path) -> None:
    """单会话抛异常（launch/落盘类意外）：记日志跳过，其余会话正常完成。"""
    repo = _seed_repo(tmp_path)
    events: list = []

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        if scenario.description == "s1":
            raise RuntimeError("这局炸了")
        events.append(("session", scenario.description))

    head = _git(repo, "rev-parse", "main")
    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(3)],
        run_session_fn=run_session_fn,
        initial_ref="main",
        max_parallel_users=2,
    )
    out = orch.run_round("c")  # 不抛 → 轮未被单会话失败废掉

    assert out == head
    assert {d for k, d in events if k == "session"} == {"s0", "s2"}  # 其余会话都完成


def test_all_user_sessions_failed_blocks_round(tmp_path) -> None:
    """所有会话都失败时，不能继续进入生成/准入并推进下一轮。"""
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    repo = _seed_repo(tmp_path)

    def fail_session(persona, scenario, harness, *, workspace_dir=None):
        raise RuntimeError("session unavailable")

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=fail_session,
        initial_ref="main",
    )
    with pytest.raises(RoundDeliveryBlocked, match="all-user-sessions-failed"):
        orch.run_round("c")


def test_parallel_default_is_serial_equivalent(tmp_path) -> None:
    """缺省 max_parallel_users=1：事件顺序与旧串行完全一致（回归基线，见 0017 acceptance）。"""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    orch = _orch(repo, events, fixed_k=2)  # _orch 不传 max_parallel_users → 默认 1

    orch.run_round("c")
    assert events == [
        ("launch", head),
        ("session", head),
        ("launch", head),
        ("session", head),
    ]  # 逐局 launch→session 交替，与并行化之前的串行时序一致


# Spec-0008/T1 v2：共享工作区——每局先于 launch materialize，同一目录同时喂 launch 与 run_session。
class _WsLauncher:
    def __init__(self, events: list) -> None:
        self._events = events

    def launch(self, ref: str, workspace_dir: str | None = None):
        self._events.append(("launch", workspace_dir))
        return ("harness", ref)


def test_round_materializes_shared_workspace_before_launch(tmp_path, monkeypatch) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.materialize_workspace",
        lambda spec: events.append(("materialize", spec.fixture)) or f"/ws/{spec.fixture}",
    )

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", workspace_dir))

    orch = Orchestrator(
        launcher=_WsLauncher(events),
        harness_repo=str(repo),
        fixed_set=[
            (
                _persona(),
                SeedScenario(description="s", workspace=WorkspaceSpec(fixture="billing-split")),
            )
        ],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    # 顺序：materialize 早于 launch；launch 与 session 收到同一个 workspace_dir。
    assert events[0] == ("materialize", "billing-split")
    assert events[1][0] == "launch" and events[1][1].cwd == "/ws/billing-split"
    assert events[2][0] == "session" and events[2][1] is events[1][1]


def test_round_ensures_deps_after_materialize_before_launch(tmp_path, monkeypatch) -> None:
    # Spec-0009/T3：依赖供给 hook 落在 materialize 之后、launch 之前；无工作区时不调。
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.materialize_workspace",
        lambda spec: events.append(("materialize", spec.fixture)) or f"/ws/{spec.fixture}",
    )
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.ensure_deps",
        lambda ws, spec: events.append(("ensure_deps", ws)),
    )

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", workspace_dir))

    orch = Orchestrator(
        launcher=_WsLauncher(events),
        harness_repo=str(repo),
        fixed_set=[
            (_persona(), SeedScenario(description="s", workspace=WorkspaceSpec(fixture="funcy"))),
        ],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    assert events[0] == ("materialize", "funcy")
    assert events[1][0] == "ensure_deps" and events[1][1].cwd == "/ws/funcy"
    assert events[2][0] == "launch" and events[2][1] is events[1][1]


def test_round_no_workspace_skips_ensure_deps(tmp_path, monkeypatch) -> None:
    # 无工作区 → materialize 与 ensure_deps 都不该被调用。
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.ensure_deps",
        lambda ws, spec: (_ for _ in ()).throw(AssertionError("不应 ensure_deps")),
    )
    orch = _orch(repo, [])  # fixed_set 场景无 workspace
    orch.run_round("c")  # 不抛即通过


def test_round_no_workspace_uses_shared_scratch(tmp_path, monkeypatch) -> None:
    # 纯文本卡（workspace=None）也开一个空的共享 scratch：不 materialize fixture，但 launch 与
    # session 拿到**同一个**非空目录——确保用户 agent 落到 harness 同一工作目录真核实，
    # 而非只凭 harness 回复"嘴上验"。
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(  # 无 fixture 工作区时绝不该调 materialize
        "auto_designer.loop.orchestrator.materialize_workspace",
        lambda spec: (_ for _ in ()).throw(AssertionError("不应 materialize")),
    )

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", workspace_dir))

    orch = Orchestrator(
        launcher=_WsLauncher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],  # workspace=None
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    launch_ws = next(ws for kind, ws in events if kind == "launch")
    session_ws = next(ws for kind, ws in events if kind == "session")
    assert launch_ws is not None and launch_ws == session_ws  # harness 与用户 agent 同一目录


# Spec-0021/T1（Spec-0032/T4 调整）：编排仓完整性绊线——每轮末调用一次；抛出即中止本轮（fail-closed）。


def test_integrity_guard_called_once_at_round_end(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    def guard() -> None:
        events.append(("guard", None))

    orch = _orch(repo, events, integrity_guard=guard)
    orch.run_round("c")

    # guard 在会话之后、返回前恰调一次
    assert [k for k, *_ in events].count("guard") == 1
    assert events[-1] == ("guard", None)


def test_integrity_guard_raise_aborts_round(tmp_path) -> None:
    from auto_designer.dev.repo_guard import RepoIntegrityError

    repo = _seed_repo(tmp_path)

    def guard() -> None:
        raise RepoIntegrityError("编排仓被动了")

    orch = _orch(repo, [], integrity_guard=guard)
    with pytest.raises(RepoIntegrityError):  # 安全事件 fail-closed，向上传播中止
        orch.run_round("c")


def test_no_guard_is_backward_compatible(tmp_path) -> None:
    """不传 integrity_guard → 行为与今天完全一致（退化）。"""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    assert _orch(repo, []).run_round("c") == head


# Spec-0029/T8（Spec-0032/T4 调整）：生成段两拍（triage 分片∥divergent → synthesize）→ Owner 准入收尾。


class _Phase:
    """记录自己被调用的时刻（往共享 events 里打一条）；shard 也记录（分片断言用）。"""

    def __init__(self, events: list, name: str) -> None:
        self._events = events
        self._name = name

    def triage_once(self, pending=None, shard=None):
        self._events.append(("d", self._name, shard))

    def propose_once(self):
        self._events.append(("d", self._name, None))

    def admit_once(self):
        self._events.append(("d", self._name, None))


def test_beats_order_triage_divergent_then_synth_then_owner(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    t0 = _Phase(events, "triage0")
    t1 = _Phase(events, "triage1")
    div = _Phase(events, "divergent")
    synth = _Phase(events, "synth")
    owner = _Phase(events, "owner")

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", None, None))

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
        triagers=[t0, t1],
        designers=[synth],
        divergents=[div],
        owner=owner,
    )
    orch.run_round("c")

    kinds = [e[1] if e[0] == "d" else e[0] for e in events if e[0] in ("session", "d")]
    # a → 第一拍（triage×2∥divergent，组内顺序不定）→ 第二拍 synth → owner 收尾（无 dev 拍）
    assert kinds[0] == "session"
    assert set(kinds[1:4]) == {"triage0", "triage1", "divergent"}
    assert kinds[4:] == ["synth", "owner"]
    # 分片参数：第 k 个 triager 拿 (k, n)
    shards = {e[1]: e[2] for e in events if e[0] == "d" and e[1].startswith("triage")}
    assert shards == {"triage0": (0, 2), "triage1": (1, 2)}


def test_triage_workers_receive_fixed_disjoint_snapshots(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    class SnapshotTriager:
        def snapshot_pending(self):
            return [type("Issue", (), {"number": number})() for number in (1, 2, 3, 4)]

        def triage_once(self, *, pending=None, shard=None):
            events.append((pending, shard))

    orch = _orch(repo, events, triagers=[SnapshotTriager(), SnapshotTriager()])
    orch.run_round("c")

    triage_events = [
        event for event in events if isinstance(event, tuple) and isinstance(event[0], list)
    ]
    assert [sorted(issue.number for issue in pending) for pending, shard in triage_events] == [
        [1, 3],
        [2, 4],
    ]
    assert all(shard is None for pending, shard in triage_events)


def test_no_owner_skips_admission(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", None, None))

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
        triagers=[_Phase(events, "triage")],
    )
    orch.run_round("c")  # owner=None 不炸、准入段跳过
    kinds = [e[1] if e[0] == "d" else e[0] for e in events if e[0] in ("session", "d")]
    assert kinds == ["session", "triage"]


def test_owner_failure_blocks_round_instead_of_advancing(tmp_path) -> None:
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    repo = _seed_repo(tmp_path)

    class BrokenOwner:
        def admit_once(self):
            raise RuntimeError("owner unavailable")

    orch = _orch(repo, [], owner=BrokenOwner())
    with pytest.raises(RoundDeliveryBlocked, match="owner-failed"):
        orch.run_round("c")


def test_run_binds_round_context_for_each_round() -> None:
    orchestrator = object.__new__(Orchestrator)
    orchestrator._initial_ref = "main"
    orchestrator._on_round_start = None
    orchestrator._on_round_end = None
    observed: list[int | None] = []
    observed_deliver: list[bool] = []

    def run_round(ref: str, *, deliver: bool = True) -> str:
        observed.append(current_usage_context().round_no)
        observed_deliver.append(deliver)
        return f"{ref}-next"

    orchestrator.run_round = run_round

    assert orchestrator.run(2) == ["main-next", "main-next-next"]
    assert observed == [1, 2]
    assert observed_deliver == [True, False]


def test_callable_session_plan_redraws_each_round(tmp_path) -> None:
    """fixed_set 为 callable 时每轮重抽 session 计划。"""
    repo = _seed_repo(tmp_path)
    events: list = []
    calls = {"n": 0}

    def plan():
        calls["n"] += 1
        return [(_persona(), SeedScenario(description=f"r{calls['n']}"))]

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", scenario.description))

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=plan,
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run(2)
    assert calls["n"] == 2
    assert [e[1] for e in events if e[0] == "session"] == ["r1", "r2"]


# Spec-0050/T3：末轮只用户；闸失败不开下一轮用户。


class _AdmitOwner:
    def __init__(self, events: list, numbers: list[int]) -> None:
        self._events = events
        self._numbers = numbers

    def admit_once(self):
        self._events.append(("admit", list(self._numbers)))

        class _Out:
            admitted = list(self._numbers)

        return _Out()


def test_run_skips_demand_on_last_round(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    waits: list[list[int]] = []

    def wait_delivery(*, numbers: list[int]) -> None:
        waits.append(list(numbers))

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=lambda persona, scenario, harness, *, workspace_dir=None: events.append(
            ("session", None)
        ),
        initial_ref="main",
        owner=_AdmitOwner(events, [11]),
        wait_delivery=wait_delivery,
    )
    orch.run(2)
    assert [e[0] for e in events if e[0] in ("session", "admit")] == [
        "session",
        "admit",
        "session",
    ]
    assert waits == [[11]]


@pytest.mark.parametrize("failure_label", ["needs-human", "automation-failed"])
def test_blocked_delivery_does_not_start_next_user_round(tmp_path, failure_label) -> None:
    # Spec-0062/T1: exercise the real gate, not a preconstructed exception.
    from auto_designer.loop.round_gate import RoundDeliveryBlocked, wait_round_delivery

    repo = _seed_repo(tmp_path)
    events: list = []

    def wait_delivery(*, numbers: list[int]) -> None:
        wait_round_delivery(
            numbers=numbers,
            fetch_issue=lambda number: {"state": "closed", "labels": [failure_label]},
        )

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=lambda persona, scenario, harness, *, workspace_dir=None: events.append(
            ("session", None)
        ),
        initial_ref="main",
        owner=_AdmitOwner(events, [8]),
        wait_delivery=wait_delivery,
    )
    with pytest.raises(RoundDeliveryBlocked, match=failure_label):
        orch.run(2)
    assert [e[0] for e in events if e[0] == "session"] == ["session"]


# Spec-0064/T2: durable stages skip completed work and reattach delivery.


def test_recovery_resumes_only_failed_stage_unit_and_keeps_frozen_plan(tmp_path) -> None:
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    repo = _seed_repo(tmp_path)
    events: list[str] = []
    plan_calls = 0

    def plan():
        nonlocal plan_calls
        plan_calls += 1
        return [(_persona(), SeedScenario(description=f"draw-{plan_calls}"))]

    class Triager:
        def __init__(self, name: str, *, fail_once: bool = False) -> None:
            self.name = name
            self.fail_once = fail_once

        def snapshot_pending(self):
            return []

        def triage_once(self, *, pending=None, shard=None):
            events.append(self.name)
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("injected triage failure")

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=plan,
        run_session_fn=lambda *args, **kwargs: events.append("user"),
        initial_ref="main",
        triagers=[Triager("triage-0"), Triager("triage-1", fail_once=True)],
        recovery=_recovery(tmp_path),
    )
    with pytest.raises(RoundDeliveryBlocked, match="triage-incomplete"):
        orch.run_round("main", round_no=1)
    assert events == ["user", "triage-0", "triage-1"]

    orch.run_round("main", round_no=1)
    assert events == ["user", "triage-0", "triage-1", "triage-1"]
    assert plan_calls == 1
    assert orch._recovery.stage_status(round_no=1, stage="round_sealed") == "completed"


def test_recovery_reattaches_delivery_without_rerunning_owner_or_users(tmp_path) -> None:
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    repo = _seed_repo(tmp_path)
    calls = {"user": 0, "owner": 0, "wait": 0}
    closed = False

    class Owner:
        def admit_once(self):
            calls["owner"] += 1
            return type("Outcome", (), {"admitted": [11]})()

    def wait_delivery(*, numbers):
        calls["wait"] += 1
        raise RoundDeliveryBlocked(numbers=list(numbers), reason="timeout")

    def fetch_issue(number):
        assert number == 11
        return {"state": "closed" if closed else "open", "labels": ["ready"]}

    def run_user(*args, **kwargs):
        calls["user"] += 1

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="one"))],
        run_session_fn=run_user,
        initial_ref="main",
        owner=Owner(),
        fetch_issue=fetch_issue,
        wait_delivery=wait_delivery,
        recovery=_recovery(tmp_path),
    )
    with pytest.raises(RoundDeliveryBlocked, match="timeout"):
        orch.run_round("main", round_no=1)
    closed = True
    orch.run_round("main", round_no=1)
    assert calls == {"user": 1, "owner": 1, "wait": 1}


def test_completed_recovery_round_is_an_idempotent_skip(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    calls: list[str] = []
    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="one"))],
        run_session_fn=lambda *args, **kwargs: calls.append("user"),
        initial_ref="main",
        recovery=_recovery(tmp_path),
    )
    first = orch.run_round("main", round_no=1, deliver=False)
    second = orch.run_round("ignored", round_no=1, deliver=False)
    assert first == second
    assert calls == ["user"]
    round_state = orch._recovery.round_state(round_no=1)
    assert set(round_state["stages"]) == {"round_started", "users", "round_sealed"}
