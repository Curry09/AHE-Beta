"""Execute logical frozen sessions, mixed modes, fan-out and recovery offline."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

from auto_designer import invocation
from auto_designer.demand.evidence_contract import build_l1_summary
from auto_designer.experiment import context, materials, workload
from auto_designer.experiment.controllers import runtime, unified
from auto_designer.loop import live
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore, operation_key
from auto_designer.loop.round_gate import RoundDeliveryBlocked
from auto_designer.models import (
    FeelingScore,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    WorkspaceSpec,
    bound_session_provenance,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.run_live import expert
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime
from test_experiment_interactions import RecordingClient
from test_experiment_materials import aabb_inputs as aabb_inputs
from test_experiment_materials import prepared_inputs as prepared_inputs
from test_experiment_workload import multiple_inputs as multiple_inputs
from test_experiment_workload import task_resources


def _repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "entry.py").write_text("pass\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return path


def _recovery(path):
    return RecoveryStore.initialize(
        root=path,
        identity=RecoveryIdentity(
            experiment_id="exp",
            run_id="run",
            config_hash="config",
            controller_sha="source",
            plan_hash="plan",
        ),
    )


def _binding(persona, task, slot, *, round_no, mode):
    return {
        "round_no": round_no,
        "slot": slot,
        "persona_id": persona,
        "task_id": task,
        "task_digest": ("a" if task == "ordinary" else "b") * 64,
        "interaction": mode,
    }


def _resolve(binding, source):
    return Persona(binding["persona_id"], "expert", "python", "task", "precise"), SeedScenario(
        f"Fix {binding['task_id']}",
        WorkspaceSpec(
            kind="empty",
            params={
                "source": str(source),
                "instance_id": binding["task_id"],
                "task_id": binding["task_id"],
                "task_digest": binding["task_digest"],
                "task_kind": "ordinary" if binding["task_id"] == "ordinary" else "swebench",
                "interaction": binding["interaction"],
            },
        ),
    )


@pytest.mark.parametrize("n_users", [4, 8])
def test_same_task_many_users_have_independent_workspaces_and_bounded_fanout(
    tmp_path, monkeypatch, n_users
):
    repo = _repo(tmp_path / "harness")
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "editable.py").write_text("BASE = 1\n")
    records, provision_contexts = [], []
    active, peak = [0], [0]
    lock = threading.Lock()
    plan = [
        _binding(f"p-{index}", "ordinary", index, round_no=1, mode="direct")
        for index in range(n_users)
    ]
    store, tracker = SessionStore(tmp_path / "sessions"), FakeTracker()
    client_calls = []
    runner = runtime._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(client_calls),
        tracker=tracker,
        store=store,
        sim_personas={},
    )

    def materialize(spec):
        ctx = current_usage_context()
        provision_contexts.append(ctx)
        assert ctx.session_id and ctx.attempt == 1 and ctx.task_id == "ordinary"
        destination = tmp_path / ctx.session_id
        shutil.copytree(baseline, destination)
        # Verify Python imports from the local editable checkout, not another slot.
        (destination / "editable.py").write_text(f"OWNER = {ctx.persona_id!r}\n")
        return LocalWorkspaceRuntime(
            destination, owns_tmp=True, evidence={"patch_capability": "not_applicable"}
        )

    monkeypatch.setattr("auto_designer.loop.orchestrator.materialize_workspace", materialize)

    class Harness(ScriptedHarness):
        def __init__(self, ws):
            super().__init__()
            self.ws = ws

        def send(self, message):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                time.sleep(0.02)
                response = self.ws.run(
                    "python3 -c 'import editable; print(editable.OWNER)'", timeout=5
                )
                assert response["returncode"] == 0
                ctx = current_usage_context()
                assert response["stdout"].strip() == ctx.persona_id
                records.append((ctx.session_id, ctx.persona_id, str(self.ws)))
                return super().send(message)
            finally:
                with lock:
                    active[0] -= 1

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            assert current_usage_context().harness_sha == ref
            return Harness(workspace_dir)

    orch = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        max_parallel_users=2,
        recovery=_recovery(tmp_path / "ledger"),
        task_kinds={"ordinary": "ordinary", "swe": "swebench", "simple-task": "ordinary"},
        frozen_session_plan=lambda round_no: plan,
        resolve_session=lambda binding: _resolve(binding, baseline),
        on_session_event=partial(unified._observe_session, data_dir=tmp_path, persona_meta={}),
    )
    assert len(orch.run(1)) == 1
    assert peak[0] == 2
    assert len({record[0] for record in records}) == n_users
    assert len({record[2] for record in records}) == n_users
    assert len(store.index(include_invalid=True)) == n_users
    assert len(tracker.list_open_issues()) == n_users
    assert len(live.read_agents(data_dir=tmp_path)) == n_users
    assert len(live.read_history(data_dir=tmp_path)) == n_users
    assert (baseline / "editable.py").read_text() == "BASE = 1\n"
    assert all(ctx.slot is not None and ctx.task_digest == "a" * 64 for ctx in provision_contexts)
    for index in store.index():
        session = store.load(index["session_id"])
        summary = build_l1_summary(session)
        assert summary["task_id"] == "ordinary"
        assert summary["task_kind"] == "ordinary"
        assert "source" not in summary
        assert live.read_history(data_dir=tmp_path)[0]["session_provenance"]


def test_mixed_tasks_use_both_modes_and_first_progress_has_stable_identity(tmp_path):
    repo = _repo(tmp_path / "harness")
    plan = [
        _binding("expert-dev", "ordinary", 0, round_no=1, mode="simulated_user"),
        _binding("other", "swe", 1, round_no=1, mode="direct"),
    ]
    store, tracker = SessionStore(tmp_path / "sessions"), FakeTracker()
    progress, calls = [], []
    runner = runtime._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(calls),
        tracker=tracker,
        store=store,
        sim_personas={"expert-dev": replace(expert(), persona_id="expert-dev")},
        on_turn=lambda identity, sp, result, running, session_id=None: progress.append(
            (identity, session_id, current_usage_context())
        ),
    )

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            return ScriptedHarness()

    orch = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        recovery=_recovery(tmp_path / "ledger"),
        task_kinds={"ordinary": "ordinary", "swe": "swebench", "simple-task": "ordinary"},
        frozen_session_plan=lambda round_no: plan,
        resolve_session=lambda binding: _resolve(binding, tmp_path),
        on_session_event=partial(unified._observe_session, data_dir=tmp_path, persona_meta={}),
    )
    orch.run(1)
    sessions = [store.load(row["session_id"]) for row in store.index(include_invalid=True)]
    assert {session.session_provenance["task_kind"] for session in sessions} == {
        "ordinary",
        "swebench",
    }
    assert calls.count("review") == 1 and "simulated" in calls
    simulated = next(session for session in sessions if session.sim_trace is not None)
    assert progress[0][1] == simulated.session_id == progress[0][2].session_id
    assert progress[0][2].task_id == "ordinary"
    assert (
        progress[0][2].round_no == 1 and progress[0][2].agent_id == f"user-{simulated.session_id}"
    )
    assert len(live.read_history(data_dir=tmp_path)) == 2


def test_partial_failure_recovery_keeps_keys_inputs_and_completed_sessions_when_coordinates_change(
    tmp_path, monkeypatch
):
    repo = _repo(tmp_path / "harness")
    plan = [_binding(f"p-{i}", "ordinary", i, round_no=1, mode="direct") for i in range(4)]
    source, fail = [tmp_path / "old"], [True]
    store, tracker = SessionStore(tmp_path / "sessions"), FakeTracker()
    calls, attempts, resolved = [], [], []
    runner = runtime._make_user_run_session_fn(
        client_factory=lambda: RecordingClient(calls), tracker=tracker, store=store, sim_personas={}
    )

    def materialize(spec):
        ctx = current_usage_context()
        attempts.append((ctx.persona_id, ctx.attempt, ctx.session_id, spec.params["source"]))
        if ctx.persona_id == "p-1" and fail[0]:
            raise RuntimeError("setup interrupted")
        destination = tmp_path / f"{ctx.session_id}-{ctx.attempt}"
        destination.mkdir()
        return LocalWorkspaceRuntime(
            destination, owns_tmp=True, evidence={"patch_capability": "not_applicable"}
        )

    monkeypatch.setattr("auto_designer.loop.orchestrator.materialize_workspace", materialize)

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            return ScriptedHarness()

    recovery = _recovery(tmp_path / "ledger")

    def resolve(binding):
        resolved.append(binding["persona_id"])
        return _resolve(binding, source[0])

    def orchestrator():
        return Orchestrator(
            launcher=Launcher(),
            harness_repo=str(repo),
            fixed_set=[],
            run_session_fn=runner,
            initial_ref="main",
            recovery=recovery,
            max_parallel_users=2,
            task_kinds={"ordinary": "ordinary", "swe": "swebench", "simple-task": "ordinary"},
            frozen_session_plan=lambda round_no: plan,
            resolve_session=resolve,
            on_session_event=partial(unified._observe_session, data_dir=tmp_path, persona_meta={}),
        )

    with pytest.raises(RoundDeliveryBlocked, match="user-sessions-incomplete"):
        orchestrator().run(1)
    units = recovery.snapshot()["rounds"]["1"]["stages"]["users"]["units"]
    inputs = {key: unit["input_digest"] for key, unit in units.items()}
    assert len(store.index(include_invalid=True)) == 3
    source[0], fail[0] = tmp_path / "reprovisioned", False
    orchestrator().run(1)
    units = recovery.snapshot()["rounds"]["1"]["stages"]["users"]["units"]
    assert inputs == {key: unit["input_digest"] for key, unit in units.items()}
    assert [(persona, attempt) for persona, attempt, _, _ in attempts].count(("p-1", 2)) == 1
    assert len(attempts) == len(resolved) == 5
    assert (
        len(store.index(include_invalid=True)) == len(tracker.list_open_issues()) == len(calls) == 4
    )
    assert len(live.read_history(data_dir=tmp_path)) == 4
    assert recovery.round_state(round_no=1)["plan"] == plan
    assert all("scenario" not in unit["input"] for unit in units.values())


@pytest.mark.parametrize(
    "wrong", ["run_id", "task_id", "persona_id", "task_kind", "slot", "interaction", "harness_sha"]
)
def test_wrong_cached_task_is_rejected_before_index_reconciliation_and_round_seal(tmp_path, wrong):
    repo = _repo(tmp_path / "harness")
    binding = _binding("p", "ordinary", 0, round_no=1, mode="direct")
    key = operation_key("run", "users", binding)
    persona, scenario = _resolve(binding, tmp_path)
    provenance = {
        "contract_version": 1,
        "run_id": "run",
        **binding,
        "task_kind": "ordinary",
        "harness_sha": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip(),
    }
    wrong_values = {
        "run_id": "other-run",
        "task_id": "other-task",
        "persona_id": "other-persona",
        "task_kind": "swebench",
        "slot": 7,
        "interaction": "simulated_user",
        "harness_sha": "bad-sha",
    }
    provenance[wrong] = wrong_values[wrong]
    if wrong in {"task_id", "task_kind", "interaction"}:
        scenario.workspace.params[wrong] = wrong_values[wrong]
    if wrong == "persona_id":
        persona.identity = wrong_values[wrong]
    cached = Session(
        persona,
        scenario,
        Transcript(),
        FeelingScore(2, "wrong source"),
        session_id=key,
        session_provenance=provenance,
    )
    store = SessionStore(tmp_path / "sessions")
    store.root.mkdir()
    (store.root / f"{key}.json").write_text(json.dumps(cached.to_dict()))
    tracker = FakeTracker()
    runner = runtime._make_user_run_session_fn(
        client_factory=ScriptedPersonaClient, tracker=tracker, store=store, sim_personas={}
    )

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            pytest.fail("bad cache must block before launch")

    recovery = _recovery(tmp_path / "ledger")
    orch = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        recovery=recovery,
        task_kinds={"ordinary": "ordinary", "swe": "swebench", "simple-task": "ordinary"},
        frozen_session_plan=lambda round_no: [binding],
        resolve_session=lambda value: (persona, scenario),
    )
    with pytest.raises(RoundDeliveryBlocked):
        orch.run(1)
    assert not (store.root / "index.json").exists()
    assert recovery.stage_status(round_no=1, stage="users") != "completed"
    assert recovery.round_state(round_no=1).get("sealed_sha") is None
    assert not tracker.list_open_issues()


def test_frozen_aabb_plan_executes_rounds_and_shared_pressure_callback(
    aabb_inputs, tmp_path, monkeypatch
):
    package = json.loads((tmp_path / "task.json").read_text())
    package["interaction"] = "direct"
    (tmp_path / "task.json").write_text(json.dumps(package))
    manifest = materials.prepare_materials(aabb_inputs, tmp_path / "runs")
    plan = workload.read_session_plan(Path(manifest["run_dir"]), manifest)
    aabb_inputs.write_text("{}")
    repo = _repo(tmp_path / "harness")
    tracker, store = FakeTracker(), SessionStore(tmp_path / "sessions")
    called, pressure = [], []
    runner = runtime._make_user_run_session_fn(
        client_factory=ScriptedPersonaClient, tracker=tracker, store=store, sim_personas={}
    )

    def resolve(binding):
        # Frozen AABB catalog is an ordinary task; use actual logical bindings/digest.
        persona = Persona(binding["persona_id"], "expert", "python", "task", "precise")
        return persona, SeedScenario(
            "frozen task",
            WorkspaceSpec(
                kind="empty",
                params={
                    "task_id": binding["task_id"],
                    "task_digest": binding["task_digest"],
                    "task_kind": "ordinary",
                    "interaction": "simulated_user",
                },
            ),
        )

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            called.append(current_usage_context().persona_id)
            return ScriptedHarness()

    def direct_resolve(binding):
        persona, scenario = resolve(binding)
        scenario.workspace.params["interaction"] = "direct"
        return persona, scenario

    monkeypatch.setattr(invocation, "append_round", lambda **kwargs: None)
    monkeypatch.setattr(
        runtime, "_check_backpressure", lambda **kwargs: pressure.append(kwargs["round_no"])
    )
    monkeypatch.setattr(runtime, "DATA", tmp_path)
    monkeypatch.setattr(runtime, "TOTAL_ROUNDS", 4)
    orch = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        recovery=_recovery(tmp_path / "ledger"),
        task_kinds={"ordinary": "ordinary", "swe": "swebench", "simple-task": "ordinary"},
        frozen_session_plan=lambda round_no: plan["rounds"][round_no - 1],
        resolve_session=direct_resolve,
        on_round_end=partial(runtime._on_round_end, tracker=tracker, round_shas=[]),
    )
    orch.run(4)
    ids = manifest["config"]["workload"]["persona_ids"]
    assert called == [ids[0], ids[0], ids[1], ids[1]]
    assert pressure == [1, 2, 3, 4]
    assert len(store.index(include_invalid=True)) == 4
    assert "owner" not in orch._recovery.round_state(round_no=4)["stages"]


def test_controller_resolver_selects_each_actual_frozen_task(
    multiple_inputs, tmp_path, monkeypatch
):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    catalog = workload.read_task_catalog(root, manifest)
    resources = task_resources(catalog)
    for task in resources.values():
        task["params"]["workload_contract_version"] = 1
    (root / "resources.json").write_text(json.dumps(resources))
    env = {
        "AUTO_DESIGNER_WORKLOAD_CONTRACT_VERSION": "1",
        "AUTO_DESIGNER_TASK_CATALOG": str(root / manifest["materials"]["task_catalog"]["path"]),
        "AUTO_DESIGNER_TASK_WORKSPACES_FILE": str(root / "resources.json"),
        "AUTO_DESIGNER_FROZEN_MANIFEST": str(root / "manifest.json"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sp = expert()
    plan = context.frozen_workload()[1]
    for binding in plan["rounds"][0]:
        _, scenario = unified._resolve_frozen_session(binding, {binding["persona_id"]: sp})
        assert scenario.workspace.params["task_id"] == binding["task_id"]
        assert scenario.workspace.params["task_digest"] == binding["task_digest"]
        assert scenario.workspace.params["image"] == f"image-{binding['task_id']}"
    with pytest.raises(Exception, match="explicit task_id"):
        unified._resolve_frozen_session({"persona_id": "p", "task_id": "absent"}, {"p": sp})


@pytest.mark.parametrize("wrong", ["contract_version", "task_id", "persona_id"])
def test_authoritative_save_rejects_wrong_binding_before_writing(tmp_path, wrong):
    persona, scenario = _resolve(_binding("p", "ordinary", 0, round_no=1, mode="direct"), tmp_path)
    ctx = {
        "run_id": "run",
        "round_no": 1,
        "slot": 0,
        "persona_id": "p",
        "task_id": "ordinary",
        "task_digest": "a" * 64,
        "task_kind": "ordinary",
        "harness_sha": "sha",
        "interaction_mode": "direct",
    }
    store = SessionStore(tmp_path / "sessions")
    with bind_usage_context(**ctx):
        provenance = bound_session_provenance()
        provenance[wrong] = True if wrong == "contract_version" else "wrong"
        session = Session(
            persona, scenario, Transcript(), FeelingScore(2, "bad"), session_provenance=provenance
        )
        with pytest.raises(ValueError, match="provenance"):
            store.save(session)
    assert not (store.root / f"{session.session_id}.json").exists()
    assert not (store.root / "index.json").exists()


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_real_unified_main_uses_frozen_catalog_and_terminal_user_only_plan(
    prepared_inputs, tmp_path, monkeypatch, backend
):
    from types import SimpleNamespace

    from auto_designer.experiment.context import build_controller_environment

    config = json.loads(prepared_inputs.read_text())
    config["rounds"]["count"] = 1
    config["roles"].update(triager=0, synthesizer=0)
    if backend == "e2b":
        config["runtime"] = {
            "backend": "e2b",
            "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
            "e2b": {"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600},
        }
    prepared_inputs.write_text(json.dumps(config))
    package = json.loads((tmp_path / "task.json").read_text())
    package["interaction"] = "direct"
    (tmp_path / "task.json").write_text(json.dumps(package))
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    resources = {
        "gitea": {"url": "https://offline.example", "owner": "test", "repo": "test"},
        "task_workspaces": task_resources(workload.read_task_catalog(root, manifest)),
    }
    if backend == "e2b":
        resources["sandbox_id"] = "offline-sandbox"
        for resource in resources["task_workspaces"].values():
            resource["kind"] = "prebuilt"
    env = build_controller_environment(
        run_dir=root,
        manifest=manifest,
        resources=resources,
        credentials={
            "GITEA_TOKEN": "offline",
            "MODEL_API_KEY": "offline",
            "MODEL_BASE_URL": "https://offline.example",
        },
    )
    for key in (
        "ROLE_RUNS_DIR",
        "AUTO_DESIGNER_USAGE_PATH",
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.setenv(key, "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in (
        "DATA",
        "ROOT",
        "HARNESS_REPO",
        "_SANDBOX_ROOT",
        "_VIGIL_CONTAINER",
        "_VIGIL_NETWORK",
        "_VIGIL_CONFIG_STAGING",
        "GITEA_ENV_FILE",
        "TOTAL_ROUNDS",
    ):
        monkeypatch.setattr(runtime, key, getattr(runtime, key))
    harness_repo = _repo(tmp_path / "offline-harness")
    tracker, calls, launches = FakeTracker(), [], []
    monkeypatch.setattr(runtime, "_isolate_git_credentials", lambda: None)
    monkeypatch.setattr(runtime, "_seed_harness_repo", lambda: harness_repo)
    monkeypatch.setattr(runtime, "_set_gitea_remote", lambda *args: None)
    monkeypatch.setattr(runtime, "_reset_to_initial", lambda *args: None)
    monkeypatch.setattr(
        runtime,
        "start_vigil",
        lambda **kwargs: pytest.fail("terminal round starts no delivery plane"),
    )
    monkeypatch.setattr("auto_designer.tracker.gitea.GiteaTracker", lambda **kwargs: tracker)
    monkeypatch.setattr(
        "auto_designer.user.sim.persona_client.ApiPersonaClient",
        lambda: SimpleNamespace(complete=None),
    )
    monkeypatch.setattr(
        "auto_designer.user.sim.persona_client.AgenticPersonaClient",
        lambda complete: RecordingClient(calls),
    )
    monkeypatch.setattr(
        "auto_designer.guards.repo_guard.snapshot_repo", lambda **kwargs: ("test", "")
    )
    monkeypatch.setattr("auto_designer.guards.repo_guard.verify_unchanged", lambda **kwargs: None)

    def materialize(spec):
        ctx = current_usage_context()
        launches.append((ctx.session_id, ctx.task_id, ctx.task_digest, ctx.attempt, spec.kind))
        directory = tmp_path / ctx.session_id
        directory.mkdir()
        return LocalWorkspaceRuntime(
            directory, owns_tmp=True, evidence={"patch_capability": "not_applicable"}
        )

    monkeypatch.setattr("auto_designer.loop.orchestrator.materialize_workspace", materialize)

    class Launcher:
        def __init__(self, **kwargs):
            pass

        def launch(self, ref, workspace_dir=None):
            return ScriptedHarness()

    monkeypatch.setattr("auto_designer.harness.launcher.HarnessLauncher", Launcher)
    assert unified.main() == 0
    assert calls == ["review"]
    assert len(launches) == 1 and launches[0][3] == 1
    assert launches[0][4] == ("docker-seed" if backend == "local" else "prebuilt")
    recovery = json.loads((root / "checkpoints/recovery.json").read_text())
    assert "owner" not in recovery["rounds"]["1"]["stages"]
    session_store = SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions")
    assert len(session_store.index()) == 1
    assert session_store.index()[0]["task_id"] == "simple-task"


@pytest.mark.parametrize("field,value", [("round_no", True), ("slot", False)])
def test_internal_logical_plan_rejects_bool_round_and_slot(tmp_path, field, value):
    from auto_designer.loop.recovery import RecoveryConflictError

    repo = _repo(tmp_path / "harness")
    binding = _binding("p", "ordinary", 0, round_no=1, mode="direct")
    binding[field] = value

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            pytest.fail("invalid logical binding must fail before launch")

    def resolve(binding):
        pytest.fail("invalid logical binding must fail before workspace resolution")

    orchestrator = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=lambda *args, **kwargs: pytest.fail("invalid plan ran a session"),
        initial_ref="main",
        recovery=_recovery(tmp_path / "ledger"),
        frozen_session_plan=lambda round_no: [binding],
        resolve_session=resolve,
        task_kinds={"ordinary": "ordinary"},
    )
    with pytest.raises(RecoveryConflictError, match="invalid frozen logical session binding"):
        orchestrator.run(1)


def test_queued_sessions_stay_pending_until_they_acquire_a_worker(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from auto_designer.experiment.runtime import progress_v2
    from auto_designer.loop.recovery import EVENT_FILE

    repo = _repo(tmp_path / "harness")
    recovery = _recovery(tmp_path / "checkpoints")
    plan = [_binding(f"p-{slot}", "ordinary", slot, round_no=1, mode="direct") for slot in range(4)]
    acquired, release = threading.Event(), threading.Event()
    lock, started = threading.Lock(), []
    store = SessionStore(tmp_path / "sessions")

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            return ScriptedHarness()

    def runner(persona, scenario, harness, *, workspace_dir=None):
        ctx = current_usage_context()
        with lock:
            started.append(ctx.session_id)
            if len(started) == 2:
                acquired.set()
        assert release.wait(timeout=10), "worker barrier was not released"
        session = Session(
            persona,
            scenario,
            Transcript(),
            FeelingScore(3, "complete"),
            session_id=ctx.session_id,
            session_provenance=bound_session_provenance(),
        )
        store.save(session)
        return session

    runner.load_completed_session = lambda sid: store.reconcile(
        sid, expected_provenance=bound_session_provenance()
    )
    orchestrator = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        max_parallel_users=2,
        recovery=recovery,
        frozen_session_plan=lambda round_no: plan,
        resolve_session=lambda binding: _resolve(binding, tmp_path),
        task_kinds={"ordinary": "ordinary"},
    )
    with ThreadPoolExecutor(max_workers=1) as supervisor:
        future = supervisor.submit(orchestrator.run, 1)
        try:
            assert acquired.wait(timeout=10), "two workers did not enter actual sessions"
            state = recovery.round_state(round_no=1)
            # Identity is fixed for all four slots, without pretending queued work started.
            assert state["plan"] == plan
            users = progress_v2(tmp_path)["rounds"]["1"]["users"]
            assert {
                name: users[name]
                for name in ("expected", "started", "running", "pending", "completed", "failed")
            } == {
                "expected": 4,
                "started": 2,
                "running": 2,
                "pending": 2,
                "completed": 0,
                "failed": 0,
            }
            events = [
                json.loads(line) for line in (recovery.root / EVENT_FILE).read_text().splitlines()
            ]
            begins = [
                event
                for event in events
                if event.get("event") == "unit_started" and event.get("stage") == "users"
            ]
            assert {event["operation_key"] for event in begins} == set(started)
            assert len(begins) == 2
        finally:
            release.set()
        assert len(future.result(timeout=10)) == 1
    users = progress_v2(tmp_path)["rounds"]["1"]["users"]
    assert users["started"] == users["completed"] == 4
    assert users["pending"] == users["running"] == users["failed"] == 0
    assert all(
        unit["attempt"] == 1
        for unit in recovery.round_state(round_no=1)["stages"]["users"]["units"].values()
    )
