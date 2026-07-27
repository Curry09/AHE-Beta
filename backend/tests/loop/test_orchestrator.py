# Spec-0007/T2：Orchestrator 纯 trunk 编排单测——会话级 main SHA 快照 + 去 release 链。
"""mock launcher/developer + 临时 git 仓：

- 每局 launch 的 ref 解析自 harness 仓 main 当前 HEAD SHA（非 release_ref 链）；
- 无 dev 推进时下一局仍取 main 最新（SHA 不变）；dev 推进 main 后下一局解析到前进的 SHA；
- b 段开发者依次领不同 issue（skip 透传），不再据 outcome.tag 链式回灌。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_designer.dev.agentic_developer import DevOutcome
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.models import Persona, SeedScenario, WorkspaceSpec


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


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


class _Launcher:
    def __init__(self, events: list) -> None:
        self._events = events

    def launch(self, ref: str, workspace_dir: str | None = None):
        self._events.append(("launch", ref))
        return ("harness", ref)


class _Dev:
    """假开发者：记录调用与收到的 skip；可选地真改 main（模拟直推推进 HEAD）。"""

    def __init__(self, events: list, outcome: DevOutcome, repo: Path | None = None, label="dev"):
        self._events = events
        self._outcome = outcome
        self._repo = repo
        self._label = label
        self._n = 0

    def work_one(self, skip: set[int] | None = None) -> DevOutcome:
        self._events.append((self._label, frozenset(skip or set())))
        if self._repo is not None:  # 模拟 dev 直推 main：每次唯一改动推进 HEAD
            self._n += 1
            (self._repo / "f").write_text(f"advanced {self._n}\n", encoding="utf-8")
            _git(self._repo, "commit", "-am", f"dev advance main {self._n}")
        return self._outcome


def _orch(repo, events, developers, fixed_k=1):
    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))

    return Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description=f"s{i}")) for i in range(fixed_k)],
        developer_agents=developers,
        run_session_fn=run_session_fn,
        initial_ref="main",
    )


def test_round_launches_main_head_sha(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    dev = _Dev(events, DevOutcome(issue_number=1, tag="v2", committed=True))  # 不真改仓
    orch = _orch(repo, events, [dev], fixed_k=2)

    out = orch.run_round("ignored-cursor")  # 传入游标被忽略，解析 live main
    assert out == head  # 无真实推进 → 回灌仍是当前 main HEAD
    # a 段两局都按 main HEAD SHA launch（非 release_ref/tag）
    assert events[:4] == [
        ("launch", head),
        ("session", head),
        ("launch", head),
        ("session", head),
    ]
    assert events[4][0] == "dev"  # b 段在 a 段之后


def test_no_dev_keeps_main_latest(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    orch = _orch(repo, events, [_Dev(events, DevOutcome())])  # 无 issue/未推进
    assert orch.run_round("c") == head  # 下一局仍取 main 最新（未变）


def test_dev_advances_main_sha_forward(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    events: list = []
    dev = _Dev(events, DevOutcome(issue_number=1, tag="v2", committed=True), repo=repo)
    orch = _orch(repo, events, [dev])

    out = orch.run_round("c")
    # a 段按起始 SHA launch（dev 推进发生在会话之后）
    assert ("launch", head_before) in events
    # 回灌 = dev 推进后的新 main HEAD，SHA 前进
    assert out == _git(repo, "rev-parse", "main") != head_before


def test_two_devs_skip_chains_assigned_issues(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    dev1 = _Dev(events, DevOutcome(issue_number=1, tag="v2", committed=True), label="dev1")
    dev2 = _Dev(events, DevOutcome(issue_number=2, tag="v3", committed=True), label="dev2")
    orch = _orch(repo, events, [dev1, dev2])
    orch.run_round("c")
    dev2_call = next(e for e in events if e[0] == "dev2")
    assert 1 in dev2_call[1]  # dev2 收到的 skip 含 dev1 已认领的 issue 1


def test_run_resolves_live_main_each_round(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    dev = _Dev(events, DevOutcome(issue_number=1, tag="v", committed=True), repo=repo)
    orch = _orch(repo, events, [dev])

    refs = orch.run(3)
    launched = [e[1] for e in events if isinstance(e, tuple) and e[0] == "launch"]
    assert len(launched) == 3  # 三轮各一次 launch
    # 每轮 dev 推进 main，回灌的各轮末 SHA 互不相同（无 release 链，全靠 live main 递进）
    assert len(set(refs)) == 3
    # 第 k+1 轮按第 k 轮回灌的 SHA launch（next 局取到上轮 dev 推进后的 main）
    assert launched[1:] == refs[:2]


def test_run_nonpositive_raises(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    with pytest.raises(ValueError):
        _orch(repo, [], [_Dev([], DevOutcome())]).run(0)


def test_b_phase_error_propagates(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    class _BoomDev:
        def work_one(self, skip=None):
            raise RuntimeError("dev 崩了")

    with pytest.raises(RuntimeError):
        _orch(repo, events, [_BoomDev()]).run_round("c")


# Spec-0017/T3：a 段并行化——线程池并发跑会话、单会话异常不废整轮、汇齐后才进 d/b 段。


def test_parallel_sessions_all_run_and_devs_wait(tmp_path) -> None:
    """max_parallel_users=4 并发 8 局：全部会话都跑到，且 b 段在 a 段全部汇齐后才开始。"""
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
        developer_agents=[_Dev(events, DevOutcome(issue_number=1, tag="v", committed=True))],
        run_session_fn=run_session_fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    sessions = [e for e in events if e[0] == "session"]
    assert len(sessions) == 8  # 8 局全部跑到
    assert {d for _, d in sessions} == {f"s{i}" for i in range(8)}
    assert events.index(("dev", frozenset())) == len(events) - 1  # dev 在全部会话之后


def test_parallel_one_session_failure_does_not_kill_round(tmp_path) -> None:
    """单会话抛异常（launch/落盘类意外）：记日志跳过，其余会话正常完成、d/b 段照常。"""
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
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
        max_parallel_users=2,
    )
    out = orch.run_round("c")  # 不抛 → 轮未被单会话失败废掉

    assert out == head
    assert {d for k, d in events if k == "session"} == {"s0", "s2"}  # 其余会话都完成
    assert any(k == "dev" for k, *_ in events)  # b 段照常执行


def test_parallel_default_is_serial_equivalent(tmp_path) -> None:
    """缺省 max_parallel_users=1：事件顺序与旧串行完全一致（回归基线，见 0017 acceptance）。"""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    dev = _Dev(events, DevOutcome(issue_number=1, tag="v2", committed=True))
    orch = _orch(repo, events, [dev], fixed_k=2)  # _orch 不传 max_parallel_users → 默认 1

    orch.run_round("c")
    assert events[:4] == [
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
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    # 顺序：materialize 早于 launch；launch 与 session 收到同一个 workspace_dir。
    assert events[0] == ("materialize", "billing-split")
    assert events[1] == ("launch", "/ws/billing-split")
    assert events[2] == ("session", "/ws/billing-split")


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
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    assert events[:3] == [
        ("materialize", "funcy"),
        ("ensure_deps", "/ws/funcy"),
        ("launch", "/ws/funcy"),
    ]


def test_round_no_workspace_skips_ensure_deps(tmp_path, monkeypatch) -> None:
    # 无工作区 → materialize 与 ensure_deps 都不该被调用。
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.ensure_deps",
        lambda ws, spec: (_ for _ in ()).throw(AssertionError("不应 ensure_deps")),
    )
    orch = _orch(repo, [], [_Dev([], DevOutcome())])  # fixed_set 场景无 workspace
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
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run_round("c")

    launch_ws = next(ws for kind, ws in events if kind == "launch")
    session_ws = next(ws for kind, ws in events if kind == "session")
    assert launch_ws is not None and launch_ws == session_ws  # harness 与用户 agent 同一目录


# Spec-0021/T1：编排仓完整性绊线——b 段后调用；guard 抛出中止本轮并传播（fail-closed）。


def _orch_with_guard(repo, events, developers, guard):
    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))

    return Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        developer_agents=developers,
        run_session_fn=run_session_fn,
        initial_ref="main",
        integrity_guard=guard,
    )


def test_integrity_guard_called_after_b_phase(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    def guard() -> None:
        events.append(("guard", None))

    orch = _orch_with_guard(repo, events, [_Dev(events, DevOutcome())], guard)
    orch.run_round("c")

    # guard 在 b 段（dev）之后、返回前恰调一次
    assert [k for k, *_ in events].count("guard") == 1
    assert events.index(("guard", None)) > max(i for i, e in enumerate(events) if e[0] == "dev")


def test_integrity_guard_raise_aborts_round(tmp_path) -> None:
    from auto_designer.dev.repo_guard import RepoIntegrityError

    repo = _seed_repo(tmp_path)
    events: list = []

    def guard() -> None:
        raise RepoIntegrityError("编排仓被动了")

    orch = _orch_with_guard(repo, events, [_Dev(events, DevOutcome())], guard)
    with pytest.raises(RepoIntegrityError):  # 安全事件 fail-closed，向上传播中止
        orch.run_round("c")


def test_no_guard_is_backward_compatible(tmp_path) -> None:
    """不传 integrity_guard → 行为与今天完全一致（退化）。"""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    assert _orch(repo, [], [_Dev([], DevOutcome())]).run_round("c") == head


# Spec-0025/T6：d 段两 agent——triage 先于 synthesize，两者都在 b 之前。


class _Phase:
    """记录自己被调用的时刻（往共享 events 里打一条）。"""

    def __init__(self, events: list, name: str) -> None:
        self._events = events
        self._name = name

    def triage_once(self):
        self._events.append(("d", self._name))

    def propose_once(self):
        self._events.append(("d", self._name))


def test_triage_runs_before_synthesize_before_dev(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    triager = _Phase(events, "triage")
    synth = _Phase(events, "synth")

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", None))

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
        triagers=[triager],
        designers=[synth],
    )
    orch.run_round("c")

    # a（session）→ d1 triage → d2 synth → b（dev），严格此序
    kinds = [e[1] if e[0] == "d" else e[0] for e in events if e[0] in ("session", "d", "dev")]
    assert kinds == ["session", "triage", "synth", "dev"]


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
        developer_agents=[_Dev(events, DevOutcome())],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    orch.run(2)
    assert calls["n"] == 2
    assert [e[1] for e in events if e[0] == "session"] == ["r1", "r2"]
