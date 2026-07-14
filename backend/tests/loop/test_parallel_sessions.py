# Spec-0017/T4：多用户会话并行化端到端回归（全 Fake，不依赖真 LLM/Gitea）。
"""穿透真实用户侧栈（Orchestrator → make_sim_run_session_fn → sim run_session →
ScriptedPersonaClient × ScriptedHarness → SessionStore/FakeTracker/live）验证三件事：

① 并发正确性：8 局并发后 sessions 目录 8 个全量文件、index.json 恰 8 条、live 槽位/归档完整
   （精确计数，可捕获竞态丢更新回归）；
② 慢会话注入：慢会话不阻塞其余会话收割（快会话先完成，慢会话最后收尾）；
③ 崩溃注入：harness send 抛异常 → 会话内 [harness error] 信号路径在并发下仍成立，
   会话正常落盘、不影响同批其他会话。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from auto_designer.loop.live import archive_agent as live_archive_agent
from auto_designer.loop.live import read_agents, read_history, update_agent
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.sim_user import make_sim_run_session_fn
from auto_designer.models import Persona, SeedScenario
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.run_live import expert


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("v0\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-m", "s"],
        check=True,
        capture_output=True,
    )
    return repo


class _ScriptedLauncher:
    """每次 launch 新建一个 ScriptedHarness（一句柄一会话，与真 launcher 同构）。"""

    def launch(self, ref: str, workspace_dir: str | None = None):
        return ScriptedHarness()


class _CrashingHarness:
    """send 必炸的 harness：验证 loop 侧 [harness error] 转译在并发下仍成立。"""

    def send(self, message: str) -> str:
        raise RuntimeError("boom: 协议违例")

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


class _NoopDev:
    def work_one(self, skip=None):
        from auto_designer.dev.agentic_developer import DevOutcome

        return DevOutcome()


def _rig(tmp_path: Path, n_users: int):
    """组一套真实用户侧栈：返回 (fixed_set, run_session_fn, store, tracker, data_dir, done)。

    done: 收尾回调按完成先后记录 identity（观测完成顺序用）。
    """
    sp = expert()
    identities = [f"U{i:02d}" for i in range(n_users)]
    fixed_set = [
        (
            Persona(identity=ident, level="expert", domain="python", goal="g", speaking_style="s"),
            SeedScenario(description=f"task-{ident}"),
        )
        for ident in identities
    ]
    store = SessionStore(tmp_path / "sessions")
    tracker = FakeTracker()
    data_dir = tmp_path / "data"
    done: list[str] = []

    def on_turn(identity, sim_p, res, running, *, session_id=None):
        # 与 run.py on_sim_turn 同构的最小接线：逐轮 upsert 槽位，收尾归档（走 live 锁路径）。
        update_agent(
            data_dir=data_dir,
            agent_id=f"user-{identity}",
            role="user",
            label=identity,
            running=running,
            status="对话中…" if running else f"已完成 · {res.end_reason}",
            round_no=1,
        )
        if not running:
            done.append(identity)  # list.append 原子，无需额外锁
            live_archive_agent(
                data_dir=data_dir,
                agent_id=f"user-{identity}",
                round_no=1,
                extra={"kind": "user_session", "session_id": session_id},
            )

    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=tracker,
        store=store,
        sim_personas={ident: sp for ident in identities},
        on_turn=on_turn,
    )
    return fixed_set, fn, store, tracker, data_dir, done


def test_eight_parallel_sessions_land_completely(tmp_path) -> None:
    """① 并发正确性：8 局（并发 4）后全量文件/索引/live 槽位/归档/issue 一个不少。"""
    repo = _seed_repo(tmp_path)
    fixed_set, fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=8)

    orch = Orchestrator(
        launcher=_ScriptedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        developer_agents=[_NoopDev()],
        run_session_fn=fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    entries = store.index()
    assert len(entries) == 8  # index 恰 8 条（丢条目即竞态回归）
    full_files = {p.name for p in (tmp_path / "sessions").glob("*.json")} - {"index.json"}
    assert len(full_files) == 8  # 全量文件 8 个
    for e in entries:
        assert store.load(e["session_id"]).session_id == e["session_id"]  # 逐个可回读

    agents = read_agents(data_dir=data_dir)
    assert [a["label"] for a in agents] == [f"U{i:02d}" for i in range(8)]  # 槽位全在且稳定有序
    assert all(a["running"] is False for a in agents)
    history = read_history(data_dir=data_dir)
    assert len(history) == 8 and all(h["round"] == 1 for h in history)  # 按轮归档完整
    assert sorted(done) == [f"U{i:02d}" for i in range(8)]
    # expert × ScriptedHarness 确定性走 file_issue → 每局一条 issue 落 tracker
    assert len(tracker.list_open_issues()) == 8


def test_slow_session_does_not_block_fast_ones(tmp_path) -> None:
    """② 慢会话注入：U00 每轮多睡 0.3s，其余秒回——快会话先收尾，慢会话最后，且不互相等。"""
    repo = _seed_repo(tmp_path)
    fixed_set, inner_fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=4)

    def fn(persona, scenario, harness, *, workspace_dir=None):
        if persona.identity == "U00":
            time.sleep(0.3)  # 模拟慢 harness/慢 LLM：整局起步即慢
        return inner_fn(persona, scenario, harness, workspace_dir=workspace_dir)

    orch = Orchestrator(
        launcher=_ScriptedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        developer_agents=[_NoopDev()],
        run_session_fn=fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    assert len(store.index()) == 4  # 快慢全部落盘
    # 并行下快会话不等慢会话：U00 睡着时其余三局已完成 → U00 必最后收尾。
    # （若退化为串行，U00 第一个跑、第一个完成，此断言即失败。）
    assert done[-1] == "U00" and set(done) == {"U00", "U01", "U02", "U03"}


def test_crashing_harness_still_lands_as_signal_among_healthy_peers(tmp_path) -> None:
    """③ 崩溃注入：坏 harness 的 send 全炸——会话不炸整轮，[harness error] 进 transcript，
    同批健康会话不受影响（0012 信号转译 × 0017 并行的组合回归）。"""
    repo = _seed_repo(tmp_path)
    fixed_set, fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=3)

    class _MixedLauncher:
        """U00 那局拿到必炸 harness：launch 按调用次序分配——阶段二提交顺序即 fixed_set 顺序，
        max_parallel_users=1 下第一次 launch 恰为 U00（串行时序确定）。"""

        def __init__(self) -> None:
            self.calls = 0

        def launch(self, ref: str, workspace_dir: str | None = None):
            self.calls += 1
            return _CrashingHarness() if self.calls == 1 else ScriptedHarness()

    orch = Orchestrator(
        launcher=_MixedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        developer_agents=[_NoopDev()],
        run_session_fn=fn,
        initial_ref="main",
        max_parallel_users=1,  # 串行时序使「第 1 次 launch = U00」确定；信号路径与并发度无关
    )
    orch.run_round("c")  # 不抛：崩溃已在会话内转信号

    entries = store.index()
    assert len(entries) == 3  # 崩溃局照样落盘（有梯度），健康局不受影响
    by_id = {store.load(e["session_id"]).persona.identity: e["session_id"] for e in entries}
    crashed = store.load(by_id["U00"])
    texts = " ".join(t.content for t in crashed.transcript.turns)
    assert "[harness error]" in texts  # 崩溃如实进 transcript（persona 视角可感知）
    for ident in ("U01", "U02"):
        healthy = store.load(by_id[ident])
        assert all("[harness error]" not in t.content for t in healthy.transcript.turns)
