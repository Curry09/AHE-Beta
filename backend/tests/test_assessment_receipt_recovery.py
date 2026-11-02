"""Crashes between the durable measurement and acceptance projection (Spec-0084/T5)."""

import time
from types import SimpleNamespace

import pytest

from ahe_beta.experiment.assessment_worker import sign
from ahe_beta.experiment.config import ConfigError
from ahe_beta.loop import round_assessment as module
from test_experiment_assessment_worker import claim, queue, result  # noqa: F401


class SubmitCrash(RuntimeError):
    pass


def interrupt_submit(queue, monkeypatch):  # noqa: F811
    root, _, request, directory = queue
    payload = result(queue, claim(queue), False)
    original = module.write_json

    def write_then_crash(path, value):
        original(path, value)
        if path.parent.name == "completed":
            raise SubmitCrash("durable result written, acceptance not written")

    with monkeypatch.context() as patch:
        patch.setattr(module, "write_json", write_then_crash)
        with pytest.raises(SubmitCrash):
            module.exchange(root, "submit", payload)
    assert not (directory / "accepted.json").exists()
    completed = root / "assessment/completed" / (module.stable_request_id(request) + ".json")
    return payload, completed


@pytest.mark.parametrize("operation", ["state", "claim", "submit"])
@pytest.mark.parametrize("expired", [False, True])
def test_durable_result_repairs_acceptance_without_regrading(
    queue,  # noqa: F811
    monkeypatch,
    operation,
    expired,
):
    root, _, request, directory = queue
    payload, completed = interrupt_submit(queue, monkeypatch)
    committed = completed.read_bytes()
    if expired:
        module.write_json(
            directory / "claim.json",
            {
                **module.read_json(directory / "claim.json"),
                "lease_until": 0,
            },
        )
    prior_claim = (directory / "claim.json").read_bytes()
    argument = {
        "state": {},
        "claim": {"request_digest": request["request_digest"], "worker_nonce": "e" * 32},
        "submit": payload,
    }[operation]
    answer = module.exchange(root, operation, argument)
    if operation == "state":
        assert answer["pending"] == []
    elif operation == "claim":
        assert answer["state"] == "accepted"
    else:
        assert answer == {"accepted": True, "duplicate": True}
    assert module.read_json(directory / "accepted.json") == payload["envelope"]
    assert completed.read_bytes() == committed
    assert (directory / "claim.json").read_bytes() == prior_claim
    assert module.exchange(root, "state", {})["pending"] == []


def test_crashed_commit_cannot_be_replaced_by_conflicting_retry(queue, monkeypatch):  # noqa: F811
    root, _, _, directory = queue
    payload, completed = interrupt_submit(queue, monkeypatch)
    committed = completed.read_bytes()
    conflict = result(queue, module.read_json(directory / "claim.json"), True)
    with pytest.raises(ConfigError, match="Conflicting"):
        module.exchange(root, "submit", conflict)
    assert module.read_json(directory / "accepted.json") == payload["envelope"]
    assert completed.read_bytes() == committed


@pytest.mark.parametrize("changed", ["signature", "generation", "epoch", "nonce", "claim_request"])
def test_acceptance_repair_revalidates_signature_generation_and_claim(queue, monkeypatch, changed):  # noqa: F811
    root, key, _, directory = queue
    _, completed = interrupt_submit(queue, monkeypatch)
    record = module.read_json(completed)
    if changed == "signature":
        record["envelope"]["signature"] = "AA=="
    elif changed == "generation":
        record["envelope"]["body"]["generation"] = "other-generation"
        record["envelope"] = sign(key, record["envelope"]["body"])
    else:
        claimed = module.read_json(directory / "claim.json")
        key_name, value = {
            "epoch": ("claim_epoch", claimed["claim_epoch"] + 1),
            "nonce": ("worker_nonce", "e" * 32),
            "claim_request": ("request_digest", "f" * 64),
        }[changed]
        claimed[key_name] = value
        module.write_json(directory / "claim.json", claimed)
    module.write_json(completed, record)
    with pytest.raises(ConfigError):
        module.exchange(root, "state", {})
    assert not (directory / "accepted.json").exists()


