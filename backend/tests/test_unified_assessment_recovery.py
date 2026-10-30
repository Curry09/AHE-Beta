"""Exercise worker gating through unified.main and the real recovery orchestrator."""

from types import SimpleNamespace

import pytest

from auto_designer.experiment.controllers import unified
from auto_designer.loop.recovery import RecoveryStore
from auto_designer.loop.round_assessment import read_json, write_json
from auto_designer.tracker.fake import FakeTracker
from test_experiment_grading import archived_run, prepared_inputs  # noqa: F401
from test_experiment_round_grading import assessed_round, sealed  # noqa: F401


@pytest.fixture
def wired_main(assessed_round, monkeypatch):  # noqa: F811
    """Replace external provisioning, but keep controller, sessions, ledger and grader real."""
    from auto_designer.experiment import workload

    run, assessor, recovery, identity, arguments, _ = assessed_round
    root = run["directory"]
    assessor(recovery=recovery, **arguments)
    original_session = assessor.store.load(run["session_id"])
    state = read_json(recovery.root / "recovery.json")
    # The source fixture predates these generic recovery bookkeeping fields.
    # Complete them before executing the real orchestrator, without changing
    # the persisted Session, user input/output receipts or assessment projection.
    users = state["rounds"]["1"]["stages"]["users"]
    users["dependencies"] = ["round_started"]
    for unit in users["units"].values():
        unit.update(attempt=1, expected_postconditions={"completed": True})
    write_json(recovery.root / "recovery.json", state)
    write_json(root / "runtime/controller.json", {"nonce": "resumed-generation"})

    monkeypatch.setenv("TOTAL_ROUNDS", "1")
    monkeypatch.setenv("AUTO_DESIGNER_FROZEN_MANIFEST", str(root / "manifest.json"))
    monkeypatch.setenv("PERSONA_LIBRARY", str(root / "personas"))
    for key in ("MODEL", "BASE_URL", "API_KEY"):
        monkeypatch.setenv(f"HARNESS_LLM_{key}", "unused-local-test")
    monkeypatch.setattr(unified.runtime, "TOTAL_ROUNDS", 1)
    monkeypatch.setattr(unified.runtime, "DATA", root / "data")
    monkeypatch.setattr(unified.runtime, "ROOT", root / "source")
    runtime_functions = {
        "apply_experiment_context": lambda **kw: None,
        "_isolate_git_credentials": lambda: None,
        "_load_env": lambda path: {
            "GITEA_URL": "http://localhost",
            "OWNER": "test",
            "REPO": "test",
            "TOKEN": "unused",
        },
        "experiment_run_mode": lambda: "resume",
        "install_role_runs": lambda **kw: assessor.store.root.parent,
        "load_recovery_store": lambda **kw: RecoveryStore.open(
            root=recovery.root, identity=identity
        ),
        "existing_harness_repo": lambda: root / "harness",
        "_set_gitea_remote": lambda *args: None,
        "_on_round_end": lambda *args, **kw: None,
    }
    for name, function in runtime_functions.items():
        monkeypatch.setattr(unified.runtime, name, function)
    monkeypatch.setattr("auto_designer.experiment.context.require_controller_context", lambda: {})
    catalog = workload.read_task_catalog(root, run["manifest"])
    plan = workload.read_session_plan(root, run["manifest"])
    monkeypatch.setattr(
        "auto_designer.experiment.context.frozen_workload", lambda: (catalog, plan, {})
    )
    monkeypatch.setattr(
        "auto_designer.experiment.context.frozen_scenario", lambda **kw: original_session.scenario
    )
    monkeypatch.setattr(
        "auto_designer.loop.roster.load_roster",
        lambda: {
            "user": 1,
            "triager": 0,
            "synthesizer": 0,
            "divergent": 0,
            "owner": 0,
            "developer": 0,
        },
    )
    tracker = FakeTracker()
    monkeypatch.setattr("auto_designer.tracker.gitea.GiteaTracker", lambda **kw: tracker)
    monkeypatch.setattr("auto_designer.distill.library.PersonaLibrary", lambda path: None)
    persona = SimpleNamespace(
        persona_id=run["binding"]["persona_id"],
        d1=SimpleNamespace(value="expert"),
        d2=SimpleNamespace(stack=["python"]),
        d41=SimpleNamespace(value="delegation"),
        d5=SimpleNamespace(value="autonomous"),
    )
    monkeypatch.setattr(
        "auto_designer.user.sim.persona_io.card_to_personas", lambda library: [persona]
    )
    monkeypatch.setattr(
        "auto_designer.user.sim.persona_client.ApiPersonaClient",
        lambda: SimpleNamespace(complete=lambda *a, **kw: pytest.fail("no model call")),
    )
    monkeypatch.setattr(
        "auto_designer.experiment.controllers.feedback.assemble_feedback_roles",
        lambda **kw: {
            "triagers": [],
            "synthesizers": [],
            "divergents": [],
            "owner": None,
        },
    )
    monkeypatch.setattr("auto_designer.guards.repo_guard.snapshot_repo", lambda **kw: {})
    monkeypatch.setattr("auto_designer.guards.repo_guard.verify_unchanged", lambda **kw: None)
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.Orchestrator._assert_commit_available", lambda *a: None
    )
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.Orchestrator._assert_descendant", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.Orchestrator._resolve_head",
        lambda *a, **kw: arguments["user_sha"],
    )
    events = []
    monkeypatch.setattr(
        "auto_designer.experiment.collection.export_gitea_snapshot",
        lambda **kw: events.append("export gitea"),
    )
    monkeypatch.setattr(
        "auto_designer.experiment.continuation.export.export_continuation",
        lambda **kw: events.append("export continuation"),
    )
    monkeypatch.setattr(
        unified.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="")
    )
    monkeypatch.setattr(
        "auto_designer.harness.launcher.HarnessLauncher.launch",
        lambda *a, **kw: pytest.fail("Actor must not launch"),
    )
    return root, run, recovery.root, identity, events


