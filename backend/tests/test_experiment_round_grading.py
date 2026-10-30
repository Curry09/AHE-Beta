"""Same original session on post-run and sealed online paths (Spec-0084/T5)."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from auto_designer.evaluation.results import ExecutionEvidence, GradingResult
from auto_designer.evaluation.service import implementation_digest
from auto_designer.execution_contract import (
    canonical_bytes,
    canonical_sha256,
    make_execution_contract,
)
from auto_designer.experiment.assessment_worker import grade_bundle
from auto_designer.experiment.grading_inputs import load_grading_plan
from auto_designer.loop.recovery import digest_value
from auto_designer.loop.round_assessment import _bundle, read_json, write_json
from auto_designer.user.session_store import SessionStore
from test_experiment_grading import archived_run, grading_plan, prepared_inputs  # noqa: F401


@pytest.fixture
def sealed(archived_run):  # noqa: F811
    run = archived_run
    root = run["directory"]
    store = SessionStore(root / "data/role_runs" / run["manifest"]["run_id"] / "sessions")
    session = store.load(run["session_id"])
    session.execution_contract = make_execution_contract(
        session_id=session.session_id,
        task_id=run["task"]["id"],
        task_digest=run["task"]["digest"],
        followup_input="unavailable",
        task_budget_seconds=7200,
        budget_source="task_metadata",
    )
    # Build the new-source fixture before sealing it; production never rewrites an old Session.
    write_json(store.root / f"{session.session_id}.json", session.to_dict())
    state = read_json(root / "checkpoints/recovery.json")["rounds"]["1"]
    unit = state["stages"]["users"]["units"][session.session_id]
    output = read_json(root / "checkpoints" / unit["output_artifact"])
    output.update(output=session.to_dict(), output_digest=digest_value(session.to_dict()))
    unit["output_digest"] = output["output_digest"]
    write_json(root / "checkpoints" / unit["output_artifact"], output)
    durable_state = read_json(root / "checkpoints/recovery.json")
    durable_state["rounds"]["1"] = state
    write_json(root / "checkpoints/recovery.json", durable_state)
    recovery = SimpleNamespace(root=root / "checkpoints", round_state=lambda **kw: state)
    bundle = _bundle(root, run["manifest"], recovery, 1, run["binding"], store)
    bundle["task"] = run["task"]
    payload = canonical_bytes(bundle)
    plan = load_grading_plan(grading_plan(run))
    identity = {
        "run_id": run["manifest"]["run_id"],
        "session_id": session.session_id,
        "user_sha": state["user_sha"],
        "round_no": 1,
        "slot": run["binding"]["slot"],
        "task_digest": run["task"]["digest"],
        "artifact_digest": hashlib.sha256(payload).hexdigest(),
        "plan_digest": plan.digest,
        "adapter": "swebench",
        "adapter_version": 1,
        "timeout_seconds": plan.document["graders"][0]["timeout_seconds"],
        "generation": "g",
        "implementation_sha256": implementation_digest(),
    }
    request = {
        "schema_version": 1,
        "identity": identity,
        "contract_id": session.execution_contract["contract_id"],
    }
    request["request_digest"] = canonical_sha256(request)
    return run, payload, request, plan


@pytest.mark.parametrize("passed", [True, False])
def test_sealed_session_uses_common_verified_result_service(sealed, monkeypatch, tmp_path, passed):
    from auto_designer.evaluation import service

    run, payload, request, plan = sealed
    calls = []

    class Adapter:
        def validate_inputs(self, request):
            assert request.patch == run["patch"]
            assert request.session["session_id"] == run["session_id"]

        def evaluate(self, request, directory):
            calls.append(request)
            return GradingResult(
                "swebench",
                1,
                "completed",
                passed=passed,
                execution=ExecutionEvidence("fresh_official_instance", True, "sha256:" + "e" * 64),
            )

    monkeypatch.setattr(service, "get_adapter", lambda *args: Adapter())
    outcome = grade_bundle(
        payload=payload, request=request, plan=plan, attempt_dir=tmp_path / "private"
    )
    assert outcome["status"] == "completed" and outcome["passed"] is passed and len(calls) == 1


def test_changed_sealed_bytes_fail_before_any_evaluator(sealed, tmp_path):
    from auto_designer.experiment.config import ConfigError

    _, payload, request, plan = sealed
    with pytest.raises(ConfigError, match="digest"):
        grade_bundle(
            payload=payload + b" ", request=request, plan=plan, attempt_dir=tmp_path / "private"
        )
    assert not (tmp_path / "private").exists()


def test_changed_user_sha_or_task_identity_cannot_be_resigned_as_same_source(sealed, tmp_path):
    from auto_designer.experiment.config import ConfigError

    _, payload, request, plan = sealed
    request["identity"]["user_sha"] = "f" * 40
    with pytest.raises(ConfigError, match="provenance"):
        grade_bundle(payload=payload, request=request, plan=plan, attempt_dir=tmp_path / "private")


@pytest.mark.parametrize(
    "archived_run",
    [
        {
            "schema_version": 2,
            "kind": "ordinary",
            "artifacts": {
                "version": 1,
                "exports": [
                    {
                        "id": "output",
                        "source": "workspace",
                        "path": "output.bin",
                        "content_type": "application/octet-stream",
                        "required": True,
                        "max_bytes": 1024,
                    }
                ],
            },
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "expected,passed", [("original submission", True), ("different value", False)]
)
def test_live_docker_sealed_actor_artifact(sealed, tmp_path, expected, passed):
    """Opt-in real verifier containers, without models or new experiment provisioning."""
    import json
    import os
    import subprocess

    from auto_designer.experiment.grading_inputs import load_grading_plan

    if os.environ.get("RUN_SPEC_0084_DOCKER") != "1":
        pytest.skip("set RUN_SPEC_0084_DOCKER=1 for real Docker grading")
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", "python:3.13-slim-bookworm"],
        text=True,
        timeout=30,
    ).strip()
    _, payload, request, _ = sealed
    script = tmp_path / "verifier.py"
    script.write_text(
        "import json,pathlib\nvalue=pathlib.Path('/inputs/output').read_text()\npathlib.Path('/logs/verifier/result.json').write_text(json.dumps({'passed': value == "
        + repr(expected)
        + ", 'private_assertion': 'HIDDEN-ONLY'}))\n"
    )
    plan_file = tmp_path / "online-plan.json"
    document = {
        "schema_version": 1,
        "materials": {
            "script": {
                "path": str(script),
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        },
        "graders": [
            {
                "adapter": "custom",
                "contract_version": 1,
                "task_ids": [json.loads(payload)["task"]["id"]],
                "inputs": {"script": "script"},
                "timeout_seconds": 60,
                "config": {
                    "image": image,
                    "argv": ["python", "/grader/script.py"],
                    "artifact_map": {"output": "/inputs/output"},
                },
            }
        ],
    }
    plan_file.write_text(json.dumps(document))
    plan = load_grading_plan(plan_file)
    request["identity"].update(adapter="custom", timeout_seconds=60, plan_digest=plan.digest)
    result = grade_bundle(
        payload=payload, request=request, plan=plan, attempt_dir=tmp_path / "private-live"
    )
    assert result["status"] == "completed", result
    assert result["passed"] is passed
    assert result["execution"]["verified"] is True
    from auto_designer.experiment.assessment_worker import safe_summary

    public = safe_summary(result=result, request=request)
    assert "HIDDEN-ONLY" not in str(public)


@pytest.fixture
def assessed_round(sealed):
    """A real ledger with an already signed measurement, before round projection."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from auto_designer.experiment.assessment_worker import safe_summary, sign
    from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
    from auto_designer.loop.round_assessment import RoundAssessment, exchange

    run, _, request, plan = sealed
    root = run["directory"]
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    manifest = run["manifest"]
    manifest["config"]["evaluation"] = {
        "session_grading": {
            "plan_sha256": plan.digest,
            "worker_key_sha256": hashlib.sha256(raw).hexdigest(),
            "runner": "external",
        }
    }
    manifest["assessment_registration"] = {
        "worker_public_key": base64.b64encode(raw).decode(),
        "implementation_sha256": implementation_digest(),
        "selections": {
            run["task"]["id"]: {
                "adapter": "swebench",
                "contract_version": 1,
                "timeout_seconds": request["identity"]["timeout_seconds"],
            }
        },
    }
    write_json(root / "manifest.json", manifest)
    write_json(root / "runtime/controller.json", {"nonce": "g"})
    write_json(root / "assessment/requests" / request["request_digest"] / "request.json", request)
    claimed = exchange(
        root, "claim", {"request_digest": request["request_digest"], "worker_nonce": "d" * 32}
    )["claim"]
    result = {"status": "completed", "passed": False, "raw_report": {"private": "assertion"}}
    summary = safe_summary(result=result, request=request)
    envelope = sign(
        key,
        {
            "kind": "assessment_result",
            "run_id": manifest["run_id"],
            "plan_digest": plan.digest,
            **{
                key: claimed[key]
                for key in ("request_digest", "generation", "claim_epoch", "worker_nonce")
            },
            "safe_summary": summary,
            "safe_summary_digest": canonical_sha256(summary),
            "private_result_digest": canonical_sha256(result),
        },
    )
    exchange(root, "submit", {"request_digest": request["request_digest"], "envelope": envelope})
    state_path = root / "checkpoints/recovery.json"
    state = read_json(state_path)
    state["revision"] = 0
    state["rounds"]["1"]["status"] = "running"
    state["rounds"]["1"]["stages"].pop("round_sealed", None)
    write_json(state_path, state)
    identity = RecoveryIdentity(**state["identity"])
    recovery = RecoveryStore.open(root=root / "checkpoints", identity=identity)
    store = SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions")
    assessor = RoundAssessment(root, manifest, store, poll_seconds=0)
    arguments = dict(
        round_no=1, user_sha=request["identity"]["user_sha"], bindings=[run["binding"]]
    )
    return run, assessor, recovery, identity, arguments, summary


