"""Registered worker identity, stale delivery and null failure semantics (Spec-0084/T5)."""

import base64
import hashlib
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auto_designer.execution_contract import canonical_sha256
from auto_designer.experiment.assessment_worker import safe_summary, sign
from auto_designer.experiment.config import ConfigError
from auto_designer.loop.round_assessment import exchange, read_json, write_json


@pytest.fixture
def queue(tmp_path):
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    manifest = {
        "run_id": "run",
        "config": {
            "evaluation": {
                "session_grading": {
                    "plan_sha256": "a" * 64,
                    "worker_key_sha256": hashlib.sha256(raw).hexdigest(),
                }
            }
        },
        "assessment_registration": {
            "worker_public_key": base64.b64encode(raw).decode(),
            "implementation_sha256": "b" * 64,
        },
    }
    write_json(tmp_path / "manifest.json", manifest)
    write_json(tmp_path / "runtime/controller.json", {"nonce": "generation1"})
    body = {
        "schema_version": 1,
        "identity": {
            "run_id": "run",
            "session_id": "session1",
            "generation": "generation1",
            "timeout_seconds": 30,
            "plan_digest": "a" * 64,
            "adapter": "custom",
        },
        "contract_id": "c" * 64,
    }
    digest = canonical_sha256(body)
    request = {**body, "request_digest": digest}
    directory = tmp_path / "assessment/requests" / digest
    write_json(directory / "request.json", request)
    return tmp_path, key, request, directory


def claim(queue, nonce="d" * 32):
    root, key, request, directory = queue
    return exchange(
        root, "claim", {"request_digest": request["request_digest"], "worker_nonce": nonce}
    )["claim"]


def result(queue, claimed, passed=False):
    root, key, request, directory = queue
    raw = {
        "status": "completed",
        "passed": passed,
        "reason": "SECRET TEST ASSERTION",
        "raw_report": {"gold": "secret"},
    }
    summary = safe_summary(result=raw, request=request)
    body = {
        "kind": "assessment_result",
        "run_id": "run",
        "plan_digest": "a" * 64,
        **{k: claimed[k] for k in ("request_digest", "generation", "claim_epoch", "worker_nonce")},
        "safe_summary": summary,
        "safe_summary_digest": canonical_sha256(summary),
        "private_result_digest": canonical_sha256(raw),
    }
    return {"request_digest": request["request_digest"], "envelope": sign(key, body)}


def test_signed_negative_is_accepted_once_and_no_hidden_details_return(queue):
    root, key, request, directory = queue
    payload = result(queue, claim(queue), False)
    assert "SECRET" not in str(payload) and "gold" not in str(payload)
    assert exchange(root, "submit", payload)["accepted"]
    assert exchange(root, "submit", payload)["duplicate"]
    assert read_json(directory / "accepted.json")["body"]["safe_summary"]["passed"] is False
    changed = result(queue, read_json(directory / "claim.json"), True)
    with pytest.raises(ConfigError, match="Conflicting"):
        exchange(root, "submit", changed)


def test_completed_measurement_survives_controller_restart(queue):
    from auto_designer.loop.round_assessment import completed_summary

    root, key, request, directory = queue
    payload = result(queue, claim(queue), False)
    exchange(root, "submit", payload)
    resumed = {**request, "identity": {**request["identity"], "generation": "new-generation"}}
    summary = completed_summary(root / "assessment", read_json(root / "manifest.json"), resumed)
    assert summary == payload["envelope"]["body"]["safe_summary"]
    resumed["identity"]["user_sha"] = "another-source"
    assert (
        completed_summary(root / "assessment", read_json(root / "manifest.json"), resumed) is None
    )


def test_private_completed_cache_is_signed_and_cannot_change_measurement(queue):
    from auto_designer.experiment.assessment_worker import cached_result
    from auto_designer.loop.round_assessment import stable_request_id

    root, key, request, directory = queue
    value = {"status": "completed", "passed": False, "raw_report": {"assertion": "private"}}
    cache = root / "private-result.json"
    envelope = sign(
        key,
        {
            "measurement_id": stable_request_id(request),
            "result_digest": canonical_sha256(value),
            "result": value,
        },
    )
    write_json(cache, envelope)
    assert cached_result(cache, key, request) == value
    envelope["body"]["result"]["passed"] = True
    write_json(cache, envelope)
    with pytest.raises(ConfigError, match="cache is invalid"):
        cached_result(cache, key, request)


def test_continuous_metric_preserved_without_binary_pass_rule(queue):
    request = queue[2]
    request["identity"]["adapter"] = "nl2repo"
    summary = safe_summary(
        result={
            "status": "completed",
            "passed": None,
            "score": 0.75,
            "score_definition": "SECRET arbitrary text",
        },
        request=request,
    )
    assert summary["passed"] is None and summary["score"] == 0.75
    assert summary["metric_definition"]["name"] == "official test ratio"
    assert "SECRET" not in str(summary)


