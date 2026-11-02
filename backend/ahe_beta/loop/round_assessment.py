"""Sealed-session grading exchange and round recovery (Spec-0084/T5).

The controller accepts only a registered worker's signed safe summary. Private
plans and verifier reports never cross this interface. Provider adapters invoke
these fixed operations through their existing ownership-checked management path.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ahe_beta.execution_contract import (
    canonical_bytes,
    canonical_sha256,
    validate_assessment_summary,
)
from ahe_beta.experiment.config import ConfigError

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_BUNDLE_BYTES = 256 * 1024 * 1024


def write_json(path: Path, value) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ConfigError("Unsafe assessment output path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        with tmp.open("xb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ConfigError("Assessment state contains a symlink")
    return json.loads(path.read_bytes())


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ConfigError("Invalid assessment request digest")
    return value


@contextmanager
def _lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ConfigError("Unsafe assessment management path")
    with (root / ".exchange.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _generation(run_dir: Path) -> str:
    nonce = read_json(run_dir / "runtime/controller.json").get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise ConfigError("Assessment requires a known controller generation")
    return nonce


def _verify(manifest: dict, envelope: dict) -> dict:
    try:
        body = envelope["body"]
        key = base64.b64decode(
            manifest["assessment_registration"]["worker_public_key"], validate=True
        )
        expected = manifest["config"]["evaluation"]["session_grading"]["worker_key_sha256"]
        if hashlib.sha256(key).hexdigest() != expected:
            raise ValueError("worker key mismatch")
        Ed25519PublicKey.from_public_bytes(key).verify(
            base64.b64decode(envelope["signature"], validate=True), canonical_bytes(body)
        )
        if (
            body["run_id"] != manifest["run_id"]
            or body["plan_digest"]
            != manifest["config"]["evaluation"]["session_grading"]["plan_sha256"]
        ):
            raise ValueError("worker run/plan mismatch")
        return body
    except (KeyError, ValueError, TypeError, InvalidSignature) as exc:
        raise ConfigError("Invalid registered assessment worker signature/identity") from exc


def stable_request_id(request: dict) -> str:
    """Stable measurement identity across controller restarts, excluding delivery nonce."""
    identity = {k: v for k, v in request["identity"].items() if k != "generation"}
    return canonical_sha256({"identity": identity, "contract_id": request["contract_id"]})


def _completed_record(root: Path, manifest: dict, request: dict) -> dict | None:
    path = root / "completed" / (stable_request_id(request) + ".json")
    if not path.exists():
        return None
    record = read_json(path)
    prior = record["request"]
    if (
        stable_request_id(prior) != stable_request_id(request)
        or canonical_sha256({k: v for k, v in prior.items() if k != "request_digest"})
        != prior["request_digest"]
    ):
        raise ConfigError("Retained assessment source identity changed")
    body = _verify(manifest, record["envelope"])
    summary = validate_assessment_summary(body["safe_summary"])
    if (
        body.get("kind") != "assessment_result"
        or body.get("generation") != prior["identity"]["generation"]
        or body["request_digest"] != prior["request_digest"]
        or body["safe_summary_digest"] != canonical_sha256(summary)
        or summary["source_sha256"] != body["private_result_digest"]
        or summary["contract_id"] != prior["contract_id"]
        or summary["session_id"] != prior["identity"]["session_id"]
    ):
        raise ConfigError("Retained assessment receipt mismatch")
    return record


def completed_summary(root: Path, manifest: dict, request: dict) -> dict | None:
    record = _completed_record(root, manifest, request)
    return record["envelope"]["body"]["safe_summary"] if record is not None else None


def _restore_accepted(root: Path, manifest: dict, request: dict) -> bool:
    """Finish a durable submit after a crash; caller holds the exchange lock."""
    digest = _digest(request["request_digest"])
    if canonical_sha256({k: v for k, v in request.items() if k != "request_digest"}) != digest:
        raise ConfigError("Changed assessment request")
    directory = root / "requests" / digest
    accepted = directory / "accepted.json"
    if accepted.exists():
        return True
    record = _completed_record(root, manifest, request)
    if record is None or record["request"] != request:
        # Stable measurement reuse across generations belongs to the controller;
        # it must not impersonate a new generation's claim/acceptance exchange.
        return False
    body = record["envelope"]["body"]
    claim = read_json(directory / "claim.json")
    if (
        claim.get("request_digest") != digest
        or claim.get("generation") != request["identity"]["generation"]
        or any(body.get(key) != claim.get(key) for key in ("claim_epoch", "worker_nonce"))
    ):
        raise ConfigError("Retained assessment claim has been superseded")
    # The completed record was committed after the original lease check. A
    # later expiry does not revoke that result, just as for an accepted receipt.
    write_json(accepted, record["envelope"])
    return True


def exchange(run_dir: Path, action: str, payload: dict) -> dict:
    """Bounded fixed RPC, never executes caller-provided commands or paths."""
    run_dir = Path(run_dir)
    root = run_dir / "assessment"
    manifest = read_json(run_dir / "manifest.json")
    with _lock(root):
        generation = _generation(run_dir)
        if action == "register":
            body = _verify(manifest, payload)
            now = time.time()
            if (
                body.get("kind") != "worker_ready"
                or body.get("generation") != generation
                or body.get("implementation_sha256")
                != manifest["assessment_registration"]["implementation_sha256"]
                or body.get("docker_available") is not True
                or not now < body.get("expires_at", 0) <= now + 600
            ):
                raise ConfigError("Worker readiness does not match current execution capability")
            write_json(root / "worker-ready.json", payload)
            return {"registered": True}
        if action == "state":
            pending = []
            for path in sorted((root / "requests").glob("*/request.json")):
                request = read_json(path)
                if request["identity"]["generation"] == generation and not _restore_accepted(
                    root, manifest, request
                ):
                    pending.append(
                        {"request_digest": path.parent.name, "identity": request["identity"]}
                    )
            return {
                "generation": generation,
                "pending": pending,
                "assessment": read_json(root / "status.json")
                if (root / "status.json").exists()
                else {},
            }
        digest = _digest(payload.get("request_digest"))
        directory = root / "requests" / digest
        request = read_json(directory / "request.json")
        if (
            canonical_sha256({k: v for k, v in request.items() if k != "request_digest"}) != digest
            or request["identity"]["generation"] != generation
        ):
            raise ConfigError("Stale or changed assessment request")
        if action == "claim":
            nonce = payload.get("worker_nonce")
            if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
                raise ConfigError("Invalid worker nonce")
            accepted = directory / "accepted.json"
            if _restore_accepted(root, manifest, request):
                return {"state": "accepted", "receipt": read_json(accepted)}
            prior = (
                read_json(directory / "claim.json") if (directory / "claim.json").exists() else {}
            )
            if prior.get("lease_until", 0) > time.time():
                return {"state": "busy"}
            claim = {
                "request_digest": digest,
                "generation": generation,
                "claim_epoch": prior.get("claim_epoch", 0) + 1,
                "worker_nonce": nonce,
                "lease_until": time.time() + request["identity"]["timeout_seconds"] + 600,
            }
            write_json(directory / "claim.json", claim)
            return {"state": "claimed", "claim": claim, "request": request}
        if action == "submit":
            body = _verify(manifest, payload["envelope"])
            if (
                body.get("kind") != "assessment_result"
                or body.get("request_digest") != digest
                or body.get("generation") != generation
            ):
                raise ConfigError("Worker result is not for this request/generation")
            claim = read_json(directory / "claim.json")
            if any(body.get(key) != claim.get(key) for key in ("claim_epoch", "worker_nonce")):
                raise ConfigError("Worker claim has been superseded")
            accepted = directory / "accepted.json"
            if _restore_accepted(root, manifest, request):
                if read_json(accepted) != payload["envelope"]:
                    raise ConfigError("Conflicting duplicate assessment result")
                return {"accepted": True, "duplicate": True}
            if claim["lease_until"] <= time.time():
                raise ConfigError("Worker claim has expired")
            summary = validate_assessment_summary(body["safe_summary"])
            if (
                body.get("safe_summary_digest") != canonical_sha256(summary)
                or summary["source_sha256"] != body.get("private_result_digest")
                or summary["session_id"] != request["identity"]["session_id"]
                or summary["contract_id"] != request["contract_id"]
            ):
                raise ConfigError("Assessment summary binding mismatch")
            write_json(
                root / "completed" / (stable_request_id(request) + ".json"),
                {"request": request, "envelope": payload["envelope"]},
            )
            write_json(accepted, payload["envelope"])
            return {"accepted": True, "duplicate": False}
        raise ConfigError("Unknown assessment exchange operation")


def bundle_path(run_dir: Path, digest: str) -> Path:
    path = Path(run_dir) / "assessment/requests" / _digest(digest) / "bundle.json"
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or not path.is_file()
        or path.stat().st_size > MAX_BUNDLE_BYTES
    ):
        raise ConfigError("Invalid sealed assessment bundle")
    return path


def _bundle(run_dir: Path, manifest: dict, recovery, round_no: int, binding: dict, store) -> dict:
    from ahe_beta.loop.recovery import operation_key

    sid = operation_key(manifest["run_id"], "users", binding)
    session = store.load(sid)
    document = session.to_dict()
    files = {f"data/role_runs/{manifest['run_id']}/sessions/{sid}.json": canonical_bytes(document)}
    evidence = document.get("workspace_evidence", {})
    relatives = []
    if evidence.get("prediction"):
        relatives.append(evidence["prediction"]["path"])
    for entry in evidence.get("evaluation_artifacts", {}).get("entries", []):
        if entry.get("status") == "collected":
            relatives.append(entry["path"])
    for relative in relatives:
        path = store.root.parent / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or any(p.is_symlink() for p in (path, *path.parents))
        ):
            raise ConfigError("Unsafe sealed artifact path")
        files[f"data/role_runs/{manifest['run_id']}/{relative}"] = path.read_bytes()
    state = recovery.round_state(round_no=round_no)
    # Only the sealed user stage belongs to this measurement. Later demand or
    # grading ledger writes must not change its identity during recovery.
    state = {"user_sha": state["user_sha"], "stages": {"users": state["stages"]["users"]}}
    unit = state["stages"]["users"]["units"][sid]
    relative = unit["output_artifact"]
    path = recovery.root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise ConfigError("Unsafe user unit receipt")
    files["checkpoints/" + relative] = path.read_bytes()
    return {
        "schema_version": 1,
        "session_id": sid,
        "binding": binding,
        "round_state": state,
        "manifest": {"run_id": manifest["run_id"]},
        "files": {name: base64.b64encode(data).decode() for name, data in files.items()},
        "inventory": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }


class RoundAssessment:
    def __init__(self, run_dir: Path, manifest: dict, store, *, poll_seconds: float = 5):
        self.run_dir, self.manifest, self.store = Path(run_dir), manifest, store
        self.poll_seconds = poll_seconds
        self.config = manifest["config"].get("evaluation", {}).get("session_grading")

    def await_worker(self):
        if not self.config:
            return
        root = self.run_dir / "assessment"
        while True:
            with _lock(root):
                path = root / "worker-ready.json"
                if path.exists():
                    body = _verify(self.manifest, read_json(path))
                    if (
                        body.get("generation") == _generation(self.run_dir)
                        and body.get("expires_at", 0) > time.time()
                    ):
                        status_path = root / "status.json"
                        status = read_json(status_path) if status_path.exists() else {}
                        if (
                            status.get("assessment_state") == "PENDING"
                            and status.get("reason") == "worker_not_ready"
                        ):
                            # Clear only this readiness wait, never an active
                            # measurement's PENDING or a completed projection.
                            write_json(status_path, {"assessment_state": "READY"})
                        return
                write_json(
                    root / "status.json",
                    {
                        "phase": "objective_grading",
                        "assessment_state": "PENDING",
                        "reason": "worker_not_ready",
                    },
                )
            time.sleep(self.poll_seconds)

    def __call__(self, *, round_no: int, user_sha: str, bindings: list, recovery) -> None:
        from ahe_beta.experiment.workload import read_task_catalog, tasks_by_id

        root = self.run_dir / "assessment"
        projection = root / "feedback" / f"round-{round_no}.json"
        if recovery.stage_status(round_no=round_no, stage="objective_grading") == "completed":
            frozen = read_json(projection)
            saved = recovery.read_output(
                round_no=round_no, stage="objective_grading", key=f"objective-grading-{round_no}"
            )
            if (
                frozen != saved
                or frozen["user_sha"] != user_sha
                or frozen["sha256"] != canonical_sha256(frozen["summaries"])
            ):
                raise ConfigError("Frozen round feedback changed")
            # Spec-0084/T5: the ledger may commit before this derived status write.
            with _lock(root):
                write_json(
                    root / "status.json",
                    {
                        "phase": "objective_grading",
                        "assessment_state": "COMPLETE",
                        "round_no": round_no,
                    },
                )
            return
        summaries = []
        tasks = tasks_by_id(read_task_catalog(self.run_dir, self.manifest))
        for binding in bindings:
            from ahe_beta.loop.recovery import operation_key

            sid = operation_key(self.manifest["run_id"], "users", binding)
            session = self.store.load(sid)
            if not self.config:
                summaries.append(
                    dict(
                        receipt_id=f"not-configured-{sid}",
                        session_id=sid,
                        contract_id=session.execution_contract["contract_id"],
                        status="not_configured",
                        passed=None,
                        score=None,
                        metric_definition=None,
                        assessment_kind="independent",
                        source_sha256=canonical_sha256({"not_configured": sid}),
                    )
                )
                continue
            bundle = _bundle(self.run_dir, self.manifest, recovery, round_no, binding, self.store)
            bundle["task"] = tasks[binding["task_id"]]
            payload = canonical_bytes(bundle)
            if len(payload) > MAX_BUNDLE_BYTES:
                raise ConfigError("Sealed assessment bundle exceeds its limit")
            selection = self.manifest["assessment_registration"]["selections"][binding["task_id"]]
            identity = {
                "run_id": self.manifest["run_id"],
                "round_no": round_no,
                "slot": binding["slot"],
                "session_id": sid,
                "user_sha": user_sha,
                "task_digest": binding["task_digest"],
                "artifact_digest": hashlib.sha256(payload).hexdigest(),
                "plan_digest": self.config["plan_sha256"],
                "adapter": selection["adapter"],
                "adapter_version": selection["contract_version"],
                "implementation_sha256": self.manifest["assessment_registration"][
                    "implementation_sha256"
                ],
                "timeout_seconds": selection["timeout_seconds"],
                "generation": _generation(self.run_dir),
            }
            body = {
                "schema_version": 1,
                "identity": identity,
                "contract_id": session.execution_contract["contract_id"],
            }
            retained = completed_summary(root, self.manifest, body)
            if retained is not None:
                summaries.append(retained)
                continue
            self.await_worker()
            digest = canonical_sha256(body)
            directory = root / "requests" / digest
            with _lock(root):
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = directory / "bundle.json"
                if target.exists() and target.read_bytes() != payload:
                    raise ConfigError("Sealed session bundle changed")
                if not target.exists():
                    write_json(target, bundle)
                request = {**body, "request_digest": digest}
                if (directory / "request.json").exists() and read_json(
                    directory / "request.json"
                ) != request:
                    raise ConfigError("Frozen request changed")
                write_json(directory / "request.json", request)
            while True:
                with _lock(root):
                    if _restore_accepted(root, self.manifest, request):
                        break
                    write_json(
                        root / "status.json",
                        {
                            "phase": "objective_grading",
                            "assessment_state": "PENDING",
                            "round_no": round_no,
                            "session_id": sid,
                        },
                    )
                time.sleep(self.poll_seconds)
            envelope = read_json(directory / "accepted.json")
            body = _verify(self.manifest, envelope)
            retained = completed_summary(root, self.manifest, request)
            if retained is None or retained != body["safe_summary"]:
                raise ConfigError("Accepted assessment receipt is missing or inconsistent")
            summaries.append(retained)
        frozen = {
            "round_no": round_no,
            "user_sha": user_sha,
            "summaries": summaries,
            "sha256": canonical_sha256(summaries),
        }
        if projection.exists() and read_json(projection) != frozen:
            raise ConfigError("Round feedback projection conflicts with its frozen receipt")
        write_json(projection, frozen)
        key = f"objective-grading-{round_no}"
        recovery.begin_unit(
            round_no=round_no,
            stage="objective_grading",
            key=key,
            input_value={"user_sha": user_sha},
            expected_postconditions={"completed": True},
            dependencies=("users",),
        )
        recovery.save_output(round_no=round_no, stage="objective_grading", key=key, output=frozen)
        recovery.complete_unit(
            round_no=round_no,
            stage="objective_grading",
            key=key,
            observed_postconditions={"completed": True},
        )
        recovery.complete_stage(round_no=round_no, stage="objective_grading")
        with _lock(root):
            write_json(
                root / "status.json",
                {
                    "phase": "objective_grading",
                    "assessment_state": "COMPLETE",
                    "round_no": round_no,
                },
            )