@pytest.mark.parametrize(
    "crash_after", ["projection", "save_output", "complete_unit", "complete_stage"]
)
def test_round_projection_recovery_keeps_sealed_source_and_does_not_regrade(
    assessed_round, monkeypatch, crash_after
):
    from auto_designer.loop import round_assessment
    from auto_designer.loop.recovery import RecoveryStore

    run, assessor, recovery, identity, arguments, summary = assessed_round
    root = run["directory"]
    session_path = assessor.store.root / f"{run['session_id']}.json"
    original_session = session_path.read_bytes()
    projection = root / "assessment/feedback/round-1.json"
    write_json(
        root / "assessment/status.json",
        {"phase": "objective_grading", "assessment_state": "PENDING"},
    )
    monkeypatch.setattr(
        assessor, "await_worker", lambda: pytest.fail("retained receipt needs no worker")
    )

    class Crash(RuntimeError):
        pass

    with monkeypatch.context() as crash:
        if crash_after == "projection":
            original = round_assessment.write_json

            def write_then_crash(path, value):
                original(path, value)
                if path == projection:
                    raise Crash("projection written")

            crash.setattr(round_assessment, "write_json", write_then_crash)
        else:
            original = getattr(recovery, crash_after)

            def complete_then_crash(**kwargs):
                original(**kwargs)
                raise Crash("ledger boundary written")

            crash.setattr(recovery, crash_after, complete_then_crash)
        with pytest.raises(Crash):
            assessor(recovery=recovery, **arguments)

    frozen = projection.read_bytes()
    write_json(root / "runtime/controller.json", {"nonce": "new-generation"})
    resumed = RecoveryStore.open(root=recovery.root, identity=identity)
    assessor(recovery=resumed, **arguments)
    assert resumed.stage_status(round_no=1, stage="objective_grading") == "completed"
    assert projection.read_bytes() == frozen and session_path.read_bytes() == original_session
    assert read_json(projection)["summaries"] == [summary]
    assert summary["passed"] is False  # Genuine failure still advances the measurement stage.
    assert read_json(root / "assessment/status.json")["assessment_state"] == "COMPLETE"
    assert len(list((root / "assessment/requests").glob("*/request.json"))) == 1