def test_unified_main_seals_resumed_final_round_without_live_worker(wired_main, monkeypatch):
    root, run, checkpoint_root, identity, events = wired_main
    session_path = (
        root
        / "data/role_runs"
        / run["manifest"]["run_id"]
        / "sessions"
        / f"{run['session_id']}.json"
    )
    session_before = session_path.read_bytes()
    projection = root / "assessment/feedback/round-1.json"
    projection_before = projection.read_bytes()
    monkeypatch.setattr(
        "auto_designer.loop.round_assessment.RoundAssessment.await_worker",
        lambda self: pytest.fail("completed Actors and measurement need no live worker"),
    )
    assert unified.main() == 0
    state = RecoveryStore.open(root=checkpoint_root, identity=identity).round_state(round_no=1)
    assert state["status"] == "completed"
    assert state["stages"]["round_sealed"]["dependencies"] == ["objective_grading"]
    assert events == ["export gitea", "export continuation"]
    assert session_path.read_bytes() == session_before
    assert projection.read_bytes() == projection_before


def test_unified_main_still_blocks_unfinished_actor_until_worker_ready(wired_main, monkeypatch):
    from auto_designer.user.sim.runtime import make_empty_runtime

    root, run, checkpoint_root, identity, events = wired_main
    state = read_json(checkpoint_root / "recovery.json")
    for stage in ("users", "objective_grading"):
        state["rounds"]["1"]["stages"].pop(stage, None)
    write_json(checkpoint_root / "recovery.json", state)
    (
        root
        / "data/role_runs"
        / run["manifest"]["run_id"]
        / "sessions"
        / f"{run['session_id']}.json"
    ).unlink()
    monkeypatch.setattr(
        "auto_designer.loop.orchestrator.materialize_workspace", lambda spec: make_empty_runtime()
    )
    monkeypatch.setattr("auto_designer.loop.orchestrator.ensure_deps", lambda *args: None)
    waits = []

    def bound_wait(seconds):
        waits.append(seconds)
        raise RuntimeError("bounded observation: worker unavailable")

    monkeypatch.setattr("auto_designer.loop.round_assessment.time.sleep", bound_wait)
    assert unified.main() == 1
    assert waits == [5]
    assert read_json(root / "assessment/status.json")["reason"] == "worker_not_ready"
    assert events == []
    state = RecoveryStore.open(root=checkpoint_root, identity=identity).round_state(round_no=1)
    assert state["status"] != "completed"
    assert "round_sealed" not in state["stages"]


def test_ready_launcher_preserves_interface_and_checks_each_parallel_actor():
    from concurrent.futures import ThreadPoolExecutor
    from threading import local

    thread = local()

    def ready():
        thread.ready = True

    def launch(ref, *, workspace_dir):
        assert thread.ready
        thread.ready = False
        return ref, workspace_dir

    inner = SimpleNamespace(launch=launch, runs_root="preserved attribute")
    launcher = unified._AssessmentReadyLauncher(inner, SimpleNamespace(await_worker=ready))
    assert launcher.runs_root == inner.runs_root
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda i: launcher.launch(str(i), workspace_dir=i), range(12)))
    assert replies == [(str(i), i) for i in range(12)]
