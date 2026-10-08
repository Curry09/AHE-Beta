"""Read and validate current collect archives without executing their contents."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from auto_designer.demand.issue_schema import REPORT, plane
from auto_designer.experiment.config import ConfigError, config_hash, validate_schema
from auto_designer.experiment.workload import catalog_tasks, compile_session_plan

EXPORT_PATH = "runtime/continuation-export.json"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 100_000
_SHA256 = re.compile(r"[a-f0-9]{64}")
_IDENTITY = ("run_id", "experiment_id", "config_hash", "controller_sha", "plan_hash")


@dataclass(frozen=True)
class ContinuationSource:
    """Validated immutable-input view; callers freeze selected bytes into a new run."""

    archive_sha256: str
    manifest: dict[str, Any]
    collection: dict[str, Any]
    recovery: dict[str, Any]
    export: dict[str, Any]
    files: dict[str, bytes]
    selected_sessions: list[dict[str, Any]]
    pairs: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    personas: list[dict[str, Any]]
    reports: list[dict[str, Any]]

    def read(self, path: str) -> bytes:
        try:
            return self.files[_safe_path(path)]
        except KeyError as exc:
            raise ConfigError(f"Continuation archive file missing: {path}") from exc

    def summary(self) -> dict[str, Any]:
        boundary = self.export["boundary"]
        return {
            "parent_identity": dict(self.export["identity"]),
            "parent_archive_sha256": self.archive_sha256,
            "base_round": boundary["lineage_round"],
            "parent_local_round": boundary["local_round"],
            "parent_user_sha": boundary["user_sha"],
            "parent_tree_id": self.export["harness"]["tree_id"],
            "sessions": len(self.selected_sessions),
            "reports": len(self.reports),
            "pending_reports": sum(
                report["state"] == "open"
                and plane(report["labels"]) == REPORT
                and not set(report["labels"]).intersection(
                    {
                        "declined",
                        "merged",
                        "rejected",
                        "needs-info",
                        "gate-dropped",
                        "superseded",
                        "delivered",
                        "openagents/ready",
                        "owner-rejected",
                    }
                )
                for report in self.reports
            ),
            "pairs": self.pairs,
            "task_ids": [task["id"] for task in self.tasks],
            "persona_ids": [card["id"] for card in self.personas],
            "continuation_ready": True,
            "gaps": [
                {
                    "session_id": session["session_id"],
                    "kind": "native_observation",
                    "reason": session["observation_reason"],
                }
                for session in self.selected_sessions
                if session.get("observation_status") == "unavailable"
            ],
        }


def _safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ConfigError("Invalid continuation archive path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ConfigError(f"Unsafe continuation archive path: {value}")
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, label: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigError(f"Duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise ConfigError(f"Invalid continuation JSON: {label}") from exc


def _read_tar(stream: Any, *, mode: str) -> dict[str, bytes]:
    files = {}
    total = 0
    try:
        with tarfile.open(fileobj=stream, mode=mode) as archive:
            for member in archive:
                name = _safe_path(member.name)
                if name in files or not member.isfile() or member.size > MAX_MEMBER_BYTES:
                    raise ConfigError(f"Invalid/duplicate continuation member: {name}")
                total += member.size
                if total > MAX_ARCHIVE_BYTES or len(files) >= MAX_MEMBERS:
                    raise ConfigError("Continuation archive exceeds expansion budget")
                handle = archive.extractfile(member)
                if handle is None:
                    raise ConfigError(f"Unreadable continuation member: {name}")
                with handle:
                    files[name] = handle.read(member.size + 1)
                if len(files[name]) != member.size:
                    raise ConfigError(f"Truncated continuation member: {name}")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ConfigError("Invalid gzip continuation archive") from exc
    return files


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _match_file(
    files: dict[str, bytes], collection: dict, path: str, expected: str, *, evidence: bool = False
) -> bytes:
    name = _safe_path(path)
    _require(name in files, f"Continuation file missing: {name}")
    data = files[name]
    actual = _digest(data)
    if actual != expected:
        projection = collection.get("public_projections", {}).get(name, {})
        _require(
            evidence
            and projection.get("original_sha256") == expected
            and projection.get("archive_sha256") == actual
            and projection.get("reason") == "credential_redaction",
            f"Continuation original content hash mismatch: {name}",
        )
    return data


def _git_object(kind: str, data: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest()


def git_tree_id(files: dict[str, bytes], inventory: dict[str, dict]) -> str:
    """Calculate the SHA-1 Git tree directly, without filters or archived Git config."""
    tree: dict[str, Any] = {}
    for path, data in files.items():
        parts = _safe_path(path).split("/")
        current = tree
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            _require(isinstance(child, dict), "Harness file/directory path collision")
            current = child
        _require(parts[-1] not in current, "Harness file/directory path collision")
        current[parts[-1]] = (inventory[path]["mode"], _git_object("blob", data))

    def encode(node):
        entries = []
        for name, value in node.items():
            raw = name.encode("utf-8")
            if isinstance(value, dict):
                mode, oid, key = "40000", encode(value), raw + b"/"
            else:
                mode, oid = value
                key = raw
            entries.append((key, mode.encode() + b" " + raw + b"\0" + bytes.fromhex(oid)))
        return _git_object("tree", b"".join(value for _, value in sorted(entries)))

    return encode(tree)


def _validate_harness(files: dict[str, bytes], collection: dict, exported: dict) -> None:
    harness = exported["harness"]
    payload = _match_file(files, collection, harness["archive"], harness["sha256"])
    source = _read_tar(io.BytesIO(payload), mode="r:gz")
    inventory = harness["files"]
    _require(set(source) == set(inventory), "Harness tracked inventory differs from export")
    for path, data in source.items():
        _require(
            not any(
                part == ".git"
                or part == ".env"
                or part.startswith(".env.")
                and part != ".env.example"
                for part in PurePosixPath(path).parts
            ),
            "Private path in continuation Harness",
        )
        record = inventory[path]
        _require(
            _digest(data) == record["sha256"]
            and len(data) == record["size_bytes"]
            and _git_object("blob", data) == record["blob_oid"],
            f"Harness blob differs from export: {path}",
        )
    _require(
        git_tree_id(source, inventory) == harness["tree_id"], "Harness tree differs from export"
    )


def _material(files: dict[str, bytes], collection: dict, manifest: dict, key: str) -> bytes:
    record = manifest["materials"][key]
    path = _safe_path(record["path"])
    _require(path.startswith("materials/"), "Parent frozen material lies outside materials")
    return _match_file(files, collection, path, record["sha256"])


def _validate_materials(files, collection, manifest, exported):
    registry = manifest["materials"]
    for key in registry:
        _material(files, collection, manifest, key)
    catalog = _json(_material(files, collection, manifest, "task_catalog"), "task catalog")
    plan = _json(_material(files, collection, manifest, "session_plan"), "session plan")
    _require(
        registry["task_catalog"]["sha256"] == manifest["catalog_hash"], "Catalog identity differs"
    )
    _require(registry["session_plan"]["sha256"] == manifest["plan_hash"], "Plan identity differs")
    tasks = catalog_tasks(catalog)
    inherited_pairs = None
    if manifest["config"]["workload"].get("source") == "parent":
        inherited = _json(
            _material(files, collection, manifest, "continuation_input"), "inherited input"
        )
        inherited_pairs = inherited["pairs"]
    expected = compile_session_plan(
        manifest["config"], catalog, manifest["catalog_hash"], inherited_pairs
    )
    _require(
        config_hash(data=plan) == config_hash(data=expected),
        "Frozen parent session plan differs from configuration",
    )
    _require(
        len(set(exported["material_keys"])) == len(exported["material_keys"]),
        "Duplicate exported material key",
    )
    _require(set(exported["material_keys"]) <= set(registry), "Export references unknown material")
    for task in tasks:
        package = _json(
            _material(files, collection, manifest, task["materials"]["package"]), "task package"
        )
        _require(package == task["package"], "Task package differs from catalog")
        for name, digest in task["content_hashes"].items():
            _require(
                _digest(_material(files, collection, manifest, task["materials"][name])) == digest,
                "Task content differs",
            )
        payload = _material(files, collection, manifest, task["materials"]["source_archive"])
        source = _read_tar(io.BytesIO(payload), mode="r:gz")
        _require(
            {path: _digest(data) for path, data in source.items()}
            == task["source_snapshot"]["files"],
            "Task source inventory differs",
        )
    cards = _json(_material(files, collection, manifest, "persona_library"), "persona library")
    roster = _json(_material(files, collection, manifest, "persona_roster"), "persona roster")
    by_persona = {card["id"]: card for card in cards}
    _require(len(by_persona) == len(cards), "Duplicate frozen persona")
    for entry in roster["personas"]:
        _require(
            entry["strategy"]
            == by_persona[entry["id"]]["dimensions"]["D3_interaction_style"]["on_offtrack"][
                "value"
            ],
            "Persona strategy differs from card",
        )
    return tasks, by_persona, plan


def _validate_observation(files, collection, selected, user_sha):
    prefix = selected.get("observation_path")
    if prefix is None:
        return
    prefix = _safe_path(prefix)
    document = _json(files[prefix + "/manifest.json"], "observation manifest")
    _require(
        document["session_id"] == selected["session_id"], "Observation session identity differs"
    )
    projections = collection.get("public_projections", {})

    def verify_manifest(value, base):
        entries = value["files"]
        _require(
            len({entry["path"] for entry in entries}) == len(entries), "Duplicate observation entry"
        )
        for entry in entries:
            path = base + "/" + _safe_path(entry["path"])
            _require(path not in projections, "Native observation bytes were redacted")
            data = _match_file(files, collection, path, entry["sha256"])
            _require(len(data) == entry["bytes"], "Observation byte count differs")

    _require(
        prefix + "/manifest.json" not in projections, "Native observation manifest was redacted"
    )
    verify_manifest(document, prefix)
    for run in document["runs"]:
        path = prefix + "/" + _safe_path(run["manifest"])
        value = _json(files[path], "observation run manifest")
        _require(
            value["session_id"] == selected["session_id"]
            and value["run_id"] == run["run_id"]
            and value["artifact"]["harness_sha"] == user_sha,
            "Observation native provenance differs",
        )
        verify_manifest(value, path.rsplit("/", 1)[0])


def _validate_completion(files, collection, manifest, exported):
    identity = {key: manifest[key] for key in _IDENTITY}
    _require(exported["identity"] == identity, "Continuation export identity differs from manifest")
    _require(
        config_hash(data=manifest["config"]) == manifest["config_hash"],
        "Parent config hash differs",
    )
    controller = collection.get("controller") or {}
    count = manifest["config"]["rounds"]["count"]
    _require(
        collection.get("collection_state") == "COMPLETE"
        and collection.get("consistent") is True
        and collection.get("terminal") is True
        and collection.get("continuation_ready") is True
        and collection.get("run_id") == identity["run_id"]
        and collection.get("config_hash") == identity["config_hash"]
        and controller.get("experiment_complete") is True
        and controller.get("exit_code") == 0
        and controller.get("running") is False
        and controller.get("stopped_by_user") is False
        and controller.get("nonce")
        and controller.get("expected_rounds") == count
        and controller.get("sealed_rounds") == list(range(1, count + 1)),
        "Parent collection is not a complete, successful continuation source",
    )
    recovery = _json(files["checkpoints/recovery.json"], "recovery")
    _require(
        recovery.get("schema_version") == 1 and recovery.get("identity") == identity,
        "Parent recovery identity differs",
    )
    invocation = _json(files[f"data/role_runs/{identity['run_id']}/manifest.json"], "invocation")
    rows = invocation.get("rounds", [])
    _require(invocation.get("run_id") == identity["run_id"], "Parent invocation identity differs")
    _require(
        len(rows) == count and {row["round"] for row in rows} == set(range(1, count + 1)),
        "Parent invocation rounds differ",
    )
    for row in rows:
        saved = recovery["rounds"][str(row["round"])]
        _require(
            saved["status"] == "completed"
            and saved["sealed_sha"] == row["sealed_sha"]
            and row["user_sha"] == saved["user_sha"],
            "Invocation/recovery Harness identity differs",
        )
    boundary = exported["boundary"]
    last = recovery["rounds"][str(count)]
    _require(
        boundary["local_round"] == count
        and last["user_sha"]
        == last["sealed_sha"]
        == boundary["user_sha"]
        == boundary["sealed_sha"]
        == exported["harness"]["commit"],
        "Parent last users-only boundary differs",
    )
    base = (manifest.get("lineage") or {}).get("base_round", 0)
    _require(boundary["lineage_round"] == base + count, "Parent lineage round differs")
    if manifest["config"].get("continuation"):
        bootstrap = _json(
            files["checkpoints/continuation-bootstrap/recovery.json"], "bootstrap recovery"
        )
        boot = bootstrap["rounds"]["1"]
        input_record = manifest["materials"]["continuation_input"]
        bootstrap_identity = {**identity, "plan_hash": input_record["sha256"]}
        receipt = _json(files["runtime/continuation-bootstrap.json"], "bootstrap receipt")
        inherited = _json(files[input_record["path"]], "bootstrap input")
        mapping = _json(files["runtime/continuation-issue-map.json"], "bootstrap issue map")
        _require(
            bootstrap["identity"] == bootstrap_identity
            and receipt["identity"] == bootstrap_identity
            and receipt["status"] == "completed"
            and receipt["input_sha256"] == input_record["sha256"]
            and boot["status"] == "completed"
            and boot["sealed_sha"] == recovery["rounds"]["1"]["user_sha"] == receipt["sealed_sha"]
            and receipt["issue_map_sha256"] == _digest(files["runtime/continuation-issue-map.json"])
            and mapping["complete"] is True
            and mapping["identity"]
            == {
                "child": bootstrap_identity,
                "parent": inherited["export"]["identity"],
                "child_seed": boot["user_sha"],
                "parent_archive_sha256": manifest["lineage"]["parent_archive_sha256"],
            }
            and mapping["source_digest"] == config_hash(data=inherited["export"]["reports"])
            and mapping["map_hash"] == config_hash(data=mapping["issue_map"]),
            "Parent continuation bootstrap is incomplete or differs",
        )
    return recovery, last


def load_continuation_source(*, archive: str | Path, sha256: str) -> ContinuationSource:
    """Fail closed on unsupported, incomplete or inconsistent current archives."""
    _require(
        isinstance(sha256, str) and _SHA256.fullmatch(sha256) is not None,
        "Invalid parent archive SHA256",
    )
    path = Path(archive)
    _require(path.is_file() and not path.is_symlink(), "Parent archive must be a regular file")
    _require(path.stat().st_size <= MAX_ARCHIVE_BYTES, "Parent archive exceeds size budget")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
        _require(actual == sha256, "Parent archive SHA256 mismatch")
        handle.seek(0)
        files = _read_tar(handle, mode="r:gz")
        handle.seek(0)
        _require(
            hashlib.file_digest(handle, "sha256").hexdigest() == actual,
            "Parent archive changed while reading",
        )
    try:
        manifest = _json(files["manifest.json"], "manifest")
        collection = _json(files["collection.json"], "collection")
        _require(
            type(manifest.get("schema_version")) is int
            and manifest["schema_version"] == 2
            and type(manifest.get("workload_contract_version")) is int
            and manifest["workload_contract_version"] == 1,
            "Unsupported parent archive contract",
        )
        _require(
            EXPORT_PATH in files, "Parent archive lacks current continuation export; unsupported"
        )
        exported = _json(files[EXPORT_PATH], "continuation export")
        validate_schema(document=exported, schema_name="continuation-export-v1.json")
        _require(exported["status"] == "ready", "Parent continuation export is unavailable")
        listing = collection["files"]
        _require(
            set(listing) == set(files) - {"collection.json"}, "Parent collection inventory differs"
        )
        for name, expected in listing.items():
            _require(
                _digest(files[_safe_path(name)]) == expected,
                f"Parent collected file hash mismatch: {name}",
            )
        for name, projection in collection.get("public_projections", {}).items():
            _require(
                name in listing
                and _SHA256.fullmatch(projection["original_sha256"]) is not None
                and projection["archive_sha256"] == listing[name]
                and projection["reason"] == "credential_redaction",
                "Invalid credential redaction projection",
            )
        recovery, last = _validate_completion(files, collection, manifest, exported)
        tasks, by_persona, plan = _validate_materials(files, collection, manifest, exported)
        expected_pairs = plan["rounds"][-1]
        _require(last["plan"] == expected_pairs, "Parent recovery plan differs from frozen plan")
        selections = exported["boundary"]["sessions"]
        _require(
            [selection["binding"] for selection in selections] == expected_pairs,
            "Exported parent pairings differ from frozen plan",
        )
        users = last["stages"]["users"]
        _require(
            users["status"] == "completed"
            and last["stages"]["round_sealed"]["status"] == "completed",
            "Parent final users/seal are incomplete",
        )
        _require(
            len({row["session_id"] for row in selections}) == len(selections)
            and set(users["units"]) == {row["session_id"] for row in selections},
            "Parent selected users differ from recovery units",
        )
        sessions = []
        for selected in selections:
            sid = selected["session_id"]
            unit = users["units"][sid]
            binding = selected["binding"]
            _require(
                unit["status"] == "completed"
                and unit["input"]["binding"] == binding
                and unit["input"]["user_sha"] == last["user_sha"]
                and unit["observed_postconditions"]["session_id"] == sid,
                "Parent user receipt binding differs",
            )
            _require(
                config_hash(data=unit["input"]) == unit["input_digest"],
                "Parent user input digest differs",
            )
            receipt_path = "checkpoints/" + _safe_path(unit["output_artifact"])
            receipt = _json(files[receipt_path], "user recovery receipt")
            projected_receipt = receipt_path in collection.get("public_projections", {})
            _require(
                receipt["schema_version"] == 1
                and receipt["operation_key"] == sid
                and receipt["stage"] == "users"
                and receipt["round"] == binding["round_no"]
                and receipt["input_digest"] == unit["input_digest"]
                and receipt["output_digest"] == unit["output_digest"]
                and (
                    config_hash(data=receipt["output"]) == unit["output_digest"]
                    or projected_receipt
                ),
                "Parent user recovery receipt differs",
            )
            session = _json(
                _match_file(files, collection, selected["path"], selected["sha256"], evidence=True),
                "session",
            )
            provenance = session.get("session_provenance") or {}
            _require(
                session["session_id"] == sid
                and provenance.get("contract_version") == 1
                and provenance.get("run_id") == manifest["run_id"]
                and provenance.get("harness_sha") == last["user_sha"]
                and all(provenance.get(key) == value for key, value in binding.items()),
                "Parent session provenance differs",
            )
            _require(
                receipt["output"]["session_id"] == sid
                and receipt["output"]["session_provenance"] == provenance,
                "Parent session differs from completed user receipt",
            )
            _require(
                config_hash(data=by_persona[binding["persona_id"]]) == selected["persona_sha256"],
                "Parent persona card digest differs",
            )
            if selected.get("observation_path"):
                _safe_path(selected["observation_path"])
            try:
                if not selected.get("observation_path"):
                    raise ConfigError("No native parent observation")
                _validate_observation(files, collection, selected, last["user_sha"])
                session["observation_status"] = "available"
            except (ConfigError, KeyError, ValueError, TypeError):
                session["observation_status"] = "unavailable"
                session["observation_reason"] = "Native parent bytes not verified"
            sessions.append(session)
        _validate_harness(files, collection, exported)
        forge = _json(
            _match_file(
                files,
                collection,
                exported["forge"]["path"],
                exported["forge"]["sha256"],
                evidence=True,
            ),
            "forge evidence",
        )
        _require(
            forge.get("terminal") is True
            and forge.get("controller_nonce") == collection["controller"]["nonce"],
            "Parent forge capture identity differs",
        )
        reports = exported["reports"]
        _require(len({row["number"] for row in reports}) == len(reports), "Duplicate parent report")
        issues = {row["number"]: row for row in forge["issues"]}
        _require(len(issues) == len(forge["issues"]), "Duplicate forge issue identity")
        all_refs = {ref["number"] for session in sessions for ref in session.get("issue_refs", [])}
        for number in all_refs:
            _require(number in issues, "Parent feedback references missing forge issue")
        report_refs = {
            number
            for number in all_refs
            if plane(
                [
                    label["name"] if isinstance(label, dict) else label
                    for label in issues[number]["labels"]
                ]
            )
            == REPORT
        }
        _require(
            {row["number"] for row in reports} == report_refs,
            "Parent reports do not match selected feedback references",
        )
        for report in reports:
            body = {key: value for key, value in report.items() if key != "sha256"}
            _require(
                config_hash(data=body) == report["sha256"]
                or EXPORT_PATH in collection.get("public_projections", {}),
                "Parent report hash differs",
            )
            issue = issues[report["number"]]
            labels = [
                label["name"] if isinstance(label, dict) else label for label in issue["labels"]
            ]
            _require(
                all(
                    report[key] == (issue.get(key) or "" if key == "body" else issue[key])
                    for key in ("title", "body", "state")
                )
                and report["labels"] == labels
                and report["url"] == issue.get("html_url", issue.get("url", "")),
                "Parent report differs from forge evidence",
            )
            expected_sids = sorted(
                {
                    session["session_id"]
                    for session in sessions
                    if any(
                        ref["number"] == report["number"] for ref in session.get("issue_refs", [])
                    )
                }
            )
            _require(
                report["session_ids"] == expected_sids, "Parent report session association differs"
            )
        chosen_tasks = list(dict.fromkeys(pair["task_id"] for pair in expected_pairs))
        chosen_personas = list(dict.fromkeys(pair["persona_id"] for pair in expected_pairs))
        required_materials = {"task_catalog", "session_plan", "persona_library", "persona_roster"}
        for task in tasks:
            if task["id"] in chosen_tasks:
                required_materials.update(task["materials"].values())
        _require(
            required_materials <= set(exported["material_keys"]),
            "Export omits selected frozen materials",
        )
        return ContinuationSource(
            actual,
            manifest,
            collection,
            recovery,
            exported,
            files,
            sessions,
            expected_pairs,
            [
                next(task for task in tasks if task["id"] == identifier)
                for identifier in chosen_tasks
            ],
            [by_persona[identifier] for identifier in chosen_personas],
            reports,
        )
    except (KeyError, TypeError, IndexError, StopIteration) as exc:
        raise ConfigError("Incomplete current continuation archive") from exc
