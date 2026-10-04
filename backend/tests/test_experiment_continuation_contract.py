"""Spec-0079/T6: current producer→collect→prepare→bootstrap→new user boundaries.

These offline fixtures validate execution contracts with empty admission outcomes;
real model feedback and nonempty OpenAgents delivery are verified separately.
"""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.experiment import materials, workload
from auto_designer.experiment.collection import collect_archive
from auto_designer.experiment.continuation.export import export_continuation
from auto_designer.experiment.continuation.source import load_continuation_source
from auto_designer.experiment.controllers import feedback, runtime
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore, operation_key
from auto_designer.models import (
    FeelingScore,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    WorkspaceSpec,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from test_experiment_config_v2 import package, write
from test_experiment_materials import prepared_inputs as prepared_inputs

FIXTURE = Path(__file__).parent / "fixtures/continuation/current-parent-v1.json"


def git(repo, *args, input=None):
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Contract",
                "-c",
                "user.email=contract@x",
                *args,
            ],
            input=input,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )


def mark_stage(ledger, round_no, stage, input_value, dependencies):
    key = operation_key(round_no, stage, "stage-marker")
    ledger.begin_unit(
        round_no=round_no,
        stage=stage,
        key=key,
        input_value=input_value,
        dependencies=dependencies,
        expected_postconditions={"completed": True},
    )
    ledger.complete_unit(round_no=round_no, stage=stage, key=key)
    ledger.complete_stage(round_no=round_no, stage=stage)


def complete_fixture_users(manifest, repo):
    """Persist real store/recovery receipt contracts without pretending to call a model."""
    root = Path(manifest["run_dir"])
    identity = RecoveryIdentity(
        **{
            field: manifest[field]
            for field in (
                "experiment_id",
                "run_id",
                "config_hash",
                "controller_sha",
                "plan_hash",
            )
        }
    )
    ledger = RecoveryStore.initialize(root=root / "checkpoints", identity=identity)
    store = SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions")
    plan = workload.read_session_plan(root, manifest)
    sha = git(repo, "rev-parse", "main")
    invocation = {"run_id": manifest["run_id"], "rounds": []}
    tasks = workload.tasks_by_id(workload.read_task_catalog(root, manifest))
    for number, bindings in enumerate(plan["rounds"], 1):
        ledger.freeze_round(round_no=number, user_sha=sha, plan=bindings)
        mark_stage(ledger, number, "round_started", {"user_sha": sha, "plan": bindings}, ())
        for binding in bindings:
            sid = operation_key(manifest["run_id"], "users", binding, sha)
            session = Session(
                session_id=sid,
                persona=Persona(binding["persona_id"], "l", "d", "g", "s"),
                scenario=SeedScenario(
                    "Offline contract task",
                    workspace=WorkspaceSpec(
                        params={
                            "task_id": binding["task_id"],
                            "task_digest": binding["task_digest"],
                            "task_kind": tasks[binding["task_id"]]["kind"],
                            "interaction": binding["interaction"],
                        }
                    ),
                ),
                transcript=Transcript([]),
                feeling=FeelingScore(3, "Fixture; no model evaluation"),
                accept_validity="unverified_accept",
                session_provenance={
                    "contract_version": 1,
                    "run_id": manifest["run_id"],
                    "harness_sha": sha,
                    "task_kind": tasks[binding["task_id"]]["kind"],
                    **binding,
                },
            )
            store.save(session)
            ledger.begin_unit(
                round_no=number,
                stage="users",
                key=sid,
                input_value={"binding": binding, "user_sha": sha},
                dependencies=("round_started",),
                expected_postconditions={"completed": True},
            )
            ledger.save_output(round_no=number, stage="users", key=sid, output=session.to_dict())
            ledger.complete_unit(
                round_no=number,
                stage="users",
                key=sid,
                observed_postconditions={"completed": True, "session_id": sid},
            )
        ledger.complete_stage(round_no=number, stage="users")
        mark_stage(ledger, number, "round_sealed", {"user_sha": sha, "sealed_sha": sha}, ("users",))
        ledger.seal_round(round_no=number, sealed_sha=sha)
        invocation["rounds"].append({"round": number, "user_sha": sha, "sealed_sha": sha})
    write(store.root.parent / "manifest.json", invocation)
    nonce = "contract-" + manifest["run_id"]
    write(
        root / "runtime/gitea-evidence.json",
        {
            "repository": {"id": 1, "full_name": "offline/" + manifest["run_id"]},
            "issues": [],
            "comments": {},
            "terminal": True,
            "controller_nonce": nonce,
        },
    )
    exported = export_continuation(
        root=root,
        manifest=manifest,
        recovery=ledger,
        harness_repo=repo,
        sessions_root=store.root,
    )
    assert exported["status"] == "ready"
    receipt = collect_archive(
        run_dir=root,
        manifest=manifest,
        snapshot={
            "snapshot_dir": str(root),
            "terminal": True,
            "consistent": True,
            "controller": {
                "experiment_complete": True,
                "expected_rounds": len(plan["rounds"]),
                "sealed_rounds": list(range(1, len(plan["rounds"]) + 1)),
                "exit_code": 0,
                "running": False,
                "stopped_by_user": False,
                "nonce": nonce,
            },
        },
        credentials={},
    )
    assert receipt["continuation_ready"]
    source = load_continuation_source(
        archive=Path(receipt["archive"]), sha256=receipt["archive_sha256"]
    )
    return receipt, source