def test_old_generation_measurement_is_reusable_but_not_a_current_claim(queue, monkeypatch):  # noqa: F811
    root, _, request, directory = queue
    payload, _ = interrupt_submit(queue, monkeypatch)
    module.write_json(root / "runtime/controller.json", {"nonce": "generation2"})
    resumed = {**request, "identity": {**request["identity"], "generation": "generation2"}}
    assert (
        module.completed_summary(
            root / "assessment", module.read_json(root / "manifest.json"), resumed
        )
        == payload["envelope"]["body"]["safe_summary"]
    )
    assert module.exchange(root, "state", {})["pending"] == []
    assert not (directory / "accepted.json").exists()
    with pytest.raises(ConfigError, match="Stale"):
        module.exchange(
            root, "claim", {"request_digest": request["request_digest"], "worker_nonce": "e" * 32}
        )


def worker_ready(key, generation, expires_at):
    return sign(
        key,
        {
            "kind": "worker_ready",
            "run_id": "run",
            "plan_digest": "a" * 64,
            "generation": generation,
            "implementation_sha256": "b" * 64,
            "docker_available": True,
            "expires_at": expires_at,
        },
    )


@pytest.mark.parametrize("retained", ["absent", "expired", "old_generation"])
def test_readiness_wait_clears_runtime_phase_only_after_valid_current_worker(
    queue,  # noqa: F811
    monkeypatch,
    retained,
):
    """Use signed readiness + real exchange + real runtime.status_v2 projection."""
    from ahe_beta.experiment import runtime

    root, key, _, _ = queue
    manifest = module.read_json(root / "manifest.json")
    if retained != "absent":
        module.write_json(
            root / "assessment/worker-ready.json",
            worker_ready(
                key,
                "old" if retained == "old_generation" else "generation1",
                time.time() - 1 if retained == "expired" else time.time() + 120,
            ),
        )
    monkeypatch.setattr(runtime, "load_run_v2", lambda **kw: (root, manifest))
    monkeypatch.setattr(runtime, "credentials_v2", lambda **kw: {})
    adapter = SimpleNamespace(
        inspect=lambda: {
            "controller": {"state": "RUNNING", "running": True},
            "resource_state": "RUNNING",
            "progress": {"observation": "OBSERVED"},
        },
        assessment_exchange=lambda action, payload: module.exchange(root, action, payload),
    )
    monkeypatch.setattr(runtime, "backend_v2", lambda **kw: adapter)
    observations = []

    def worker_connects(seconds):
        observed = runtime.status_v2(run_id="run", root=root)
        assert observed["experiment_state"] == "RUNNING"
        assert observed["assessment_state"] == "PENDING"
        assert observed["phase"] == "objective_grading"
        observations.append(observed)
        module.exchange(root, "register", worker_ready(key, "generation1", time.time() + 120))

    monkeypatch.setattr(module.time, "sleep", worker_connects)
    module.RoundAssessment(root, manifest, None, poll_seconds=0).await_worker()
    assert len(observations) == 1
    observed = runtime.status_v2(run_id="run", root=root)
    assert observed["experiment_state"] == "RUNNING"
    assert observed["assessment_state"] == "READY"
    assert observed["phase"] is None
    assert module.read_json(root / "assessment/status.json") == {"assessment_state": "READY"}


@pytest.mark.parametrize("state", ["PENDING", "COMPLETE"])
def test_parallel_ready_launches_preserve_active_measurement_status(queue, state):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor

    root, key, _, _ = queue
    manifest = module.read_json(root / "manifest.json")
    module.exchange(root, "register", worker_ready(key, "generation1", time.time() + 120))
    status = root / "assessment/status.json"
    module.write_json(
        status,
        {
            "phase": "objective_grading",
            "assessment_state": state,
            "round_no": 1,
            "session_id": "session1",
        },
    )
    before = status.read_bytes()
    assessor = module.RoundAssessment(root, manifest, None, poll_seconds=0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: assessor.await_worker(), range(12)))
    assert status.read_bytes() == before
