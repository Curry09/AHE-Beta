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


def test_round_no_workspace_passes_none(tmp_path, monkeypatch) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(  # 无工作区时绝不该调 materialize
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

    assert ("launch", None) in events
    assert ("session", None) in events