def seed_parent(root, fixture):
    repo = root / "data/harness_sandbox/harness_repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    for relative, record in fixture["harness_files"].items():
        data = record["text"].encode()
        path = repo / relative
        path.write_bytes(data)
        path.chmod(0o755 if record["mode"] == "100755" else 0o644)
        oid = git(repo, "hash-object", "-w", "--stdin", input=data)
        git(repo, "update-index", "--add", "--cacheinfo", record["mode"], oid, relative)
    git(repo, "commit", "-m", "contract exact parent tree")
    return repo


def seed_child(manifest, monkeypatch):
    root = Path(manifest["run_dir"])
    repo = root / "data/harness_sandbox/harness_repo"
    monkeypatch.setattr(runtime, "HARNESS_REPO", repo)
    monkeypatch.setenv(
        "AUTO_DESIGNER_HARNESS_ARCHIVE",
        str(root / manifest["materials"]["harness_archive"]["path"]),
    )
    monkeypatch.setenv(
        "AUTO_DESIGNER_CONTINUATION_INPUT",
        str(root / manifest["materials"]["continuation_input"]["path"]),
    )
    monkeypatch.delenv("AUTO_DESIGNER_OBSERVATION_ROOT", raising=False)
    runtime._seed_harness_repo()
    monkeypatch.setattr(
        feedback,
        "assemble_feedback_roles",
        lambda **k: {
            "triagers": [],
            "synthesizers": [],
            "divergents": [],
            "owner": None,
        },
    )
    receipt = feedback.run_continuation_bootstrap(
        run_root=root,
        manifest=manifest,
        tracker=FakeTracker(),
        child_store=SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions"),
        repo=repo,
        definitions_root=root / "definitions",
        roster={},
        resolve_head=lambda: git(repo, "rev-parse", "main"),
        assert_descendant=lambda **s: git(
            repo, "merge-base", "--is-ancestor", s["ancestor"], s["descendant"]
        ),
        integrity_guard=lambda: None,
        status_factory=lambda *a: None,
        event_factory=lambda *a: None,
    )
    assert receipt["no_admissions"] is True  # Explicitly not nonempty delivery verification.
    return repo, receipt


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_current_three_generations_preserve_selected_inputs_and_reach_logical_r8(
    tmp_path, prepared_inputs, monkeypatch, backend
):
    fixture = json.loads(FIXTURE.read_text())
    raw = json.loads(prepared_inputs.read_text())
    task_paths = []
    for task in fixture["tasks"]:
        package_doc = {**package(), **task}
        task_path = write(tmp_path / (task["id"] + ".json"), package_doc)
        task_paths.append(str(task_path))
    library_path = Path(__file__).resolve().parents[2] / "examples/personas/library.json"
    cards = json.loads(library_path.read_text())
    write(tmp_path / "personas.json", [c for c in cards if c["id"] in fixture["persona_ids"]])
    raw["workload"].pop("task_package")
    raw["workload"].pop("kind")
    raw["workload"].update(
        task_packages=task_paths,
        persona_ids=fixture["persona_ids"],
        interaction_plan=[
            fixture["selected_parent_pairs"] for _ in range(fixture["parent_rounds"])
        ],
    )
    raw["rounds"] = {"count": 5, "sessions_per_round": 2, "max_parallel_users": 2}
    write(prepared_inputs, raw)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    repo = seed_parent(Path(manifest["run_dir"]), fixture)
    parent_receipt, parent = complete_fixture_users(manifest, repo)
    initial_archive = Path(parent_receipt["archive"])
    parent_original = initial_archive.read_bytes()
    assert len(parent.manifest["config"]["workload"]["persona_ids"]) == 3
    assert len(parent.tasks) == len(parent.personas) == 2
    boundaries = [parent.export["boundary"]["lineage_round"]]
    original_pairs = [
        {k: v for k, v in p.items() if k not in {"round_no", "slot"}} for p in parent.pairs
    ]
    for count in fixture["append_rounds"]:
        child_config = copy.deepcopy(raw)
        child_config.update(
            harness={"source": "continuation"},
            workload={"source": "parent"},
            continuation={
                "archive": parent_receipt["archive"],
                "sha256": parent_receipt["archive_sha256"],
            },
            rounds={"count": count, "sessions_per_round": 2, "max_parallel_users": 2},
        )
        if backend == "e2b":
            child_config["runtime"].update(
                backend="e2b", e2b={"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600}
            )
            child_config["runtime"]["gitea"]["provider"] = "gitea.com"
        config_path = write(tmp_path / f"configs/child-{count}.json", child_config)
        assert materials.check_materials(config_path)["ok"]
        child = materials.prepare_materials(config_path, tmp_path / "runs")
        child_root = Path(child["run_dir"])
        frozen_plan = workload.read_session_plan(child_root, child)
        assert child["lineage"]["base_round"] == boundaries[-1]
        assert child["plan_hash"] != parent.manifest["plan_hash"]
        assert len(workload.read_task_catalog(child_root, child)["tasks"]) == 2
        for local_round, bindings in enumerate(frozen_plan["rounds"], 1):
            assert [b["round_no"] for b in bindings] == [local_round] * 2
            assert [
                {k: v for k, v in p.items() if k not in {"round_no", "slot"}} for p in bindings
            ] == original_pairs
        repo, bootstrap = seed_child(child, monkeypatch)
        assert git(repo, "rev-parse", "main^{tree}") == parent.export["harness"]["tree_id"]
        assert git(repo, "rev-parse", "main") != parent.export["harness"]["commit"]
        parent_receipt, parent = complete_fixture_users(child, repo)
        assert parent.recovery["rounds"]["1"]["user_sha"] == bootstrap["sealed_sha"]
        boundaries.append(parent.export["boundary"]["lineage_round"])
        assert not any(key.startswith("continuation:") for key in parent.export["material_keys"])
    assert boundaries == fixture["expected_lineage_rounds"]
    assert initial_archive.read_bytes() == parent_original


# Spec-0080/T3: collect -> source -> child keeps repeated slots, not repeated cards.
def test_reused_persona_and_pair_archive_roundtrip(tmp_path, prepared_inputs, monkeypatch):
    fixture = json.loads(FIXTURE.read_text())
    raw = json.loads(prepared_inputs.read_text())
    raw["rounds"] = {"count": 1, "sessions_per_round": 3, "max_parallel_users": 2}
    raw["workload"]["interaction_plan"] = [[["sr-15-swyx", "simple-task"]] * 3]
    write(prepared_inputs, raw)
    parent_manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    repo = seed_parent(Path(parent_manifest["run_dir"]), fixture)
    receipt, parent = complete_fixture_users(parent_manifest, repo)
    archive = Path(receipt["archive"])
    original = archive.read_bytes()
    assert len(parent.pairs) == 3 and len(parent.personas) == 1
    assert len(parent.export["boundary"]["sessions"]) == 3
    child_config = copy.deepcopy(raw)
    child_config.update(
        harness={"source": "continuation"},
        workload={"source": "parent"},
        continuation={"archive": str(archive), "sha256": receipt["archive_sha256"]},
        rounds={"count": 2, "sessions_per_round": 3, "max_parallel_users": 2},
    )
    path = write(tmp_path / "configs/reused-child.json", child_config)
    preview = materials.check_materials(path)
    assert preview["persona_ids"] == ["sr-15-swyx"]
    assert preview["interaction_plan"] == [[["sr-15-swyx", "simple-task"]] * 3] * 2
    child = materials.prepare_materials(path, tmp_path / "runs")
    root = Path(child["run_dir"])
    plan = workload.read_session_plan(root, child)
    assert all([b["slot"] for b in picks] == [0, 1, 2] for picks in plan["rounds"])
    cards = json.loads((root / child["materials"]["persona_library"]["path"]).read_text())
    assert len(cards) == 1
    repo, _ = seed_child(child, monkeypatch)
    _, reloaded = complete_fixture_users(child, repo)
    assert len(reloaded.pairs) == 3 and len(reloaded.personas) == 1
    assert archive.read_bytes() == original