def test_not_configured_writes_unknown_assessment_without_reviewer_substitution(
    assessed_round, monkeypatch
):
    from auto_designer.loop.round_assessment import RoundAssessment

    run, assessor, recovery, _, arguments, _ = assessed_round
    manifest = {
        **run["manifest"],
        "config": {**run["manifest"]["config"], "evaluation": {"official_grading": False}},
    }
    assessor = RoundAssessment(run["directory"], manifest, assessor.store)
    monkeypatch.setattr(
        assessor, "await_worker", lambda: pytest.fail("unconfigured needs no worker")
    )
    before = (assessor.store.root / f"{run['session_id']}.json").read_bytes()
    assessor(recovery=recovery, **arguments)
    projection = read_json(run["directory"] / "assessment/feedback/round-1.json")
    row = projection["summaries"][0]
    assert (row["status"], row["passed"], row["score"]) == ("not_configured", None, None)
    assert recovery.stage_status(round_no=1, stage="objective_grading") == "completed"
    assert (assessor.store.root / f"{run['session_id']}.json").read_bytes() == before


def test_worker_unavailable_keeps_pending_and_never_invents_failed_score(
    assessed_round, monkeypatch
):
    from auto_designer.loop import round_assessment

    run, assessor, recovery, _, arguments, _ = assessed_round
    for path in (run["directory"] / "assessment/completed").glob("*.json"):
        path.unlink()
    # The result has not been durably accepted in this independent failure scenario.
    for path in (run["directory"] / "assessment/requests").glob("*/accepted.json"):
        path.unlink()

    class Pending(RuntimeError):
        pass

    def stop_wait(seconds):
        raise Pending("bounded test observation of a pending worker")

    monkeypatch.setattr(round_assessment.time, "sleep", stop_wait)
    with pytest.raises(Pending):
        assessor(recovery=recovery, **arguments)
    assert read_json(run["directory"] / "assessment/status.json")["assessment_state"] == "PENDING"
    assert not (run["directory"] / "assessment/feedback/round-1.json").exists()
    assert recovery.stage_status(round_no=1, stage="objective_grading") != "completed"