def test_forged_worker_cannot_replace_a_summary(queue):
    payload = result(queue, claim(queue))
    payload["envelope"] = sign(Ed25519PrivateKey.generate(), payload["envelope"]["body"])
    with pytest.raises(ConfigError, match="signature"):
        exchange(queue[0], "submit", payload)


def test_superseded_worker_and_generation_rejected(queue):
    root, key, request, directory = queue
    first = claim(queue)
    stale = result(queue, first)
    expired = {**first, "lease_until": 0}
    write_json(directory / "claim.json", expired)
    second = claim(queue, "e" * 32)
    assert second["claim_epoch"] == first["claim_epoch"] + 1
    with pytest.raises(ConfigError, match="superseded"):
        exchange(root, "submit", stale)
    write_json(root / "runtime/controller.json", {"nonce": "generation2"})
    with pytest.raises(ConfigError, match="Stale"):
        exchange(root, "submit", result(queue, second))


def test_busy_claim_is_not_reassigned_and_expired_result_rejected(queue):
    first = claim(queue)
    root, key, request, directory = queue
    assert (
        exchange(
            root, "claim", {"request_digest": request["request_digest"], "worker_nonce": "e" * 32}
        )["state"]
        == "busy"
    )
    write_json(directory / "claim.json", {**first, "lease_until": 0})
    with pytest.raises(ConfigError, match="expired"):
        exchange(root, "submit", result(queue, first))


@pytest.mark.parametrize(
    "status",
    ["unavailable", "crashed", "timed_out", "ungradable", "missing_artifact", "unsupported"],
)
def test_infrastructure_failure_never_becomes_a_zero_score(queue, status):
    summary = safe_summary(
        result={"status": status, "passed": False, "score": 0, "raw_report": {"secret": 1}},
        request=queue[2],
    )
    assert summary["passed"] is None and summary["score"] is None


def test_ready_requires_registered_signature_current_generation_and_capability(queue):
    root, key, request, directory = queue
    body = {
        "kind": "worker_ready",
        "run_id": "run",
        "plan_digest": "a" * 64,
        "generation": "generation1",
        "implementation_sha256": "b" * 64,
        "docker_available": True,
        "expires_at": time.time() + 120,
    }
    assert exchange(root, "register", sign(key, body))["registered"]
    body["generation"] = "old"
    with pytest.raises(ConfigError, match="capability"):
        exchange(root, "register", sign(key, body))


def test_arbitrary_rpc_and_path_are_rejected(queue):
    with pytest.raises(ConfigError):
        exchange(queue[0], "shell", {"request_digest": "../../etc/passwd"})


@pytest.mark.parametrize("new_generation", [False, True])
def test_worker_crash_before_submit_reuses_signed_result_without_regrading(
    queue, monkeypatch, new_generation
):
    """A lost delivery may need a new claim/generation, never a second verifier run."""
    from types import SimpleNamespace

    from cryptography.hazmat.primitives import serialization

    from auto_designer.experiment import assessment_worker as worker
    from auto_designer.experiment import runtime
    from auto_designer.experiment.grading_inputs import GradingPlan
    from auto_designer.loop.round_assessment import stable_request_id

    root, key, request, directory = queue
    manifest = read_json(root / "manifest.json")
    key_file = root / "private.key"
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_file.chmod(0o600)
    plan = GradingPlan({}, "a" * 64, b"fixed private plan", {})
    grades = []
    drops = [True]

    class Transport:
        def assessment_exchange(self, action, payload):
            if action == "submit" and drops[0]:
                drops[0] = False
                raise ConnectionError("injected loss before submit")
            return exchange(root, action, payload)

        def assessment_download(self, digest):
            return b"sealed actor bytes"

        def inspect(self):
            return {
                "controller": {"state": "RUNNING", "running": True},
                "resource_state": "RUNNING",
            }

    def grade(**kwargs):
        grades.append(kwargs["payload"])
        return {"status": "completed", "passed": False, "raw_report": {"private": "assertion"}}

    monkeypatch.setattr(runtime, "load_run_v2", lambda **kw: (root, manifest))
    monkeypatch.setattr(runtime, "credentials_v2", lambda **kw: {})
    monkeypatch.setattr(runtime, "backend_v2", lambda **kw: Transport())
    monkeypatch.setattr(worker, "load_grading_plan", lambda path: plan)
    monkeypatch.setattr(worker, "implementation_digest", lambda: "b" * 64)
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(worker, "grade_bundle", grade)
    arguments = dict(
        run_id="run", root=root.parent, plan_path=root / "plan.json", signing_key=key_file
    )
    with pytest.raises(ConnectionError, match="before submit"):
        worker.run_worker(**arguments)
    cached = root / "evaluation/online/completed" / (stable_request_id(request) + ".json")
    assert cached.is_file() and not (directory / "accepted.json").exists()
    result_files = list((root / "evaluation/online").glob("*/*/*/result.json"))
    assert len(result_files) == 1 and read_json(result_files[0])["passed"] is False

    if new_generation:
        write_json(root / "runtime/controller.json", {"nonce": "generation2"})
        request = {
            **request,
            "identity": {**request["identity"], "generation": "generation2"},
        }
        request["request_digest"] = canonical_sha256(
            {key: value for key, value in request.items() if key != "request_digest"}
        )
        directory = root / "assessment/requests" / request["request_digest"]
        write_json(directory / "request.json", request)
    else:
        prior = read_json(directory / "claim.json")
        write_json(directory / "claim.json", {**prior, "lease_until": 0})

    outcome = worker.run_worker(**arguments)
    assert outcome["completed"] == 1
    assert grades == [b"sealed actor bytes"]
    accepted = read_json(directory / "accepted.json")["body"]
    assert accepted["safe_summary"]["passed"] is False
    assert "private" not in str(accepted["safe_summary"])
    assert accepted["generation"] == ("generation2" if new_generation else "generation1")
    assert worker.run_worker(**arguments)["completed"] == 0
    assert len(grades) == 1


