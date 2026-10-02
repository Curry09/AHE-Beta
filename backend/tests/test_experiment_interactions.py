"""Execute frozen AABB plans and both interaction modes without models or cloud resources."""

from __future__ import annotations

import json
import random
import subprocess
from functools import partial
from pathlib import Path

import pytest

from auto_designer import invocation
from auto_designer.experiment import materials
from auto_designer.experiment.controllers import ordinary, swebench
from auto_designer.loop import live
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.models import IssueDraft, Persona, SeedScenario, WorkspaceSpec
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.run_live import expert
from test_experiment_materials import aabb_inputs as aabb_inputs
from test_experiment_materials import prepared_inputs as prepared_inputs


class RecordingHarness(ScriptedHarness):
    def __init__(self):
        super().__init__()
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return super().send(message)


class RecordingClient(ScriptedPersonaClient):
    def __init__(self, calls):
        self.calls = calls

    def respond(self, system, user):
        if "<direct_review>" in user:
            self.calls.append("review")
            return {
                "verdict": "file_issue",
                "feedback": "The response has no verified artifact.",
                "issue": "The claimed pytz API is invalid.",
                "score": 2,
                "reason": "Unverified implementation.",
            }
        self.calls.append("simulated")
        return super().respond(system, user)


@pytest.mark.parametrize("mode", ["direct", "simulated_user", None])
@pytest.mark.parametrize("controller", [ordinary, swebench], ids=["ordinary", "swebench"])
def test_controller_factory_executes_interaction_and_persists_feedback(tmp_path, controller, mode):
    sp = expert()
    persona = Persona(sp.persona_id, "expert", "python", "fix task", "precise")
    calls = []
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    factory = ordinary if controller is ordinary else controller.run_mod
    run = factory._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(calls),
        tracker=tracker,
        store=store,
        sim_personas={sp.persona_id: sp},
    )
    scenario = SeedScenario(
        "Fix timeutils and run the DST checks",
        WorkspaceSpec(
            kind="empty",
            params={"task_key": "simple-task", **({"interaction": mode} if mode else {})},
        ),
    )
    harness = RecordingHarness()
    session = run(persona, scenario, harness)
    persisted = store.load(session.session_id)
    assert persisted.issue_refs
    assert tracker.list_open_issues()
    assert run.load_completed_session(session.session_id) == persisted
    if mode == "direct":
        assert calls == ["review"]
        assert harness.messages == [scenario.description]
        assert persisted.user_outcome["interaction_mode"] == "direct"
        assert persisted.sim_trace is None
    else:
        assert "review" not in calls
        assert len(calls) > 1
        assert len(harness.messages) > 1
        assert persisted.sim_trace is not None
        assert persisted.sim_trace.turns