def test_final_trial_round_runs_assessment_before_seal_and_not_delivery(
    assessed_round, monkeypatch
):
    from auto_designer.loop.orchestrator import Orchestrator

    run, assessor, recovery, _, arguments, _ = assessed_round
    events = []
    orch = object.__new__(Orchestrator)
    orch._recovery = recovery
    orch._initial_ref = "main"
    orch._frozen_session_plan = lambda number: [run["binding"]]
    orch._task_kinds = {run["task"]["id"]: run["task"]["kind"]}
    orch._assert_commit_available = lambda sha: None
    orch._mark_recovery_stage = lambda **kw: None
    # The fixture's actor stage is already complete; this test must reuse it.
    orch._run_recovery_users = lambda **kw: events.append("retained actor")
    orch._round_assessment = lambda **kw: (assessor(**kw), events.append("assessment"))
    orch._on_round_start = None
    orch._on_round_end = None

    def seal(**kw):
        assert recovery.stage_status(round_no=1, stage="objective_grading") == "completed"
        assert kw["dependencies"] == ("objective_grading",)
        events.append("seal")
        return kw["user_sha"]

    orch._feedback_pipeline = SimpleNamespace(
        seal=seal, run=lambda **kw: pytest.fail("last round cannot deliver")
    )
    monkeypatch.setattr(assessor, "await_worker", lambda: pytest.fail("no regrading"))
    assert orch.run(1) == [arguments["user_sha"]]
    assert events == ["retained actor", "assessment", "seal"]


def test_controller_poll_recovers_worker_crash_after_durable_result(assessed_round, monkeypatch):
    """No second worker RPC is required to repair a completed measurement."""
    from auto_designer.loop import round_assessment

    run, assessor, recovery, _, arguments, summary = assessed_round
    root = run["directory"]
    request_path = next((root / "assessment/requests").glob("*/request.json"))
    request = read_json(request_path)
    accepted = request_path.parent / "accepted.json"
    envelope = read_json(accepted)
    accepted.unlink()
    next((root / "assessment/completed").glob("*.json")).unlink()
    calls = []
    monkeypatch.setattr(assessor, "await_worker", lambda: calls.append("ready"))

    def worker_submits_then_crashes(seconds):
        assert calls == ["ready"]
        calls.append("submit")
        original = round_assessment.write_json

        def write_then_crash(path, value):
            original(path, value)
            if path.parent.name == "completed":
                raise RuntimeError("worker disconnected after commit")

        with monkeypatch.context() as crash:
            crash.setattr(round_assessment, "write_json", write_then_crash)
            with pytest.raises(RuntimeError, match="disconnected"):
                round_assessment.exchange(
                    root,
                    "submit",
                    {
                        "request_digest": request["request_digest"],
                        "envelope": envelope,
                    },
                )
        assert not accepted.exists()

    monkeypatch.setattr(round_assessment.time, "sleep", worker_submits_then_crashes)
    assessor(recovery=recovery, **arguments)
    assert calls == ["ready", "submit"]
    assert read_json(accepted) == envelope
    assert read_json(root / "assessment/feedback/round-1.json")["summaries"] == [summary]
    assert recovery.stage_status(round_no=1, stage="objective_grading") == "completed"