@pytest.mark.parametrize(
    "first_observation,registrations",
    [
        ({"controller": {"state": "EXITED", "running": False}, "resource_state": "RUNNING"}, 0),
        ({"state": "EXITED", "controller": {"state": "EXITED", "running": False}}, 0),
        ({"controller": {"state": "STOPPED", "running": False}, "resource_state": "STOPPED"}, 0),
        ({"state": "EXITED", "controller": {"state": "RUNNING", "running": True}}, 1),
        ({"controller": {"state": "UNKNOWN"}, "resource_state": "DESTROYED"}, 1),
        ({"controller": {"state": "EXITED", "running": True}}, 1),
    ],
)
def test_follow_worker_uses_nested_controller_observation(
    queue, monkeypatch, first_observation, registrations
):
    _exercise_worker_exit(queue, monkeypatch, first_observation, registrations=registrations)


def test_terminal_controller_with_pending_claim_keeps_worker_alive(queue, monkeypatch):
    _exercise_worker_exit(
        queue,
        monkeypatch,
        {"controller": {"state": "EXITED", "running": False}},
        registrations=1,
        pending_first=True,
    )


def _exercise_worker_exit(
    queue, monkeypatch, first_observation, *, registrations, pending_first=False
):
    from types import SimpleNamespace

    from auto_designer.experiment import assessment_worker as worker
    from auto_designer.experiment import runtime
    from auto_designer.experiment.grading_inputs import GradingPlan

    root, key, _, _ = queue
    manifest = read_json(root / "manifest.json")
    key_file = root / "private.key"
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_file.chmod(0o600)
    calls, sleeps = [], []

    class Transport:
        inspections = 0

        def inspect(self):
            self.inspections += 1
            assert self.inspections <= 2, "worker ignored a terminal controller receipt"
            return (
                first_observation
                if self.inspections == 1
                else {"controller": {"state": "EXITED", "running": False}}
            )

        def assessment_exchange(self, action, payload):
            calls.append(action)
            if action == "state":
                return {
                    "generation": "generation1",
                    "pending": [{"request_digest": "d" * 64}]
                    if pending_first and self.inspections == 0
                    else [],
                }
            if action == "register":
                return {"registered": True}
            if action == "claim":
                return {"state": "busy"}
            raise AssertionError(action)

    backend = Transport()
    monkeypatch.setattr(runtime, "load_run_v2", lambda **kw: (root, manifest))
    monkeypatch.setattr(runtime, "credentials_v2", lambda **kw: {})
    monkeypatch.setattr(runtime, "backend_v2", lambda **kw: backend)
    monkeypatch.setattr(
        worker, "load_grading_plan", lambda _: GradingPlan({}, "a" * 64, b"plan", {})
    )
    monkeypatch.setattr(worker, "implementation_digest", lambda: "b" * 64)
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(worker.time, "sleep", lambda value: sleeps.append(value))
    outcome = worker.run_worker(
        run_id="run",
        root=root.parent,
        plan_path=root / "plan.json",
        signing_key=key_file,
        follow=True,
    )
    assert outcome == {"action": "assessment-worker", "completed": 0, "run_id": "run"}
    assert backend.inspections == registrations + 1
    assert calls.count("register") == len(sleeps) == registrations
    assert calls.count("claim") == int(pending_first)
