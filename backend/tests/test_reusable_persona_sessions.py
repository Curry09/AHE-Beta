"""Spec-0080/T2: reused cards have independent execution, feedback and recovery."""

import json
import threading
from dataclasses import replace
from functools import partial

import pytest

from auto_designer.demand.evidence_contract import build_l1_summary
from auto_designer.experiment.controllers import runtime, unified
from auto_designer.loop import live
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.recovery import RecoveryConflictError, operation_key
from auto_designer.loop.round_gate import RoundDeliveryBlocked
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import current_usage_context
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.run_live import expert
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime
from test_experiment_interactions import RecordingClient
from test_experiment_multitask_controller import _binding, _recovery, _repo, _resolve


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_repeated_pair_has_independent_clients_workspaces_feedback_and_recovery(
    tmp_path, monkeypatch, mode, interrupt
):
    repo = _repo(tmp_path / "harness")
    plan = [_binding("same-card", "ordinary", i, round_no=1, mode=mode) for i in range(2)]
    store, tracker = SessionStore(tmp_path / "sessions"), FakeTracker()
    ledger = _recovery(tmp_path / "ledger")
    clients, attempts, records, calls = [], [], [], []
    lock, barrier = threading.Lock(), threading.Barrier(2)
    fail = [interrupt]

    def client_factory():
        client = RecordingClient(calls)
        with lock:
            clients.append(client)
        return client

    runner = runtime._make_user_run_session_fn(
        client_factory=client_factory,
        tracker=tracker,
        store=store,
        sim_personas={"same-card": replace(expert(), persona_id="same-card")},
    )

    def provision(spec):
        ctx = current_usage_context()
        with lock:
            attempts.append((ctx.slot, ctx.attempt, ctx.session_id))
        if ctx.slot == 1 and fail[0]:
            raise RuntimeError("interrupted slot 1 setup")
        directory = tmp_path / f"{ctx.session_id}-{ctx.attempt}"
        directory.mkdir()
        (directory / "owner").write_text(ctx.session_id)
        return LocalWorkspaceRuntime(
            directory, owns_tmp=True, evidence={"patch_capability": "not_applicable"}
        )

    monkeypatch.setattr("auto_designer.loop.orchestrator.materialize_workspace", provision)

    class Harness(ScriptedHarness):
        def __init__(self, workspace):
            super().__init__()
            self.workspace = workspace
            self.first = True

        def send(self, message):
            ctx = current_usage_context()
            if self.first:
                self.first = False
                if not interrupt:
                    barrier.wait(timeout=10)
                result = self.workspace.run("cat owner", timeout=5)
                assert result["stdout"].strip() == ctx.session_id
                with lock:
                    records.append((ctx.slot, ctx.session_id, str(self.workspace)))
            return super().send(message)

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            return Harness(workspace_dir)

    def orchestrator():
        return Orchestrator(
            launcher=Launcher(),
            harness_repo=str(repo),
            fixed_set=[],
            run_session_fn=runner,
            initial_ref="main",
            recovery=ledger,
            max_parallel_users=2,
            task_kinds={"ordinary": "ordinary"},
            frozen_session_plan=lambda round_no: plan,
            resolve_session=lambda binding: _resolve(binding, tmp_path),
            on_session_event=partial(unified._observe_session, data_dir=tmp_path, persona_meta={}),
        )

    if interrupt:
        with pytest.raises(RoundDeliveryBlocked, match="user-sessions-incomplete"):
            orchestrator().run(1)
        assert len(store.index(include_invalid=True)) == 1
        saved = store.load(store.index(include_invalid=True)[0]["session_id"]).to_dict()
        issue_count = len(tracker.list_open_issues())
        assert attempts.count((0, 1, operation_key("run", "users", plan[0]))) == 1
        fail[0] = False
    orchestrator().run(1)
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert len(records) == 2
    assert len({row[1] for row in records}) == len({row[2] for row in records}) == 2
    sessions = [store.load(row["session_id"]) for row in store.index(include_invalid=True)]
    assert {s.persona.identity for s in sessions} == {"same-card"}
    assert {s.session_provenance["slot"] for s in sessions} == {0, 1}
    assert {s.session_id for s in sessions} == {operation_key("run", "users", b) for b in plan}
    assert all(build_l1_summary(s)["task_id"] == "ordinary" for s in sessions)
    assert len(live.read_agents(data_dir=tmp_path)) == 2
    assert len(live.read_history(data_dir=tmp_path)) == 2
    issues = [ref.number for s in sessions for ref in s.issue_refs]
    assert issues and len(issues) == len(set(issues)) == len(tracker.list_open_issues())
    units = ledger.round_state(round_no=1)["stages"]["users"]["units"]
    assert len(units) == 2 and all(u["status"] == "completed" for u in units.values())
    if interrupt:
        assert store.load(saved["session_id"]).to_dict() == saved
        assert len(tracker.list_open_issues()) > issue_count
        assert len(attempts) == 3
        assert (1, 2, operation_key("run", "users", plan[1])) in attempts
    before = (len(clients), len(attempts), len(issues))
    orchestrator().run(1)
    assert (len(clients), len(attempts), len(tracker.list_open_issues())) == before


@pytest.mark.parametrize("slot", [0, 2, True])
def test_duplicate_missing_or_boolean_slot_still_rejected(tmp_path, slot):
    plan = [_binding("same-card", "ordinary", i, round_no=1, mode="direct") for i in range(2)]
    plan[1]["slot"] = slot
    orch = Orchestrator(
        launcher=None,
        initial_ref="main",
        recovery=_recovery(tmp_path / "ledger"),
        harness_repo=str(tmp_path),
        fixed_set=[],
        run_session_fn=lambda *args, **kwargs: None,
        frozen_session_plan=lambda round_no: plan,
        resolve_session=lambda binding: None,
        task_kinds={"ordinary": "ordinary"},
    )
    with pytest.raises(RecoveryConflictError, match="logical session binding"):
        orch._logical_plan(round_no=1)


def test_binding_roundtrip_does_not_mutate_reused_input(tmp_path):
    plan = [_binding("same-card", "ordinary", i, round_no=1, mode="direct") for i in range(2)]
    original = json.dumps(plan)
    orch = Orchestrator(
        launcher=None,
        initial_ref="main",
        recovery=_recovery(tmp_path / "ledger"),
        harness_repo=str(tmp_path),
        fixed_set=[],
        run_session_fn=lambda *args, **kwargs: None,
        frozen_session_plan=lambda round_no: plan,
        resolve_session=lambda binding: None,
        task_kinds={"ordinary": "ordinary"},
    )
    compiled = orch._logical_plan(round_no=1)
    compiled[0]["persona_id"] = "changed"
    assert json.dumps(plan) == original
