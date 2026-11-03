# Spec-0032/T4: Orchestrator demand-plane orchestration unit test—session-level main SHA snapshot + two generation beats + Owner admission; dev beat retired.
"""mock launcher + temporary git repo:

- Each session's launch ref is resolved from the current HEAD SHA of main in the harness repo;
- Delivery plane (out-of-process vigil) advances main via "direct commit simulation during session"—step c feeds back the live SHA advancement read;
- Generation stage: two beats (triage shard ∥ divergent → architect) → Owner admission → tripwire, no dev beat in segment b.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore
from ahe_beta.models import Persona, SeedScenario, WorkspaceSpec
from ahe_beta.usage import current_usage_context


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> Path:
    """Local harness repo containing only main (trunk model, no release branches)."""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


def _advance_main(repo: Path, n: int) -> None:
    """Simulate delivery plane (out-of-process vigil merge) advancing main: directly commit one change."""
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

    out = orch.run_round("ignored-cursor")  # Incoming cursor is ignored, resolve live main
    assert out == head  # No delivery plane advancement → feedback remains current main HEAD
    # Both launches in phase a use main HEAD SHA (not release_ref/tag)
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
    assert orch.run_round("c") == head  # Next session still takes latest main (unchanged)


def test_external_delivery_advances_cursor(tmp_path) -> None:
    """Delivery surface advances main within the round (out-of-process equivalent simulation of vigil merge) → step c feeds back the SHA of the advanced position."""
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    events: list = []

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))
        _advance_main(repo, 1)  # Delivery surface merges into main during the session

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    out = orch.run_round("c")
    # Segment a launches from the initial SHA (session-level snapshot)
    assert ("launch", head_before) in events
    # Feedback = live main after advancing
    assert out == _git(repo, "rev-parse", "main") != head_before


def test_run_resolves_live_main_each_round(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    counter = {"n": 0}

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        events.append(("session", harness[1]))
        counter["n"] += 1
        _advance_main(repo, counter["n"])  # Delivery surface advances once per round

    orch = Orchestrator(
        launcher=_Launcher(events),
        harness_repo=str(repo),
        fixed_set=[(_persona(), SeedScenario(description="s"))],
        run_session_fn=run_session_fn,
        initial_ref="main",
    )
    refs = orch.run(3)
    launched = [e[1] for e in events if e[0] == "launch"]
    assert len(launched) == 3  # Launch occurs once per round across three rounds
    assert len(set(refs)) == 3  # Feedback SHA advances each round and is unique across rounds
    # Round k+1 launches from the SHA that the delivery plane advanced to in round k (next session receives main as advanced by the previous round's delivery plane)
    assert launched[1:] == refs[:2]


# Spec-0033/T3: cursor follows origin/main—after server-side merge, local main is no longer the source of truth.


def _seed_with_origin(tmp_path: Path) -> tuple[Path, Path]:
    """Local harness repo + bare origin: returns (repo, writer). writer is another clone simulating the delivery surface (vigil worker) advancing main on origin—the local repo is unaware, which is the actual topology after spec-0032."""
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
    """Delivery surface advances main on origin (local repo unaware) → cursor resolves to the new SHA, launcher also starts from the new SHA."""
    repo, writer = _seed_with_origin(tmp_path)
    (writer / "f").write_text("merged by vigil\n", encoding="utf-8")
    _git(writer, "commit", "-am", "delivery merge on origin")
    _git(writer, "push", "origin", "main")
    remote_head = _git(writer, "rev-parse", "main")

    events: list = []
    orch = _orch(repo, events)
    out = orch.run_round("c")
    assert out == remote_head  # Cursor = origin/main (non-stalled local seed)
    # Fetch has retrieved objects, launcher starts from new SHA
    assert ("launch", remote_head) in events


def test_cursor_falls_back_to_local_when_origin_unreachable(tmp_path) -> None:
    """Origin unreachable (offline) → alarm is not raised, parsing degrades to local main (cursor stalls but the loop is not broken)."""
    repo = _seed_repo(tmp_path)
    _git(repo, "remote", "add", "origin", str(tmp_path / "no-such-remote.git"))
    head = _git(repo, "rev-parse", "main")
    assert _orch(repo, []).run_round("c") == head


def test_cursor_refuses_stale_remote_tracking_head_after_fetch_failure(tmp_path) -> None:
    """When origin/main exists but fetch fails, cannot silently use a possibly stale remote-tracking cursor."""
    repo, _writer = _seed_with_origin(tmp_path)
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing-origin.git"))

    with pytest.raises(RuntimeError, match="refusing to use a potentially stale"):
        _orch(repo, []).run_round("c")


def test_run_nonpositive_raises(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    with pytest.raises(ValueError):
        _orch(repo, []).run(0)


# Spec-0017/T3: segment a parallelization—thread pool concurrently runs sessions, single-session exceptions do not break the round.


def test_parallel_sessions_all_run(tmp_path) -> None:
    """max_parallel_users=4 concurrent with 8 sessions: all sessions run to completion."""
    import threading

    repo = _seed_repo(tmp_path)
    events: list = []
    lock = threading.Lock()
    # 4 workers fire together, proving actual concurrency (serial execution would deadlock here with timeout)
    barrier = threading.Barrier(4)

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        # If actually serial (concurrency < 4), first session stalls here → BrokenBarrierError
        barrier.wait(timeout=10)
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
    assert len(sessions) == 8  # All 8 sessions run to completion
    assert {d for _, d in sessions} == {f"s{i}" for i in range(8)}


def test_parallel_one_session_failure_does_not_kill_round(tmp_path) -> None:
    """Single session raises exception (launch/persistence anomaly): log and skip, remaining sessions complete normally."""
    repo = _seed_repo(tmp_path)
    events: list = []

    def run_session_fn(persona, scenario, harness, *, workspace_dir=None):
        if scenario.description == "s1":
            raise RuntimeError("This round crashed")
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
    out = orch.run_round("c")  # Does not raise → round is not broken by single session failure

    assert out == head
    # Remaining sessions all complete
    assert {d for k, d in events if k == "session"} == {"s0", "s2"}


def test_all_user_sessions_failed_blocks_round(tmp_path) -> None:
    """When all sessions fail, must not continue into generation/admission and advance to the next round."""
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked

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
    """Default max_parallel_users=1: event order is identical to old serial behavior (regression baseline, see 0017 acceptance)."""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    events: list = []
    orch = _orch(repo, events, fixed_k=2)  # _orch does not pass max_parallel_users → defaults to 1

    orch.run_round("c")
    assert events == [
        ("launch", head),
        ("session", head),
        ("launch", head),
        ("session", head),
        # Alternating launch→session per session, consistent with serial timing before parallelization
    ]


# Spec-0008/T1 v2: shared workspace—each session materializes before launch, same directory feeds both launch and run_session.
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
        "ahe_beta.loop.orchestrator.materialize_workspace",
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

    # Ordering: materialize before launch; launch and session receive the same workspace_dir.
    assert events[0] == ("materialize", "billing-split")
    assert events[1][0] == "launch" and events[1][1].cwd == "/ws/billing-split"
    assert events[2][0] == "session" and events[2][1] is events[1][1]


def test_round_ensures_deps_after_materialize_before_launch(tmp_path, monkeypatch) -> None:
    # Spec-0009/T3: Dependency provisioning hook runs after materialize and before launch; not invoked when workspace is absent.
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(
        "ahe_beta.loop.orchestrator.materialize_workspace",
        lambda spec: events.append(("materialize", spec.fixture)) or f"/ws/{spec.fixture}",
    )
    monkeypatch.setattr(
        "ahe_beta.loop.orchestrator.ensure_deps",
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
    # No workspace → neither materialize nor ensure_deps should be called.
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(
        "ahe_beta.loop.orchestrator.ensure_deps",
        lambda ws, spec: (_ for _ in ()).throw(AssertionError("Should not ensure_deps")),
    )
    orch = _orch(repo, [])  # fixed_set scenario has no workspace
    orch.run_round("c")  # Passing = no exception raised


def test_round_no_workspace_uses_shared_scratch(tmp_path, monkeypatch) -> None:
    # Plain-text card (workspace=None) opens an empty shared scratch: do not materialize fixture, but launch and
    # session receives the **same** non-empty directory—ensuring user agent lands in harness working directory for real verification,
    # not merely by harness claiming verification in its reply.
    repo = _seed_repo(tmp_path)
    events: list = []
    monkeypatch.setattr(  # materialize must never be called for workspace without fixture
        "ahe_beta.loop.orchestrator.materialize_workspace",
        lambda spec: (_ for _ in ()).throw(AssertionError("Should not materialize")),
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
    # harness and user agent in the same directory
    assert launch_ws is not None and launch_ws == session_ws


# Spec-0021/T1 (Spec-0032/T4 adjustment): orchestration repository integrity guard rail—invoked once at end of each round; raising it aborts the round (fail-closed).


def test_integrity_guard_called_once_at_round_end(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []

    def guard() -> None:
        events.append(("guard", None))

    orch = _orch(repo, events, integrity_guard=guard)
    orch.run_round("c")

    # guard called exactly once after session, before return
    assert [k for k, *_ in events].count("guard") == 1
    assert events[-1] == ("guard", None)


def test_integrity_guard_raise_aborts_round(tmp_path) -> None:
    from ahe_beta.guards.repo_guard import RepoIntegrityError

    repo = _seed_repo(tmp_path)

    def guard() -> None:
        raise RepoIntegrityError("Orchestration repository was modified")

    orch = _orch(repo, [], integrity_guard=guard)
    with pytest.raises(RepoIntegrityError):  # security events fail-closed, propagate abort upward
        orch.run_round("c")


def test_no_guard_is_backward_compatible(tmp_path) -> None:
    """integrity_guard not passed → behavior identical to today (degraded mode)."""
    repo = _seed_repo(tmp_path)
    head = _git(repo, "rev-parse", "main")
    assert _orch(repo, []).run_round("c") == head


# Spec-0029/T8 (Spec-0032/T4 adjustment): generation stage with two beats (triage shard ∥ divergent → architect) → Owner admission to finish.


class _Phase:
    """Record the moment this is invoked (write one entry to shared events); shard also records (for shard assertions)."""

    def __init__(self, events: list, name: str) -> None:
        self._events = events
        self._name = name

    def triage_once(self, pending=None, shard=None):
        self._events.append(("d", self._name, shard))

    def propose_once(self):
        self._events.append(("d", self._name, None))

    def admit_once(self):
        self._events.append(("d", self._name, None))


def test_beats_order_triage_divergent_then_architect_then_owner(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    events: list = []
    t0 = _Phase(events, "triage0")
    t1 = _Phase(events, "triage1")
    div = _Phase(events, "divergent")
    architect = _Phase(events, "architect")
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
        architects=[architect],
        divergents=[div],
        owner=owner,
    )
    orch.run_round("c")

    kinds = [e[1] if e[0] == "d" else e[0] for e in events if e[0] in ("session", "d")]
    # a → first beat (triage×2 ∥ divergent, order within group undefined) → second beat architect → owner conclusion (no dev beat)
    assert kinds[0] == "session"
    assert set(kinds[1:4]) == {"triage0", "triage1", "divergent"}
    assert kinds[4:] == ["architect", "owner"]
    # shard parameters: the k-th triager receives (k, n)
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
    orch.run_round("c")  # owner=None does not raise; admission stage is skipped
    kinds = [e[1] if e[0] == "d" else e[0] for e in events if e[0] in ("session", "d")]
    assert kinds == ["session", "triage"]


def test_owner_failure_blocks_round_instead_of_advancing(tmp_path) -> None:
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked

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
    """When fixed_set is callable, resample session plan each round."""
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


# Spec-0050/T3: final round user-only; gate failure does not open next user round.


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
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked, wait_round_delivery

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
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked

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
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked

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


def test_recovery_users_reconcile_session_store_and_run_only_missing_items(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    calls: list[str] = []
    reconciled = 0

    def run_user(persona, scenario, harness, *, workspace_dir=None):
        calls.append(scenario.description)
        return {"session_id": current_usage_context().session_id}

    def load_completed(session_id):
        nonlocal reconciled
        reconciled += 1
        return {"session_id": session_id} if reconciled == 1 else None

    run_user.load_completed_session = load_completed
    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[
            (_persona(), SeedScenario(description="already-saved")),
            (_persona(), SeedScenario(description="missing")),
        ],
        run_session_fn=run_user,
        initial_ref="main",
        recovery=_recovery(tmp_path),
    )
    orch.run_round("main", round_no=1, deliver=False)
    assert reconciled == 2
    assert calls == ["missing"]


def test_recovery_users_preserve_configured_parallelism(tmp_path) -> None:
    """A resumable round runs independent user envelopes concurrently."""
    import time

    repo = _seed_repo(tmp_path)
    lock = threading.Lock()
    active = 0
    max_active = 0

    def run_user(*args, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"session_id": current_usage_context().session_id}

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[
            (_persona(), SeedScenario(description="one")),
            (_persona(), SeedScenario(description="two")),
        ],
        run_session_fn=run_user,
        initial_ref="main",
        max_parallel_users=2,
        recovery=_recovery(tmp_path),
    )
    orch.run_round("main", round_no=1, deliver=False)
    assert max_active == 2


def test_recovery_refresh_rebinds_feedback_roles_to_restored_ledger(tmp_path):
    """Spec-0079/T3: both stage owner and role units use the restored store."""
    repo = _seed_repo(tmp_path)
    bound = []

    class Role:
        def bind_recovery(self, recovery):
            bound.append(recovery)

        def bind_feedback_dependency(self, prerequisite):
            assert prerequisite == "users"

    orch = Orchestrator(
        launcher=_Launcher([]),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=lambda *args, **kwargs: None,
        initial_ref="main",
        triagers=[Role()],
        recovery=_recovery(tmp_path),
    )
    original = orch._recovery
    orch.refresh_recovery()
    assert orch._recovery is not original
    assert bound == [original, orch._recovery]
    assert orch._feedback_pipeline._recovery is orch._recovery
