"""Spec-0069/T5: portable, checksummed evidence collection independent of model keys."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.materials import sha256_file

_EXCLUDED = {
    "secrets",
    ".git",
    ".venv",
    "__pycache__",
    ".openagents",
    ".runner",  # Spec-0077/T4: act_runner registration contains a private credential.
    "archive",
    "source",
    "cloud-snapshot",
    "collection-stage",
    ".cache",
}


def export_gitea_snapshot(
    *,
    run_dir: Path,
    resources: Mapping[str, Any],
    credentials: Mapping[str, str],
    terminal: bool = False,
    controller_nonce: str | None = None,
) -> dict[str, Any]:
    """Capture issue/comment/PR facts without a model call or deleting remote data."""
    from urllib.parse import quote

    import requests

    gitea = resources.get("gitea") or {}
    destination = run_dir / "runtime/gitea-evidence.json"
    if not all(gitea.get(field) for field in ("url", "owner", "repo")):
        return {"applicable": False, "complete": True}
    prefix = (
        str(gitea["url"]).rstrip("/")
        + "/api/v1/repos/"
        + quote(str(gitea["owner"]), safe="")
        + "/"
        + quote(str(gitea["repo"]), safe="")
    )
    headers = {"Authorization": "token " + credentials.get("GITEA_TOKEN", "")}

    def get(path: str, params: dict | None = None) -> Any:
        response = requests.get(prefix + path, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            raise ConfigError(f"Gitea evidence export failed (HTTP {response.status_code})")
        return response.json()

    def pages(path: str, **params: Any) -> list:
        values = []
        for page in range(1, 10001):
            batch = get(path, {**params, "page": page, "limit": 50})
            if not isinstance(batch, list):
                raise ConfigError("Gitea evidence endpoint returned an invalid list")
            values.extend(batch)
            if len(batch) < 50:
                return values
        raise ConfigError("Gitea evidence pagination exceeded supported limit")

    try:
        issues = pages("/issues", state="all", type="issues")
        pulls = pages("/pulls", state="all")
        document = {
            "repository": get(""),
            "issues": issues,
            "pulls": pulls,
            "branches": pages("/branches"),
            "comments": {},
            "captured_at": datetime.now(UTC).isoformat(),
            "terminal": terminal,
            "controller_nonce": controller_nonce,
        }
        # Spec-0077/T4: preserve facts for each current head, never reuse an old PR green.
        if (resources.get("ci") or {}).get("enabled") is True:
            document["ci"] = _ci_evidence(
                ci=resources["ci"], branches=document["branches"], pulls=pulls, get=get
            )
        for item in [*issues, *pulls]:
            index = str(int(item["number"]))
            document["comments"][index] = pages("/issues/" + index + "/comments")
        destination.parent.mkdir(exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return {
            "applicable": True,
            "complete": True,
            "terminal": terminal,
            "sha256": sha256_file(destination),
            "path": str(destination),
        }
    except (requests.RequestException, ConfigError, ValueError, KeyError):
        if destination.is_file():
            previous = json.loads(destination.read_text())
            # local stop captured this after stopping the controller and before
            # stopping Gitea. Active checkpoints alone cannot seal an archive.
            return {
                "applicable": True,
                "complete": bool(previous.get("terminal"))
                and previous.get("controller_nonce") == controller_nonce,
                "terminal": bool(previous.get("terminal"))
                and previous.get("controller_nonce") == controller_nonce,
                "retained": True,
                "path": str(destination),
            }
        return {"applicable": True, "complete": False, "terminal": False}


def _ci_evidence(*, ci: Mapping[str, Any], branches: list, pulls: list, get: Any) -> dict:
    """Spec-0077/T4: archive public runner facts and actual commit-status observations."""
    heads = set()
    for item in branches:
        heads.add((item.get("commit") or {}).get("id"))
    for item in pulls:
        heads.add((item.get("head") or {}).get("sha"))
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in heads):
        raise ConfigError("Gitea CI evidence has an invalid current commit identity")
    statuses = {}
    for sha in sorted(heads):
        result = get("/commits/" + sha + "/status")
        if not isinstance(result, dict) or not isinstance(result.get("statuses"), list):
            raise ConfigError("Gitea CI evidence has an invalid combined status response")
        statuses[sha] = result
    runner = ci.get("runner") or {}
    daemon = ci.get("daemon") or {}
    readiness = ci.get("readiness") or {}
    # Registration credentials and opaque future fields are not public evidence.
    return {
        "enabled": True,
        **{
            key: ci.get(key)
            for key in ("state", "run_id", "config_hash", "network", "job_image_id")
        },
        "runner": {key: runner.get(key) for key in ("id", "name", "image_id")},
        "daemon": {key: daemon.get(key) for key in ("container_id", "image_id")},
        "readiness": {
            key: readiness.get(key) for key in ("head_sha", "status_count", "state", "checked_at")
        },
        "commit_statuses": statuses,
    }


def _public_file(relative: Path) -> bool:
    # Spec-0083/T3: private scorer inputs/reports never re-enter an experiment archive.
    if relative.parts[0] == "assessment" and relative.name == "bundle.json":
        return False
    if relative.parts[0] == "evaluation":
        return False
    if relative.parts[0] == "infrastructure" or relative.as_posix() == "logs/collector.log":
        return False
    if (
        relative.parts[0] == "runtime"
        and len(relative.parts) > 1
        and relative.parts[1]
        in {"image-build", "vigil-config", "collection.json", "task-environments"}
    ):
        return False
    return not any(part in _EXCLUDED for part in relative.parts) and not any(
        part == ".env"
        or (
            part.startswith(".env.")
            and not (i == len(relative.parts) - 1 and part == ".env.example")
        )
        or part.endswith(".env")
        or part.endswith(".lock")
        and part != "requirements.lock"
        for i, part in enumerate(relative.parts)
    )


def management_evidence(
    *, run_dir: Path, source: Path, manifest: dict[str, Any], terminal: bool
) -> dict[str, Any]:
    """Spec-0081/T4: archive private service records separately from role-visible evidence."""
    import gzip
    import io
    import os

    registry = source / "runtime/task-environments"
    if not registry.exists():
        return {"applicable": False, "complete": True}
    if registry.is_symlink() or not registry.is_dir():
        raise ConfigError("Invalid private task environment registry")
    contents: dict[str, bytes] = {}
    attempts = []
    complete = terminal
    for path in sorted(registry.glob("*.json")):
        if path.is_symlink() or not re.fullmatch(r"[a-f0-9]{64}\.json", path.name):
            raise ConfigError("Invalid private task environment record")
        body = path.read_bytes()
        record = json.loads(body)
        identity = record["identity"]
        if any(identity.get(key) != manifest[key] for key in ("run_id", "config_hash")):
            raise ConfigError("Private task evidence belongs to another run")
        key = path.stem
        identity_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if record.get("key") != key or identity_hash != key:
            raise ConfigError("Private task evidence filename differs from its identity")
        contents["task-environments/" + path.name] = body
        frozen = bool(record.get("frozen_at")) and record["phase"] in {
            "frozen",
            "stopped",
            "closed",
        }
        outputs = record.get("management_outputs", {})
        required = {
            output["handle"]
            for service in record["environment"]["services"]
            for output in service["exports"]
            if output["visibility"] == "management"
        }
        captured = set()
        missing_collected = False
        for handle, row in outputs.items():
            if row.get("status") != "collected":
                continue
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", handle):
                raise ConfigError("Invalid private task output handle")
            raw = registry / key / (handle + ".data")
            if raw.is_symlink() or not raw.is_file():
                missing_collected = True
                continue
            data = raw.read_bytes()
            if hashlib.sha256(data).hexdigest() != row.get("sha256") or len(data) != row.get(
                "bytes"
            ):
                raise ConfigError("Private task output checksum differs")
            contents["task-environments/" + key + "/" + handle + ".data"] = data
            captured.add(handle)
        sealed = frozen and required <= captured and not missing_collected
        complete = complete and sealed
        attempts.append(
            {
                "environment_key": key,
                "identity": identity,
                "phase": record["phase"],
                "frozen": frozen,
                "management_exports_required": len(required),
                "management_exports_collected": len(required & captured),
                "complete": sealed,
                "before_actor": not record.get("ready_at")
                and not record.get("finalization_error")
                and not outputs,
            }
        )
    # A failed initializer cannot produce user feedback. A later sealed attempt
    # for exactly the same binding is explicit recovery evidence; finalization
    # failures after readiness still require retained measurements or discard.
    binding_fields = (
        "run_id",
        "config_hash",
        "task_id",
        "task_digest",
        "recipe_hash",
        "session_id",
        "round_no",
        "slot",
    )
    for attempt in attempts:
        if attempt["complete"] or not attempt["before_actor"]:
            continue
        successors = [
            other
            for other in attempts
            if other["complete"]
            and all(
                other["identity"].get(field) == attempt["identity"].get(field)
                for field in binding_fields
            )
            and other["identity"]["attempt"] > attempt["identity"]["attempt"]
        ]
        if successors:
            successor = min(successors, key=lambda row: row["identity"]["attempt"])
            attempt.update(
                complete=True,
                outcome="superseded_before_actor",
                superseded_by=successor["environment_key"],
            )
    complete = terminal and all(attempt["complete"] for attempt in attempts)
    if not attempts:
        return {"applicable": False, "complete": True}
    public = {"version": 1, "attempts": attempts, "complete": complete}
    public_path = run_dir / "runtime/task-environments-public.json"
    public_path.parent.mkdir(exist_ok=True)
    public_path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n")
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    private_manifest = {
        "version": 1,
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "complete": complete,
        "files": inventory,
    }
    contents["management-evidence.json"] = (
        json.dumps(private_manifest, sort_keys=True, indent=2) + "\n"
    ).encode()
    archive_root = run_dir / "archive"
    archive_root.mkdir(exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".management-", suffix=".tar.gz", dir=archive_root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w") as archive:
                    for relative, body in sorted(contents.items()):
                        row = tarfile.TarInfo(relative)
                        row.size, row.mode = len(body), 0o600
                        archive.addfile(row, io.BytesIO(body))
        digest = sha256_file(temporary)
        destination = archive_root / ("management-evidence-" + digest + ".tar.gz")
        if destination.exists():
            if destination.is_symlink() or sha256_file(destination) != digest:
                raise ConfigError("Retained management evidence archive differs")
            temporary.unlink()
        else:
            temporary.replace(destination)
        destination.chmod(0o600)
        return {
            "applicable": True,
            "complete": complete,
            "path": destination.relative_to(run_dir).as_posix(),
            "sha256": digest,
            "files": inventory,
            "public_path": "runtime/task-environments-public.json",
        }
    finally:
        temporary.unlink(missing_ok=True)


def verify_management_evidence(*, run_dir: Path, receipt: dict[str, Any]) -> None:
    """Refuse destruction after losing a previously collected private sidecar."""
    evidence = receipt.get("management_evidence", {})
    if evidence.get("applicable") is not True:
        return
    relative = Path(evidence.get("path", ""))
    path = run_dir / relative
    if (
        evidence.get("complete") is not True
        or relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) != 2
        or relative.parts[0] != "archive"
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != evidence.get("sha256")
    ):
        raise ConfigError(
            "Collect and retain verified private task evidence before destroying compute"
        )


def collect_archive(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    snapshot: dict[str, Any],
    credentials: dict[str, str],
) -> dict[str, Any]:
    """COMPLETE describes a quiescent archive, never the experiment outcome.

    Provider observations before/after copying govern consistency. Host materials
    and the original immutable manifest accompany each portable archive.
    """
    source = Path(snapshot["snapshot_dir"]).resolve()
    if not source.is_dir():
        raise ConfigError("Provider did not produce a collection snapshot")
    archive_root = run_dir / "archive"
    archive_root.mkdir(exist_ok=True)
    sensitive = [
        v.encode()
        for k, v in credentials.items()
        if len(v) >= 8 and any(t in k for t in ("KEY", "TOKEN", "PASSWORD"))
    ]
    expected = snapshot.get("files", {})
    private = management_evidence(
        run_dir=run_dir, source=source, manifest=manifest, terminal=bool(snapshot.get("terminal"))
    )
    consistent = bool(snapshot.get("consistent")) and private["complete"]
    with tempfile.TemporaryDirectory(prefix="collection-stage-", dir=run_dir / "runtime") as tmp:
        stage = Path(tmp)
        files: dict[str, str] = {}
        public_projections: dict[str, dict[str, str]] = {}

        def copy(path: Path, relative: Path) -> None:
            nonlocal consistent
            if path.is_symlink() or not path.is_file():
                return
            before = sha256_file(path)
            dest = stage / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Model trajectories can echo credentials. Never copy them verbatim
            # when an explicitly supplied provider secret appears in their bytes.
            data = path.read_bytes()
            for value in sensitive:
                data = data.replace(value, b"[REDACTED]")
            dest.write_bytes(data)
            after = sha256_file(path)
            if before != after:
                consistent = False
            raw_relative = (
                path.relative_to(source).as_posix() if path.is_relative_to(source) else None
            )
            if raw_relative in expected and expected[raw_relative] != after:
                consistent = False
            archived_hash = hashlib.sha256(data).hexdigest()
            files[relative.as_posix()] = archived_hash
            if before != archived_hash:
                # Spec-0079/T2: preserve the projection's provenance without secret values.
                public_projections[relative.as_posix()] = {
                    "original_sha256": before,
                    "archive_sha256": archived_hash,
                    "reason": "credential_redaction",
                }

        for path in list(source.rglob("*")):
            relative = path.relative_to(source)
            if _public_file(relative) and not path.is_relative_to(stage):
                copy(path, relative)
        copy(run_dir / "manifest.json", Path("manifest.json"))
        for record in manifest["materials"].values():
            relative = Path(record["path"])
            if not relative.is_relative_to("materials"):
                raise ConfigError("Frozen input lies outside materials directory")
            copy(run_dir / relative, relative)
        evidence = run_dir / "runtime/gitea-evidence.json"
        if evidence.is_file() and not evidence.is_relative_to(source):
            copy(evidence, Path("runtime/gitea-evidence.json"))
        if private.get("applicable"):
            copy(run_dir / private["public_path"], Path(private["public_path"]))
        if not snapshot.get("gitea_evidence", {}).get("complete", True):
            consistent = False
        state = "COMPLETE" if snapshot.get("terminal") and consistent else "PARTIAL"
        receipt = {
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "collection_state": state,
            "consistent": consistent,
            "terminal": bool(snapshot.get("terminal")),
            "controller": snapshot.get("controller"),
            "collected_at": datetime.now(UTC).isoformat(),
            "files": files,
            "public_projections": public_projections,
            "continuation_ready": state == "COMPLETE"
            and _continuation_ready(
                stage=stage, manifest=manifest, controller=snapshot.get("controller")
            ),
        }
        if private.get("applicable"):
            receipt["management_evidence"] = private
        (stage / "collection.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        temporary = archive_root / ".artifacts.tar.gz.tmp"
        with tarfile.open(temporary, "w:gz") as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(stage).as_posix(), recursive=False)
        destination = archive_root / "artifacts.tar.gz"
        temporary.replace(destination)
        receipt["archive"] = str(destination)
        receipt["archive_sha256"] = sha256_file(destination)
        (archive_root / "collection.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )
        shutil.copy2(archive_root / "collection.json", run_dir / "runtime/collection.json")
        return receipt


def _continuation_ready(*, stage: Path, manifest: dict, controller: Any) -> bool:
    """Spec-0079/T2: code inputs must remain exact; completeness alone is insufficient."""
    from auto_designer.experiment.continuation.export import EXPORT_PATH

    if not isinstance(controller, dict) or controller.get("experiment_complete") is not True:
        return False
    try:
        export = json.loads((stage / EXPORT_PATH).read_text())
        identity = {
            key: manifest[key]
            for key in ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash")
        }
        if export.get("status") != "ready" or export["identity"] != identity:
            return False
        harness = export["harness"]
        if sha256_file(stage / harness["archive"]) != harness["sha256"]:
            return False
        # Registry inputs include task code/persona/controller inputs. A redacted
        # trajectory is evidence; redacted executable input cannot seed a child.
        return all(
            sha256_file(stage / record["path"]) == record["sha256"]
            for record in manifest["materials"].values()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