@pytest.mark.parametrize("controller", [ordinary, swebench], ids=["ordinary", "swebench"])
def test_frozen_aabb_plan_drives_four_orchestrator_rounds(
    aabb_inputs, tmp_path, monkeypatch, controller
):
    manifest = materials.prepare_materials(aabb_inputs, tmp_path / "runs")
    plan_path = Path(manifest["run_dir"]) / manifest["materials"]["interaction_plan"]["path"]
    plan = json.loads(plan_path.read_text())
    # The operator's originals can change after prepare; execution only uses the frozen plan.
    aabb_inputs.write_text("{}")
    (tmp_path / "personas.json").write_text("[]")
    materials.verify_materials(manifest)
    ids = manifest["config"]["workload"]["persona_ids"]
    personas = {
        identity: Persona(identity, "expert", "python", "fix", "precise") for identity in ids
    }
    scenarios = {
        "simple-task": SeedScenario(
            "frozen instruction",
            WorkspaceSpec(
                kind="empty", params={"interaction": "direct", "task_key": "simple-task"}
            ),
        )
    }
    current = {"round": 0}
    pair_log = {}
    if controller is swebench:
        frozen = controller._load_interaction_plan(
            path=plan_path, total_rounds=4, persona_ids=ids, instance_ids=list(scenarios)
        )
        monkeypatch.setattr(controller, "FROZEN_INTERACTION_PLAN", frozen)
        monkeypatch.setattr(controller, "ALL_ONCE", True)

    def session_plan():
        if controller is ordinary:
            return controller._planned_session_set(
                plan=plan, round_no=current["round"], personas=personas, scenarios=scenarios
            )
        return controller._session_set(
            rng=random.Random(123),
            round_no=current["round"],
            personas=personas,
            scenarios=scenarios,
            pair_log=pair_log,
        )

    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "entry.py").write_text("pass\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )
    executed = []
    calls = []
    store = SessionStore(tmp_path / "sessions")
    tracker = FakeTracker()
    session_factory = ordinary if controller is ordinary else controller.run_mod
    user_run_session = session_factory._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(calls),
        tracker=tracker,
        store=store,
        sim_personas={},
    )
    round_shas = [] if controller is ordinary else {}
    pressure_rounds = []
    receipts = []
    live_rounds = []
    checker = ordinary._check_backpressure

    def checked_pressure(*, tracker, round_no):
        pressure_rounds.append(round_no)
        checker(tracker=tracker, round_no=round_no)

    monkeypatch.setattr(ordinary, "_check_backpressure", checked_pressure)
    monkeypatch.setattr(invocation, "append_round", lambda **kwargs: receipts.append(kwargs))
    monkeypatch.setattr(
        live, "update_live_run", lambda **kwargs: live_rounds.append(kwargs["round_no"])
    )
    monkeypatch.setattr(ordinary, "TOTAL_ROUNDS", 4)

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            return RecordingHarness()

    def session_runner(persona, scenario, harness, *, workspace_dir=None):
        executed.append((current["round"], persona.identity, scenario.description))
        session = user_run_session(persona, scenario, harness, workspace_dir=workspace_dir)
        assert harness.messages == [scenario.description]
        assert store.load(session.session_id).issue_refs

    orchestrator = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=session_plan,
        run_session_fn=session_runner,
        initial_ref="main",
        on_round_start=lambda number: current.update(round=number),
        on_round_end=partial(controller._on_round_end, tracker=tracker, round_shas=round_shas),
    )
    assert len(orchestrator.run(4)) == 4
    assert executed == [
        (index, persona, "frozen instruction")
        for index, persona in enumerate((ids[0], ids[0], ids[1], ids[1]), start=1)
    ]
    assert calls == ["review"] * 4
    assert len(tracker.list_open_issues()) == 4
    assert pressure_rounds == [1, 2, 3, 4]
    assert live_rounds == [1, 2, 3, 4]
    assert [receipt["round_no"] for receipt in receipts] == [1, 2, 3, 4]
    assert len(round_shas) == 4
    if controller is swebench:
        assert pair_log == {index: [(persona, "simple-task")] for index, persona, _ in executed}


def test_ordinary_plan_resolves_task_identity_instead_of_ignoring_it():
    persona = Persona("a", "expert", "python", "fix", "precise")
    with pytest.raises(KeyError, match="unknown-task"):
        ordinary._planned_session_set(
            plan=[[["a", "unknown-task"]]],
            round_no=1,
            personas={"a": persona},
            scenarios={"simple-task": SeedScenario("instruction")},
        )


@pytest.mark.parametrize("extra", [None, "proposal", "ready", "openagents"])
def test_backpressure_counts_open_queues_and_warns_only_above_threshold(monkeypatch, capsys, extra):
    tracker = FakeTracker()
    monkeypatch.setenv("PROPOSAL_DEPTH_ALARM", "2")
    monkeypatch.setenv("READY_DEPTH_ALARM", "2")
    for label in ("proposal", "proposal", "ready", "openagents"):
        tracker.create_issue(IssueDraft(label, "pending", [label]))
    for label in ("proposal", "ready"):
        closed = tracker.create_issue(IssueDraft("closed", "completed", [label]))
        tracker.set_state(closed.number, "closed", "done")
    tracker.create_issue(IssueDraft("raw feedback", "untriaged", ["report"]))
    if extra is not None:
        tracker.create_issue(IssueDraft("extra pending", "over threshold", [extra]))
    ordinary._check_backpressure(tracker=tracker, round_no=9)
    warnings = capsys.readouterr().out
    if extra is None:
        assert warnings == ""
    else:
        plane = "proposal" if extra == "proposal" else "ready"
        assert f"第 9 轮末 {plane} 深度 3 > 2" in warnings
        assert warnings.count("[背压告警]") == 1


def test_backpressure_read_failure_does_not_block_the_completed_round(monkeypatch, capsys):
    tracker = FakeTracker()

    def failed_read():
        raise RuntimeError("tracker unavailable")

    monkeypatch.setattr(tracker, "list_open_issues", failed_read)
    ordinary._check_backpressure(tracker=tracker, round_no=1)
    assert capsys.readouterr().out == ""
