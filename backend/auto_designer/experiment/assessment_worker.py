"""Trusted external Docker grading worker (Spec-0084/T5).

Only this process receives the private plan and Ed25519 key. The controller sees
an authenticated safe summary; task processes never receive grader materials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import stat
import subprocess
import time
import uuid
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from auto_designer.evaluation.contracts import InputValidationError
from auto_designer.evaluation.service import build_request, evaluate_request, implementation_digest
from auto_designer.execution_contract import (
    canonical_bytes,
    canonical_sha256,
    validate_assessment_summary,
)
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.grading_inputs import (
    GradingPlan,
    archived_artifacts,
    load_grading_plan,
)
from auto_designer.loop.round_assessment import (
    MAX_BUNDLE_BYTES,
    read_json,
    stable_request_id,
    write_json,
)


def public_key_bytes(path: Path) -> bytes:
    payload = Path(path).read_bytes()
    try:
        key = serialization.load_pem_public_key(payload)
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("not Ed25519")
        return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    except ValueError:
        if len(payload) != 32:
            raise ConfigError("Worker public key must be Ed25519 PEM or 32 raw bytes") from None
        Ed25519PublicKey.from_public_bytes(payload)
        return payload


def registration(
    *, config: dict, tasks: list[dict], plan_path: Path | None, public_key_path: Path | None
) -> dict | None:
    options = config.get("evaluation", {}).get("session_grading")
    if options is None:
        if plan_path is not None or public_key_path is not None:
            raise ConfigError("Grading preparation files require evaluation.session_grading")
        return None
    if plan_path is None or public_key_path is None:
        raise ConfigError("Session grading requires --grading-plan and --grading-worker-public-key")
    plan = load_grading_plan(plan_path)
    key = public_key_bytes(public_key_path)
    if (
        plan.digest != options["plan_sha256"]
        or hashlib.sha256(key).hexdigest() != options["worker_key_sha256"]
    ):
        raise ConfigError("Grading plan or worker key differs from frozen configuration digest")
    selections = plan.selections({task["id"] for task in tasks})
    if set(selections) != {task["id"] for task in tasks}:
        raise ConfigError("Online grading plan must cover every frozen task")
    public = {}
    for task in tasks:
        selected = selections[task["id"]]
        from auto_designer.evaluation.service import preflight_plan

        preflight_plan(task=task, plan=plan, selection=selected)
        public[task["id"]] = {
            key: selected[key] for key in ("adapter", "contract_version", "timeout_seconds")
        }
    return {
        "schema_version": 1,
        "worker_public_key": base64.b64encode(key).decode(),
        "implementation_sha256": implementation_digest(),
        "selections": public,
    }


def sign(key: Ed25519PrivateKey, body: dict) -> dict:
    return {"body": body, "signature": base64.b64encode(key.sign(canonical_bytes(body))).decode()}


def _load_key(path: Path) -> Ed25519PrivateKey:
    path = Path(path).expanduser().absolute()
    if (
        path.is_symlink()
        or any(p.is_symlink() for p in path.parents)
        or stat.S_IMODE(path.stat().st_mode) & 0o077
    ):
        raise ConfigError("Worker signing key must be a private regular file (0600 or stricter)")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ConfigError("Worker requires an Ed25519 signing key")
    return key


def _decode_bundle(payload: bytes, request: dict) -> dict:
    if (
        len(payload) > MAX_BUNDLE_BYTES
        or hashlib.sha256(payload).hexdigest() != request["identity"]["artifact_digest"]
    ):
        raise ConfigError("Sealed bundle digest mismatch")
    bundle = json.loads(payload)
    if (
        bundle.get("schema_version") != 1
        or bundle["session_id"] != request["identity"]["session_id"]
    ):
        raise ConfigError("Sealed bundle identity mismatch")
    files = {}
    for name, encoded in bundle["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ConfigError("Unsafe sealed bundle member")
        files[name] = base64.b64decode(encoded, validate=True)
    if {name: hashlib.sha256(data).hexdigest() for name, data in files.items()} != bundle[
        "inventory"
    ]:
        raise ConfigError("Sealed bundle inventory mismatch")
    identity = request["identity"]
    binding = bundle["binding"]
    if (
        bundle["manifest"]["run_id"] != identity["run_id"]
        or bundle["round_state"]["user_sha"] != identity["user_sha"]
        or any(binding[key] != identity[key] for key in ("round_no", "slot", "task_digest"))
        or bundle["task"]["digest"] != identity["task_digest"]
    ):
        raise ConfigError("Sealed bundle source provenance mismatch")
    bundle["files"] = files
    return bundle


def grade_bundle(*, payload: bytes, request: dict, plan: GradingPlan, attempt_dir: Path) -> dict:
    from auto_designer.experiment.grading import _session_entry

    bundle = _decode_bundle(payload, request)
    task = bundle["task"]
    entry, patch = _session_entry(
        binding=bundle["binding"],
        task=task,
        round_state=bundle["round_state"],
        files=bundle["files"],
        manifest=bundle["manifest"],
    )
    if entry["status"] != "ready":
        return {key: value for key, value in entry.items() if key in {"status", "passed", "reason"}}
    selection = plan.selections({t for g in plan.document["graders"] for t in g["task_ids"]})[
        task["id"]
    ]
    identity = request["identity"]
    if (
        plan.digest != identity["plan_digest"]
        or selection["adapter"] != identity["adapter"]
        or selection["contract_version"] != identity["adapter_version"]
        or selection["timeout_seconds"] != identity["timeout_seconds"]
        or implementation_digest() != identity["implementation_sha256"]
    ):
        raise ConfigError("Worker plan/adapter implementation differs from request")
    session = entry["_session"]
    if session.get("execution_contract", {}).get("contract_id") != request["contract_id"]:
        raise ConfigError("Session execution contract mismatch")
    outputs = archived_artifacts(
        receipt=session.get("workspace_evidence", {}).get("evaluation_artifacts"),
        provenance=entry,
        declarations=task["package"].get("artifacts", {}).get("exports", []),
        files=bundle["files"],
        task_package=task["package"],
        expected_config_hash=bundle["manifest"].get("config_hash"),
    )
    try:
        grading = build_request(
            task=task,
            session=session,
            outputs=outputs,
            plan=plan,
            selection=selection,
            patch=patch or "",
        )
    except InputValidationError as exc:
        return {"status": exc.status, "passed": None, "reason": str(exc)}
    return evaluate_request(grading, attempt_dir)


def safe_summary(*, result: dict, request: dict) -> dict:
    status = result["status"]
    if status == "not_evaluated":
        status = "not_configured"
    # Definitions come from fixed adapter code, never the verifier's arbitrary
    # report text. Preserve a continuous score without inventing a pass rule.
    definition = None
    if status == "completed" and result.get("score") is not None:
        definitions = {
            "terminal-bench": {"name": "official reward", "minimum": 0, "maximum": 1},
            "tua-bench": {"name": "official reward", "minimum": 0, "maximum": 1},
            "nl2repo": {"name": "official test ratio", "minimum": 0, "maximum": 1},
            "custom": {"name": "operator custom score"},
        }
        definition = definitions.get(request["identity"]["adapter"])
    # No reason, verifier assertion, stdout or model-generated string crosses the boundary.
    return validate_assessment_summary(
        dict(
            receipt_id="assessment-" + request["request_digest"],
            session_id=request["identity"]["session_id"],
            contract_id=request["contract_id"],
            status=status,
            passed=result.get("passed") if status == "completed" else None,
            score=result.get("score") if status == "completed" else None,
            metric_definition=definition,
            assessment_kind="custom"
            if request["identity"]["adapter"] == "custom"
            else "independent",
            source_sha256=canonical_sha256(result),
        )
    )


def cached_result(path: Path, key: Ed25519PrivateKey, request: dict) -> dict | None:
    """Resume a completed private measurement without running its verifier twice."""
    if not path.exists():
        return None
    from cryptography.exceptions import InvalidSignature

    envelope = read_json(path)
    try:
        body = envelope["body"]
        key.public_key().verify(
            base64.b64decode(envelope["signature"], validate=True), canonical_bytes(body)
        )
        if body["measurement_id"] != stable_request_id(request) or body[
            "result_digest"
        ] != canonical_sha256(body["result"]):
            raise ValueError("measurement differs")
    except (InvalidSignature, KeyError, ValueError, TypeError) as exc:
        raise ConfigError("Private completed assessment cache is invalid") from exc
    return body["result"]


def run_worker(
    *,
    run_id: str,
    root: Path | None,
    plan_path: Path,
    signing_key: Path,
    secrets_file: Path | None = None,
    follow: bool = False,
    poll_seconds: float = 5,
) -> dict:
    from auto_designer.experiment.runtime import backend_v2, credentials_v2, load_run_v2

    run_dir, manifest = load_run_v2(run_id=run_id, root=root)
    options = manifest["config"].get("evaluation", {}).get("session_grading")
    if not options or "assessment_registration" not in manifest:
        raise ConfigError("Run was not prepared for online grading")
    plan = load_grading_plan(plan_path)
    key = _load_key(signing_key)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if (
        plan.digest != options["plan_sha256"]
        or hashlib.sha256(public).hexdigest() != options["worker_key_sha256"]
    ):
        raise ConfigError("Worker plan/key differs from frozen experiment")
    if implementation_digest() != manifest["assessment_registration"]["implementation_sha256"]:
        raise ConfigError("Worker grading implementation differs from frozen experiment")
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode:
        raise ConfigError("External grading worker requires Docker Engine")
    backend = backend_v2(
        run_dir=run_dir,
        manifest=manifest,
        credentials=credentials_v2(manifest=manifest, run_dir=run_dir, secrets_file=secrets_file),
    )
    private = run_dir / "evaluation/online" / uuid.uuid4().hex
    private.mkdir(parents=True, mode=0o700)
    # Freeze only on the trusted host; these paths are excluded from collection.
    materials = {}
    for name, item in plan.materials.items():
        path = private / (name + item["path"].suffix)
        path.write_bytes(item["payload"])
        path.chmod(0o400)
        materials[name] = {**item, "path": path}
    plan = replace(plan, materials=materials)
    count = 0
    while True:
        state = backend.assessment_exchange("state", {})
        observation = backend.inspect()
        controller = observation.get("controller") or {}
        if (
            controller.get("state") in {"EXITED", "STOPPED"}
            and not controller.get("running")
            and not state["pending"]
        ):
            return {"action": "assessment-worker", "completed": count, "run_id": run_id}
        body = {
            "kind": "worker_ready",
            "run_id": run_id,
            "plan_digest": plan.digest,
            "generation": state["generation"],
            "implementation_sha256": implementation_digest(),
            "docker_available": True,
            "expires_at": time.time() + 120,
        }
        backend.assessment_exchange("register", sign(key, body))
        for row in state["pending"]:
            digest = row["request_digest"]
            claimed = backend.assessment_exchange(
                "claim", {"request_digest": digest, "worker_nonce": uuid.uuid4().hex}
            )
            if claimed["state"] != "claimed":
                continue
            request, claim = claimed["request"], claimed["claim"]
            payload = backend.assessment_download(digest)
            attempt = private / digest / str(claim["claim_epoch"])
            attempt.mkdir(parents=True, mode=0o700)
            cache = run_dir / "evaluation/online/completed" / (stable_request_id(request) + ".json")
            result = cached_result(cache, key, request)
            if result is None:
                try:
                    result = grade_bundle(
                        payload=payload, request=request, plan=plan, attempt_dir=attempt
                    )
                except (ConfigError, ValueError) as exc:
                    # A corrupt provenance bundle is not a task failure.
                    result = {"status": "ungradable", "passed": None, "reason": str(exc)}
                except OSError as exc:
                    result = {"status": "unavailable", "passed": None, "reason": str(exc)}
                write_json(
                    cache,
                    sign(
                        key,
                        {
                            "measurement_id": stable_request_id(request),
                            "result_digest": canonical_sha256(result),
                            "result": result,
                        },
                    ),
                )
            write_json(attempt / "result.json", result)
            summary = safe_summary(result=result, request=request)
            body = {
                "kind": "assessment_result",
                "run_id": run_id,
                "plan_digest": plan.digest,
                **{
                    key: claim[key]
                    for key in ("request_digest", "generation", "claim_epoch", "worker_nonce")
                },
                "private_result_digest": canonical_sha256(result),
                "safe_summary": summary,
                "safe_summary_digest": canonical_sha256(summary),
            }
            envelope = sign(key, body)
            write_json(attempt / "receipt.json", envelope)
            backend.assessment_exchange("submit", {"request_digest": digest, "envelope": envelope})
            count += 1
        if not follow:
            return {"action": "assessment-worker", "completed": count, "run_id": run_id}
        time.sleep(poll_seconds)
