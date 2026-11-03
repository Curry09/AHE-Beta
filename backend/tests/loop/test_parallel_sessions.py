# Spec-0017/T4: multi-user session parallelization end-to-end regression (all Fake, no real LLM/Gitea dependency).
"""Traverse real user-side stack (Orchestrator → make_sim_run_session_fn → sim run_session →
ScriptedPersonaClient × ScriptedHarness → SessionStore/FakeTracker/live) to verify three things:

① Concurrency correctness: after 8 concurrent sessions, sessions directory has all 8 complete files, index.json has exactly 8 entries, live slots/archive intact
   (precise counts to catch lost-update race regressions);
② Slow session injection: slow session does not block harvesting of other sessions (fast sessions complete first, slow session finalized last);
③ Crash injection: harness send raises exception → [harness error] signal path within session holds under concurrency,
   session persists normally, does not affect other sessions in batch.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ahe_beta.loop.live import archive_agent as live_archive_agent
from ahe_beta.loop.live import read_agents, read_history, update_agent
from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.sim_user import make_sim_run_session_fn
from ahe_beta.models import Persona, SeedScenario
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.run_live import expert


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
    """Each launch creates a new ScriptedHarness (one handle per session, isomorphic to real launcher)."""

    def launch(self, ref: str, workspace_dir: str | None = None):
        return ScriptedHarness()


class _CrashingHarness:
    """harness that must crash on send: verify [harness error] translation at loop side holds under concurrency."""

    def send(self, message: str) -> str:
        raise RuntimeError("boom: Protocol violation")

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


def _rig(tmp_path: Path, n_users: int):
    """Assemble a real user-side stack: return (fixed_set, run_session_fn, store, tracker, data_dir, done).

    done: conclusion callback records identity in completion order (observe completion sequence).
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
        # Minimal wiring isomorphic to run.py on_sim_turn: upsert slots each round, archive at conclusion (traverse live lock path).
        update_agent(
            data_dir=data_dir,
            agent_id=f"user-{identity}",
            role="user",
            label=identity,
            running=running,
            status="In conversation…" if running else f"Completed · {res.end_reason}",
            round_no=1,
        )
        if not running:
            done.append(identity)  # list.append is atomic, no additional lock needed
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
    """① Concurrency correctness: after 8 sessions (4 concurrent) all complete files/index/live slots/archive/issues present."""
    repo = _seed_repo(tmp_path)
    fixed_set, fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=8)

    orch = Orchestrator(
        launcher=_ScriptedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        run_session_fn=fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    entries = store.index()
    # index has exactly 8 entries (missing entries indicate race regression)
    assert len(entries) == 8
    full_files = {p.name for p in (tmp_path / "sessions").glob("*.json")} - {"index.json"}
    assert len(full_files) == 8  # all 8 complete files
    for e in entries:
        # Readable sequentially, one at a time
        assert store.load(e["session_id"]).session_id == e["session_id"]

    agents = read_agents(data_dir=data_dir)
    # All slots present and stable in order
    assert [a["label"] for a in agents] == [f"U{i:02d}" for i in range(8)]
    assert all(a["running"] is False for a in agents)
    history = read_history(data_dir=data_dir)
    # Complete per-round archival
    assert len(history) == 8 and all(h["round"] == 1 for h in history)
    assert sorted(done) == [f"U{i:02d}" for i in range(8)]
    # expert × ScriptedHarness deterministic path: file_issue → one issue per session lands on tracker
    assert len(tracker.list_open_issues()) == 8


def test_slow_session_does_not_block_fast_ones(tmp_path) -> None:
    """② Slow session injection: U00 sleeps an additional 0.3s per round, others respond in seconds—fast sessions complete first, slow session last, no mutual waiting."""
    repo = _seed_repo(tmp_path)
    fixed_set, inner_fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=4)

    def fn(persona, scenario, harness, *, workspace_dir=None):
        if persona.identity == "U00":
            time.sleep(0.3)  # Simulate slow harness / slow LLM: entire session starts slow
        return inner_fn(persona, scenario, harness, workspace_dir=workspace_dir)

    orch = Orchestrator(
        launcher=_ScriptedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        run_session_fn=fn,
        initial_ref="main",
        max_parallel_users=4,
    )
    orch.run_round("c")

    assert len(store.index()) == 4  # All fast and slow persisted to disk
    # Under parallelism, fast sessions do not wait for slow: U00 sleeps while the other three sessions complete → U00 must finish last.
    # (If degraded to serial, U00 runs first and completes first, this assertion fails.)
    assert done[-1] == "U00" and set(done) == {"U00", "U01", "U02", "U03"}


def test_crashing_harness_still_lands_as_signal_among_healthy_peers(tmp_path) -> None:
    """③ Crash injection: bad harness send always fails—session does not crash entire round, [harness error] enters transcript,
    healthy sessions in same batch unaffected (0012 signal translation × 0017 parallelism regression combination)."""
    repo = _seed_repo(tmp_path)
    fixed_set, fn, store, tracker, data_dir, done = _rig(tmp_path, n_users=3)

    class _MixedLauncher:
        """U00 session receives a guaranteed-crash harness: launch allocates by invocation order—phase two submission order is fixed_set order,
        under max_parallel_users=1 first launch is exactly U00 (serial timing deterministic)."""

        def __init__(self) -> None:
            self.calls = 0

        def launch(self, ref: str, workspace_dir: str | None = None):
            self.calls += 1
            return _CrashingHarness() if self.calls == 1 else ScriptedHarness()

    orch = Orchestrator(
        launcher=_MixedLauncher(),
        harness_repo=str(repo),
        fixed_set=fixed_set,
        run_session_fn=fn,
        initial_ref="main",
        # Serial timing ensures "1st launch = U00"; signal path independent of concurrency
        max_parallel_users=1,
    )
    orch.run_round("c")  # No throw: crash already translated to signal within session

    entries = store.index()
    # Crashed session persisted nonetheless (with gradation), healthy sessions unaffected
    assert len(entries) == 3
    by_id = {store.load(e["session_id"]).persona.identity: e["session_id"] for e in entries}
    crashed = store.load(by_id["U00"])
    texts = " ".join(t.content for t in crashed.transcript.turns)
    # Crash faithfully enters transcript (detectable from persona perspective)
    assert "[harness error]" in texts
    for ident in ("U01", "U02"):
        healthy = store.load(by_id[ident])
        assert all("[harness error]" not in t.content for t in healthy.transcript.turns)
