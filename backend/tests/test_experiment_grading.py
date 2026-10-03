"""Spec-0075/T2: pinned archived predictions, independent grading and fail-closed inputs."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from auto_designer.experiment import grading, materials, workload
from auto_designer.experiment.collection import collect_archive
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.manifest import recovery_identity, run_lock, update_runtime
from auto_designer.loop.recovery import digest_value, operation_key
from auto_designer.models import (
    FeelingScore,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    WorkspaceSpec,
)
from auto_designer.user.patches import preserve_prediction
from auto_designer.user.session_store import SessionStore
from test_experiment_config_v2 import write
from test_experiment_materials import prepared_inputs as base_prepared_inputs


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def archived_run(prepared_inputs, tmp_path):
    config = json.loads(prepared_inputs.read_text())
    config["rounds"]["count"] = 1
    config["workload"].pop("kind")
    config["workload"]["task_packages"] = [config["workload"].pop("task_package")]
    write(prepared_inputs, config)
    task = json.loads((tmp_path / "task.json").read_text())
    task.update(kind="swebench", interaction="direct")
    task.pop("not_in_benchmark")
    revision = config["source"]["openagents"]["revision"]
    task["source"] = {
        "kind": "git",
        "url": "https://example.com/task.git",
        "revision": revision,
        "repo": "owner/task",
    }
    write(tmp_path / "task.json", task)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    directory = Path(manifest["run_dir"])
    plan = workload.read_session_plan(directory, manifest)
    catalog = workload.read_task_catalog(directory, manifest)
    binding = plan["rounds"][0][0]
    session_id = operation_key(manifest["run_id"], "users", binding)
    harness_sha = "1" * 40
    provenance = {
        "contract_version": 1,
        "run_id": manifest["run_id"],
        **binding,
        "harness_sha": harness_sha,
        "task_kind": "swebench",
    }
    sessions = directory / "data/role_runs" / manifest["run_id"] / "sessions"
    patch = "diff --git a/task.py b/task.py\n" + "x" * 16000
    receipt = preserve_prediction(
        sessions_root=sessions,
        session_id=session_id,
        patch=patch,
        patch_sha256=digest(patch.encode()),
    )
    session = Session(
        persona=Persona(binding["persona_id"], "expert", "python", "fix task", "direct"),
        scenario=SeedScenario(
            "Fix task",
            WorkspaceSpec(
                params={
                    k: provenance[k] for k in ("task_id", "task_digest", "task_kind", "interaction")
                }
            ),
        ),
        transcript=Transcript(),
        feeling=FeelingScore(4, "done"),
        session_id=session_id,
        session_provenance=provenance,
        workspace_evidence={
            "prediction": receipt,
            "diff_sha256": receipt["sha256"],
            "diff_bytes": receipt["bytes"],
            "diff_base_commit": revision,
        },
        user_outcome={
            "status": "completed",
            "review_status": "completed",
            "review_verdict": "accept",
        },
    )
    SessionStore(sessions).save(session)
    data = session.to_dict()
    unit_input = {"binding": binding, "user_sha": harness_sha}
    relative = f"recovery-receipts/1/users/{session_id}.json"
    output = {
        "schema_version": 1,
        "round": 1,
        "stage": "users",
        "operation_key": session_id,
        "input_digest": digest_value(unit_input),
        "output_digest": digest_value(data),
        "output": data,
    }
    write(directory / "checkpoints" / relative, output)
    recovery = {
        "schema_version": 1,
        "identity": recovery_identity(manifest),
        "rounds": {
            "1": {
                "status": "completed",
                "user_sha": harness_sha,
                "sealed_sha": harness_sha,
                "plan": plan["rounds"][0],
                "plan_hash": digest_value(plan["rounds"][0]),
                "stages": {
                    "users": {
                        "status": "completed",
                        "units": {
                            session_id: {
                                "status": "completed",
                                "input": unit_input,
                                "input_digest": digest_value(unit_input),
                                "observed_postconditions": {
                                    "completed": True,
                                    "session_id": session_id,
                                },
                                "output_artifact": relative,
                                "output_digest": digest_value(data),
                            }
                        },
                    },
                    "round_sealed": {
                        "status": "completed",
                        "units": {
                            operation_key(1, "round_sealed", "stage-marker"): {
                                "status": "completed",
                                "input": {"user_sha": harness_sha, "sealed_sha": harness_sha},
                                "input_digest": digest_value(
                                    {"user_sha": harness_sha, "sealed_sha": harness_sha}
                                ),
                                "observed_postconditions": {"completed": True},
                            }
                        },
                    },
                },
            }
        },
    }
    write(directory / "checkpoints/recovery.json", recovery)
    controller = {
        "nonce": "unique-controller",
        "command_identity": "command-proof",
        "state": "EXITED",
        "running": False,
        "cleanup_complete": True,
        "residual_processes": 0,
    }
    write(
        directory / "runtime/controller.json",
        {"nonce": controller["nonce"], "command_identity": controller["command_identity"]},
    )
    write(directory / "runtime/controller-exit.json", controller)
    row = {
        "instance_id": task["id"],
        "repo": "owner/task",
        "base_commit": revision,
        "patch": "GOLD NEVER IN EXPERIMENT",
        "test_patch": "TEST NEVER IN EXPERIMENT",
        "version": "1.0",
        "FAIL_TO_PASS": '["test_failure"]',
        "PASS_TO_PASS": "[]",
    }
    dataset = write(tmp_path / "dataset.json", [row])
    snapshot = {
        "snapshot_dir": str(directory),
        "consistent": True,
        "terminal": True,
        "controller": controller,
    }
    collection = collect_archive(
        run_dir=directory, manifest=manifest, snapshot=snapshot, credentials={}
    )
    with run_lock(run_dir=directory):
        update_runtime(
            run_dir=directory,
            action="collected-test-boundary",
            changes={
                "experiment_state": "COMPLETED",
                "collection_state": "COMPLETE",
                "resource_state": "PROVISIONED",
                "observation": "OBSERVED",
                "provider": {"controller": controller},
                "collection": collection,
            },
        )
    return {
        "manifest": manifest,
        "directory": directory,
        "dataset": dataset,
        "dataset_sha256": digest(dataset.read_bytes()),
        "session_id": session_id,
        "binding": binding,
        "task": catalog["tasks"][0],
        "row": row,
        "controller": controller,
        "snapshot": snapshot,
        "patch": patch,
    }


def invoke(run, **kwargs):
    return grading.grade_run(
        run_id=run["manifest"]["run_id"],
        root=run["directory"].parent,
        dataset=run["dataset"],
        dataset_sha256=run["dataset_sha256"],
        **kwargs,
    )


def unchanged(directory):
    return {
        str(p.relative_to(directory)): digest(p.read_bytes())
        for p in directory.rglob("*")
        if p.is_file() and (not p.is_relative_to(directory / "evaluation"))
    }


def recollect(run):
    collection = collect_archive(
        run_dir=run["directory"],
        manifest=run["manifest"],
        snapshot=run["snapshot"],
        credentials={},
    )
    update_runtime(
        run_dir=run["directory"],
        action="recollect-test-boundary",
        changes={
            "collection_state": "COMPLETE",
            "collection": collection,
        },
    )


def update_session(run, mutate):
    directory = run["directory"]
    path = (
        directory
        / "data/role_runs"
        / run["manifest"]["run_id"]
        / "sessions"
        / f"{run['session_id']}.json"
    )
    session = json.loads(path.read_text())
    mutate(session)
    write(path, session)
    rp = directory / f"checkpoints/recovery-receipts/1/users/{run['session_id']}.json"
    receipt = json.loads(rp.read_text())
    receipt["output"] = session
    receipt["output_digest"] = digest_value(session)
    write(rp, receipt)
    recovery_path = directory / "checkpoints/recovery.json"
    recovery = json.loads(recovery_path.read_text())
    recovery["rounds"]["1"]["stages"]["users"]["units"][run["session_id"]]["output_digest"] = (
        digest_value(session)
    )
    write(recovery_path, recovery)
    recollect(run)


def test_offline_validates_complete_large_patch_without_side_effects(archived_run, monkeypatch):
    run = archived_run
    before = unchanged(run["directory"])
    monkeypatch.setattr(
        grading.SWEbenchEvaluator,
        "preflight",
        staticmethod(lambda: pytest.fail("offline preflight")),
    )
    monkeypatch.setattr(
        grading.SWEbenchEvaluator, "evaluate", lambda *a, **k: pytest.fail("offline evaluation")
    )
    result = invoke(run, offline=True)
    assert result["ok"] and result["report_dir"] is None
    assert result["entries"][0]["status"] == "ready"
    assert result["entries"][0]["prediction"]["bytes"] > 12000
    assert unchanged(run["directory"]) == before
    assert not (run["directory"] / "evaluation").exists()


@pytest.mark.parametrize("passed", [True, False])
def test_independent_attempts_preserve_original_and_official_failure_is_completed(
    archived_run, monkeypatch, passed
):
    run = archived_run
    before = unchanged(run["directory"])
    calls = []
    monkeypatch.setattr(grading.SWEbenchEvaluator, "preflight", staticmethod(lambda: None))

    def evaluate(self, *, instance_id, patch):
        calls.append((instance_id, patch, json.loads(self.dataset_path.read_text())))
        return {"status": "completed", "fresh": True, "passed": passed}

    monkeypatch.setattr(grading.SWEbenchEvaluator, "evaluate", evaluate)
    first = invoke(run)
    second = invoke(run)
    assert first["ok"] and second["ok"]
    assert first["report_dir"] != second["report_dir"]
    assert first["entries"][0]["passed"] is passed
    assert calls[0][1] == run["patch"]
    assert calls[0][2] == [run["row"]]
    assert unchanged(run["directory"]) == before
    assert "GOLD NEVER" not in json.dumps(first)


@pytest.mark.parametrize("status", ["crashed", "timed_out", "unavailable", "unknown"])
def test_evaluator_errors_are_not_completed(archived_run, monkeypatch, status):
    monkeypatch.setattr(grading.SWEbenchEvaluator, "preflight", staticmethod(lambda: None))
    monkeypatch.setattr(
        grading.SWEbenchEvaluator,
        "evaluate",
        lambda *a, **kw: {"status": status, "passed": False, "fresh": True},
    )
    result = invoke(archived_run)
    assert not result["ok"]
    assert result["entries"][0]["status"] == ("crashed" if status == "unknown" else status)


def test_preflight_unavailable_has_complete_report_without_evaluator(archived_run, monkeypatch):
    monkeypatch.setattr(
        grading.SWEbenchEvaluator, "preflight", staticmethod(lambda: "Docker unavailable")
    )
    monkeypatch.setattr(
        grading.SWEbenchEvaluator, "evaluate", lambda *a, **k: pytest.fail("unavailable evaluation")
    )
    result = invoke(archived_run)
    assert not result["ok"] and result["entries"][0]["status"] == "unavailable"
    assert (Path(result["report_dir"]) / "summary.json").is_file()


def test_missing_prediction_is_ungradable_not_empty(archived_run):
    update_session(archived_run, lambda s: s["workspace_evidence"].pop("prediction"))
    result = invoke(archived_run, offline=True)
    assert not result["ok"]
    assert result["entries"][0]["reason"] == "missing_prediction"


def test_successfully_exported_empty_patch_is_valid(archived_run):
    run = archived_run
    sid = run["session_id"]
    payload = b""
    patch_path = (
        run["directory"] / f"data/role_runs/{run['manifest']['run_id']}/predictions/{sid}.patch"
    )
    patch_path.write_bytes(payload)

    def mutation(s):
        s["workspace_evidence"].update(diff_sha256=digest(payload), diff_bytes=0)
        s["workspace_evidence"]["prediction"].update(sha256=digest(payload), bytes=0)

    update_session(run, mutation)
    assert invoke(run, offline=True)["ok"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("repo", "wrong/repo"),
        ("base_commit", "2" * 40),
        ("instance_id", "other-task"),
        ("test_patch", None),
        ("FAIL_TO_PASS", "not JSON"),
    ],
)
def test_dataset_mismatch_fails_before_attempt_or_evaluator(archived_run, field, value):
    run = archived_run
    row = {**run["row"], field: value}
    write(run["dataset"], [row])
    run["dataset_sha256"] = digest(run["dataset"].read_bytes())
    with pytest.raises(ConfigError):
        invoke(run, offline=True)
    assert not (run["directory"] / "evaluation").exists()


def test_duplicate_instance_dataset_is_rejected(archived_run):
    run = archived_run
    write(run["dataset"], [run["row"], run["row"]])
    run["dataset_sha256"] = digest(run["dataset"].read_bytes())
    with pytest.raises(ConfigError, match="uniquely"):
        invoke(run, offline=True)


def test_dataset_hash_must_match_exact_bytes(archived_run):
    archived_run["dataset"].write_text("[]")
    with pytest.raises(ConfigError, match="SHA-256"):
        invoke(archived_run, offline=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_digest", "wrong"),
        ("harness_sha", "2" * 40),
        ("round_no", True),
        ("slot", 1),
        ("persona_id", "other"),
        ("run_id", "other"),
    ],
)
def test_session_binding_mismatch_is_rejected(archived_run, field, value):
    update_session(archived_run, lambda s: s["session_provenance"].update({field: value}))
    with pytest.raises(ConfigError):
        invoke(archived_run, offline=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../outside.patch"),
        ("session_id", "other"),
        ("bytes", True),
        ("sha256", "0" * 64),
        ("contract_version", True),
    ],
)
def test_prediction_receipt_mismatch_is_rejected(archived_run, field, value):
    update_session(
        archived_run, lambda s: s["workspace_evidence"]["prediction"].update({field: value})
    )
    with pytest.raises(ConfigError):
        invoke(archived_run, offline=True)


@pytest.mark.parametrize(
    "mutation", ["nonce", "running", "partial", "unsealed", "identity", "unit"]
)
def test_terminal_recovery_and_collection_mismatch_fail_closed(archived_run, mutation):
    run = archived_run
    if mutation in {"nonce", "running"}:
        run["snapshot"]["controller"] = (
            {**run["controller"], "nonce": "wrong"}
            if mutation == "nonce"
            else {**run["controller"], "running": True}
        )
    elif mutation == "partial":
        run["snapshot"]["terminal"] = False
    else:
        path = run["directory"] / "checkpoints/recovery.json"
        state = json.loads(path.read_text())
        if mutation == "unsealed":
            state["rounds"]["1"]["status"] = "running"
        elif mutation == "identity":
            state["identity"]["plan_hash"] = "wrong"
        else:
            state["rounds"]["1"]["stages"]["users"]["units"][run["session_id"]]["status"] = "failed"
        write(path, state)
    recollect(run)
    with pytest.raises(ConfigError):
        invoke(run, offline=True)


def test_cloud_wrapper_uses_same_authoritative_archive_path(archived_run):
    run = archived_run
    run["snapshot"]["controller"] = {
        "controller": run["controller"],
        "sandbox_id": "boundary-sandbox",
    }
    recollect(run)
    assert invoke(run, offline=True)["ok"]


def test_archive_hash_and_inventory_reject_tamper(archived_run):
    run = archived_run
    path = run["directory"] / "archive/artifacts.tar.gz"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ConfigError, match="SHA-256"):
        invoke(run, offline=True)


@pytest.mark.parametrize("member_type", ["duplicate", "traversal", "symlink", "hardlink"])
def test_archive_rejects_unsafe_member_even_with_updated_outer_hash(archived_run, member_type):
    run = archived_run
    path = run["directory"] / "archive/artifacts.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(path) as source, tarfile.open(fileobj=buffer, mode="w:gz") as target:
        for member in source:
            target.addfile(member, source.extractfile(member))
        info = tarfile.TarInfo(
            "manifest.json"
            if member_type == "duplicate"
            else "../escape"
            if member_type == "traversal"
            else "link"
        )
        if member_type == "symlink":
            info.type = tarfile.SYMTYPE
            info.linkname = "manifest.json"
        elif member_type == "hardlink":
            info.type = tarfile.LNKTYPE
            info.linkname = "manifest.json"
        target.addfile(info, io.BytesIO())
    path.write_bytes(buffer.getvalue())
    rp = run["directory"] / "archive/collection.json"
    receipt = json.loads(rp.read_text())
    receipt["archive_sha256"] = digest(path.read_bytes())
    write(rp, receipt)
    update_runtime(
        run_dir=run["directory"],
        action="forged-collection-boundary",
        changes={"collection": receipt},
    )
    with pytest.raises(ConfigError, match="Unsafe or duplicate"):
        invoke(run, offline=True)


def test_internal_receipt_disagreement_is_rejected(archived_run):
    path = archived_run["directory"] / "archive/collection.json"
    receipt = json.loads(path.read_text())
    receipt["collected_at"] = "tampered"
    write(path, receipt)
    with pytest.raises(ConfigError, match="Internal and external"):
        invoke(archived_run, offline=True)


def test_archive_is_authoritative_over_live_session(archived_run):
    run = archived_run
    path = (
        run["directory"]
        / f"data/role_runs/{run['manifest']['run_id']}/sessions/{run['session_id']}.json"
    )
    path.write_text("{}")
    assert invoke(run, offline=True)["ok"]


def test_frozen_symlink_ancestor_rejected(archived_run):
    run = archived_run
    materials_dir = run["directory"] / "materials"
    actual = run["directory"] / "material-copy"
    materials_dir.rename(actual)
    materials_dir.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ConfigError, match="symlink"):
        invoke(run, offline=True)


def test_invalid_session_is_not_upgraded_by_valid_prediction(archived_run):

    def mutate(s):
        s["user_outcome"]["status"] = "infrastructure_failure"

    update_session(archived_run, mutate)
    result = invoke(archived_run, offline=True)
    assert (
        not result["ok"] and result["entries"][0]["reason"] == "invalid_or_infrastructure_session"
    )


@pytest.mark.parametrize("round_no", [0, 2, True])
def test_invalid_selected_round_rejected(archived_run, round_no):
    with pytest.raises(ConfigError, match="round"):
        invoke(archived_run, round_no=round_no, offline=True)


def test_missing_prediction_baseline_is_ungradable(archived_run):
    update_session(archived_run, lambda s: s["workspace_evidence"].pop("diff_base_commit"))
    result = invoke(archived_run, offline=True)
    assert not result["ok"] and result["entries"][0]["reason"] == "missing_prediction_base"


def test_wrong_prediction_baseline_is_rejected(archived_run):
    update_session(
        archived_run, lambda s: s["workspace_evidence"].update(diff_base_commit="2" * 40)
    )
    with pytest.raises(ConfigError, match="baseline"):
        invoke(archived_run, offline=True)


def test_failed_direct_review_is_ungradable(archived_run):
    update_session(
        archived_run, lambda s: s["user_outcome"].update(review_status="infrastructure_failure")
    )
    result = invoke(archived_run, offline=True)
    assert (
        not result["ok"] and result["entries"][0]["reason"] == "invalid_or_infrastructure_session"
    )


def test_round_seal_marker_cannot_be_replaced_by_status_only(archived_run):
    run = archived_run
    path = run["directory"] / "checkpoints/recovery.json"
    recovery = json.loads(path.read_text())
    recovery["rounds"]["1"]["stages"]["round_sealed"]["units"] = {}
    write(path, recovery)
    recollect(run)
    with pytest.raises(ConfigError, match="round seal unit"):
        invoke(run, offline=True)


def test_jsonl_dataset_uses_same_strict_binding(archived_run):
    run = archived_run
    dataset = run["dataset"].with_suffix(".jsonl")
    dataset.write_text(json.dumps(run["row"]) + "\n")
    run["dataset"] = dataset
    run["dataset_sha256"] = digest(dataset.read_bytes())
    assert invoke(run, offline=True)["ok"]


def test_official_empty_prediction_is_explicitly_not_fully_graded(archived_run, monkeypatch):
    monkeypatch.setattr(grading.SWEbenchEvaluator, "preflight", staticmethod(lambda: None))
    monkeypatch.setattr(
        grading.SWEbenchEvaluator,
        "evaluate",
        lambda *a, **k: {
            "status": "not_evaluated",
            "passed": None,
            "fresh": False,
            "reason": "official_empty_prediction",
        },
    )
    result = invoke(archived_run)
    assert not result["ok"] and result["entries"][0]["status"] == "not_evaluated"
    assert result["summary"]["failed"] == 0


def test_dataset_symlink_is_rejected_without_writes(archived_run):
    run = archived_run
    target = run["dataset"].with_name("linked-dataset.json")
    target.symlink_to(run["dataset"])
    run["dataset"] = target
    with pytest.raises(ConfigError, match="symlink"):
        invoke(run, offline=True)


def test_existing_evaluation_symlink_is_rejected(archived_run, tmp_path):
    (archived_run["directory"] / "evaluation").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ConfigError, match="Unsafe evaluation"):
        invoke(archived_run)


def test_recovery_output_cannot_hide_a_different_prediction(archived_run):
    run = archived_run
    path = run["directory"] / f"checkpoints/recovery-receipts/1/users/{run['session_id']}.json"
    receipt = json.loads(path.read_text())
    receipt["output"]["workspace_evidence"]["prediction"]["sha256"] = "0" * 64
    receipt["output_digest"] = digest_value(receipt["output"])
    write(path, receipt)
    path = run["directory"] / "checkpoints/recovery.json"
    recovery = json.loads(path.read_text())
    recovery["rounds"]["1"]["stages"]["users"]["units"][run["session_id"]]["output_digest"] = (
        receipt["output_digest"]
    )
    write(path, recovery)
    recollect(run)
    with pytest.raises(ConfigError, match="immutable recovery output"):
        invoke(run, offline=True)


def test_canonical_round_plan_rejects_boolean_integer_alias(archived_run):
    run = archived_run
    path = run["directory"] / "checkpoints/recovery.json"
    recovery = json.loads(path.read_text())
    recovery["rounds"]["1"]["plan"][0]["round_no"] = True
    write(path, recovery)
    recollect(run)
    with pytest.raises(ConfigError, match="sealed/bound"):
        invoke(run, offline=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"experiment_state": "RUNNING"},
        {"experiment_state": "STOPPING"},
        {"observation": "UNKNOWN"},
        {"collection_state": "PARTIAL"},
        {"resource_state": "PROVISIONING"},
    ],
)
def test_retained_complete_archive_cannot_override_current_active_or_unknown_runtime(
    archived_run, changes
):
    run = archived_run
    update_runtime(run_dir=run["directory"], action="new-generation", changes=changes)
    before = unchanged(run["directory"])
    for offline in (True, False):
        with pytest.raises(ConfigError, match="current terminal runtime"):
            invoke(run, offline=offline)
    assert unchanged(run["directory"]) == before
    assert not (run["directory"] / "evaluation").exists()


@pytest.mark.parametrize("location", ["engine", "provider", "launch_receipt"])
def test_known_latest_nonce_must_match_retained_archive(archived_run, location):
    run = archived_run
    if location == "engine":
        write(
            run["directory"] / "runtime/controller.json",
            {"nonce": "new-nonce", "command_identity": "command-proof"},
        )
    else:
        controller = {**run["controller"], "nonce": "new-nonce"}
        update_runtime(
            run_dir=run["directory"],
            action="new-generation",
            changes={location: {"controller": controller}},
        )
    with pytest.raises(ConfigError, match="Current controller nonce"):
        invoke(run, offline=True)


def test_destroyed_compute_can_still_grade_matching_complete_terminal_run(archived_run):
    run = archived_run
    update_runtime(
        run_dir=run["directory"],
        action="destroy-test-boundary",
        changes={"resource_state": "DESTROYED"},
    )
    assert invoke(run, offline=True)["ok"]


def test_host_operation_lock_is_nonblocking_and_read_only(archived_run):
    run = archived_run
    before = unchanged(run["directory"])
    with run_lock(run_dir=run["directory"]):
        with pytest.raises(ConfigError, match="operation in progress"):
            invoke(run, offline=True)
    assert unchanged(run["directory"]) == before


@pytest.mark.parametrize("stage", ["preflight", "evaluate"])
def test_resume_during_evaluation_leaves_partial_attempt_without_summary(
    archived_run, monkeypatch, stage
):
    run = archived_run

    def resume():
        with run_lock(run_dir=run["directory"]):
            update_runtime(
                run_dir=run["directory"],
                action="resume-test-boundary",
                changes={
                    "collection_state": "PARTIAL",
                    "experiment_state": "RUNNING",
                    "launch_receipt": {
                        "nonce": "next-generation",
                        "state": "RUNNING",
                        "running": True,
                    },
                },
            )

    def preflight():
        if stage == "preflight":
            resume()
        return None

    def evaluate(self, **kwargs):
        assert stage == "evaluate"
        resume()
        return {"status": "completed", "passed": True, "fresh": True}

    monkeypatch.setattr(grading.SWEbenchEvaluator, "preflight", staticmethod(preflight))
    monkeypatch.setattr(grading.SWEbenchEvaluator, "evaluate", evaluate)
    with pytest.raises(ConfigError, match="current terminal runtime"):
        invoke(run)
    attempts = list((run["directory"] / "evaluation").glob("grade-*"))
    assert len(attempts) == 1 and (attempts[0] / "intent.json").is_file()
    assert not (attempts[0] / "summary.json").exists()
    assert bool(list(attempts[0].rglob("result.json"))) is (stage == "evaluate")


@pytest.mark.parametrize("mutation", ["remove", "evaluation_status", "interaction_status"])
def test_original_invalid_trace_cannot_be_removed_or_flipped_to_valid(archived_run, mutation):
    run = archived_run
    trace = {
        "persona_id": run["binding"]["persona_id"],
        "end_reason": "accepted",
        "turns": [],
        "signals": [],
        "evaluation_status": "invalid",
        "interaction_status": "protocol_unrecoverable",
    }
    update_session(run, lambda session: session.update(sim_trace=trace))
    path = (
        run["directory"]
        / f"data/role_runs/{run['manifest']['run_id']}/sessions/{run['session_id']}.json"
    )
    session = json.loads(path.read_text())
    if mutation == "remove":
        session.pop("sim_trace")
    else:
        session["sim_trace"][mutation] = "valid" if mutation == "evaluation_status" else "completed"
    write(path, session)
    recollect(run)
    with pytest.raises(ConfigError, match="trace"):
        invoke(run, offline=True)


def test_trace_default_omissions_normalize_like_real_dataclass_receipt(archived_run):
    run = archived_run
    trace = {
        "persona_id": run["binding"]["persona_id"],
        "end_reason": "accepted",
        "turns": [],
        "signals": [],
        "evaluation_status": "valid",
        "interaction_status": "completed",
    }
    update_session(run, lambda session: session.update(sim_trace=trace))
    path = (
        run["directory"]
        / f"data/role_runs/{run['manifest']['run_id']}/sessions/{run['session_id']}.json"
    )
    session = json.loads(path.read_text())
    session["sim_trace"].pop("evaluation_status")
    session["sim_trace"].pop("interaction_status")
    write(path, session)
    recollect(run)
    assert invoke(run, offline=True)["ok"]
