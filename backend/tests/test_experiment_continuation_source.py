"""Current continuation sources preserve bindings and reject ambiguous evidence."""

import hashlib
import io
import json
import tarfile

import pytest

from ahe_beta.experiment.config import ConfigError, config_hash
from ahe_beta.experiment.continuation import source
from ahe_beta.experiment.workload import compile_session_plan, task_digest


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def packed(files, extra=None):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        if extra is not None:
            archive.addfile(extra)
    return out.getvalue()


@pytest.fixture
def parent_files():
    files = {}
    registry = {}

    def material(key, path, data):
        files[path] = data
        registry[key] = {"path": path, "sha256": digest(data), "size_bytes": len(data)}
        return key

    package = {
        "id": "task",
        "kind": "ordinary",
        "interaction": "direct",
        "source": {"kind": "local", "path": "source/tasks/task"},
    }
    refs = {}
    hashes = {}
    for name in ("instruction", "script", "requirements_lock"):
        value = (name + "\n").encode()
        refs[name] = material(name, f"materials/tasks/task/{name}", value)
        hashes[name] = digest(value)
    refs["source_archive"] = material(
        "source_archive", "materials/tasks/task/source.tar.gz", packed({"run.py": b"print(1)\n"})
    )
    refs["package"] = material("package", "materials/tasks/task/package.json", encoded(package))
    task = {
        "id": "task",
        "kind": "ordinary",
        "interaction": "direct",
        "package": package,
        "source_snapshot": {"revision": None, "files": {"run.py": digest(b"print(1)\n")}},
        "content_hashes": hashes,
        "materials": refs,
    }
    task["digest"] = task_digest(task)
    catalog = {"contract_version": 1, "tasks": [task]}
    material("task_catalog", "materials/task-catalog.json", encoded(catalog))
    config = {
        "schema_version": 2,
        "rounds": {"count": 1, "sessions_per_round": 1},
        "workload": {"persona_ids": ["persona"]},
    }
    plan = compile_session_plan(config, catalog, registry["task_catalog"]["sha256"])
    material("session_plan", "materials/session-plan.json", encoded(plan))
    card = {
        "id": "persona",
        "dimensions": {"D3_interaction_style": {"on_offtrack": {"value": "correct"}}},
    }
    material("persona_library", "materials/persona_library.json", encoded([card]))
    material(
        "persona_roster",
        "materials/persona_roster.json",
        encoded({"personas": [{"id": "persona", "strategy": "correct"}]}),
    )
    commit = "1" * 40
    identity = {
        "run_id": "child",
        "experiment_id": "child",
        "config_hash": config_hash(data=config),
        "controller_sha": "2" * 40,
        "plan_hash": registry["session_plan"]["sha256"],
    }
    manifest = {
        **identity,
        "schema_version": 2,
        "workload_contract_version": 1,
        "config": config,
        "materials": registry,
        "catalog_hash": registry["task_catalog"]["sha256"],
    }
    binding = plan["rounds"][0][0]
    sid = "op-session"
    session = {
        "session_id": sid,
        "session_provenance": {
            "contract_version": 1,
            "run_id": "child",
            "harness_sha": commit,
            "task_kind": "ordinary",
            **binding,
        },
        "issue_refs": [],
        "transcript": [],
        "accept_validity": "unverified_accept",
        "objective_evaluation": {"status": "skipped"},
    }
    session_path = f"data/role_runs/child/sessions/{sid}.json"
    files[session_path] = encoded(session)
    unit = {
        "status": "completed",
        "input": {"binding": binding, "user_sha": commit},
        "observed_postconditions": {"completed": True, "session_id": sid},
    }
    unit.update(
        input_digest=config_hash(data=unit["input"]),
        output_digest=config_hash(data=session),
        output_artifact=f"recovery-receipts/1/users/{sid}.json",
    )
    files["checkpoints/" + unit["output_artifact"]] = encoded(
        {
            "schema_version": 1,
            "operation_key": sid,
            "stage": "users",
            "round": 1,
            "input_digest": unit["input_digest"],
            "output_digest": unit["output_digest"],
            "output": session,
        }
    )
    last = {
        "status": "completed",
        "plan": [binding],
        "user_sha": commit,
        "sealed_sha": commit,
        "stages": {
            "users": {"status": "completed", "units": {sid: unit}},
            "round_sealed": {"status": "completed"},
        },
    }
    files["checkpoints/recovery.json"] = encoded(
        {"schema_version": 1, "identity": identity, "rounds": {"1": last}}
    )
    files["data/role_runs/child/manifest.json"] = encoded(
        {"run_id": "child", "rounds": [{"round": 1, "user_sha": commit, "sealed_sha": commit}]}
    )
    harness_source = {
        ".gitignore": b"ignored.py\n",
        "ignored.py": b"tracked\n",
        "scripts/run": b"#!/bin/sh\n",
        "scripts-more": b"order\n",
    }
    inventory = {
        name: {
            "sha256": digest(data),
            "blob_oid": source._git_object("blob", data),
            "mode": "100755" if name == "scripts/run" else "100644",
            "size_bytes": len(data),
        }
        for name, data in harness_source.items()
    }
    harness_path = "runtime/continuation-harness.tar.gz"
    files[harness_path] = packed(harness_source)
    files["runtime/gitea-evidence.json"] = encoded(
        {
            "terminal": True,
            "controller_nonce": "nonce",
            "issues": [],
            "repository": {"id": 1, "full_name": "owner/repo"},
        }
    )
    export = {
        "schema_version": 1,
        "status": "ready",
        "identity": identity,
        "boundary": {
            "local_round": 1,
            "lineage_round": 1,
            "user_sha": commit,
            "sealed_sha": commit,
            "sessions": [
                {
                    "session_id": sid,
                    "path": session_path,
                    "sha256": digest(files[session_path]),
                    "binding": binding,
                    "persona_sha256": config_hash(data=card),
                }
            ],
        },
        "harness": {
            "commit": commit,
            "tree_id": source.git_tree_id(harness_source, inventory),
            "archive": harness_path,
            "sha256": digest(files[harness_path]),
            "files": inventory,
        },
        "material_keys": list(registry),
        "forge": {
            "path": "runtime/gitea-evidence.json",
            "sha256": digest(files["runtime/gitea-evidence.json"]),
        },
        "reports": [],
    }
    files[source.EXPORT_PATH] = encoded(export)
    files["manifest.json"] = encoded(manifest)
    return files


def archive(tmp_path, files, *, receipt_updates=None, extra=None):
    files = dict(files)
    manifest = json.loads(files["manifest.json"])
    receipt = {
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "collection_state": "COMPLETE",
        "consistent": True,
        "terminal": True,
        "continuation_ready": True,
        "controller": {
            "nonce": "nonce",
            "expected_rounds": 1,
            "sealed_rounds": [1],
            "experiment_complete": True,
            "exit_code": 0,
            "running": False,
            "stopped_by_user": False,
        },
        "files": {name: digest(data) for name, data in files.items()},
    }
    receipt.update(receipt_updates or {})
    files["collection.json"] = encoded(receipt)
    path = tmp_path / "artifacts.tar.gz"
    path.write_bytes(packed(files, extra))
    return path, digest(path.read_bytes())


def update(files, path, edit):
    value = json.loads(files[path])
    edit(value)
    files[path] = encoded(value)


def load(tmp_path, files, **kwargs):
    path, expected = archive(tmp_path, files, **kwargs)
    return source.load_continuation_source(archive=path, sha256=expected)


def test_complete_source_preserves_raw_input_and_invalid_score(parent_files, tmp_path):
    selected = load(tmp_path, parent_files)
    assert selected.pairs[0]["interaction"] == "direct"
    assert selected.tasks[0]["package"]["source"]["path"] == "source/tasks/task"
    assert selected.selected_sessions[0]["accept_validity"] == "unverified_accept"
    assert selected.selected_sessions[0]["objective_evaluation"]["status"] == "skipped"
    assert selected.read("materials/tasks/task/instruction") == b"instruction\n"
    assert selected.summary()["base_round"] == 1
    json.dumps(selected.summary())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda f: f.pop(source.EXPORT_PATH),
        lambda f: update(f, source.EXPORT_PATH, lambda e: e["identity"].update(run_id="other")),
        lambda f: update(
            f, source.EXPORT_PATH, lambda e: e["boundary"]["sessions"][0]["binding"].update(slot=9)
        ),
        lambda f: update(
            f,
            "checkpoints/recovery.json",
            lambda e: e["rounds"]["1"]["stages"]["users"]["units"]["op-session"].update(
                status="running"
            ),
        ),
        lambda f: update(
            f,
            "data/role_runs/child/sessions/op-session.json",
            lambda e: e["session_provenance"].update(harness_sha="3" * 40),
        ),
        lambda f: update(
            f,
            source.EXPORT_PATH,
            lambda e: e["harness"]["files"]["scripts/run"].update(mode="100644"),
        ),
        lambda f: update(f, source.EXPORT_PATH, lambda e: e["harness"].update(tree_id="4" * 40)),
        lambda f: update(f, source.EXPORT_PATH, lambda e: e["boundary"].update(lineage_round=2)),
        lambda f: update(
            f, "runtime/gitea-evidence.json", lambda e: e.update(controller_nonce="other")
        ),
    ],
)
def test_inconsistent_sources_fail_even_with_fresh_collection_hashes(
    parent_files, tmp_path, mutation
):
    mutation(parent_files)
    with pytest.raises(ConfigError):
        load(tmp_path, parent_files)


@pytest.mark.parametrize(
    "receipt",
    [
        {"collection_state": "PARTIAL"},
        {"continuation_ready": False},
        {"terminal": False},
        {"consistent": False},
    ],
)
def test_incomplete_collection_rejected(parent_files, tmp_path, receipt):
    with pytest.raises(ConfigError, match="complete"):
        load(tmp_path, parent_files, receipt_updates=receipt)


@pytest.mark.parametrize(
    "name,type_",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("runtime/link", tarfile.SYMTYPE),
        ("manifest.json", tarfile.REGTYPE),
    ],
)
def test_unsafe_and_duplicate_tar_members_rejected(parent_files, tmp_path, name, type_):
    entry = tarfile.TarInfo(name)
    entry.type = type_
    entry.linkname = "manifest.json" if type_ == tarfile.SYMTYPE else ""
    with pytest.raises(ConfigError):
        load(tmp_path, parent_files, extra=entry)


def test_bad_archive_digest_and_expansion_budget(parent_files, tmp_path, monkeypatch):
    path, expected = archive(tmp_path, parent_files)
    with pytest.raises(ConfigError, match="SHA256 mismatch"):
        source.load_continuation_source(archive=path, sha256="0" * 64)
    monkeypatch.setattr(source, "MAX_MEMBER_BYTES", 2)
    with pytest.raises(ConfigError, match="member"):
        source.load_continuation_source(archive=path, sha256=expected)


def test_session_redaction_is_explicit_and_material_redaction_is_rejected(parent_files, tmp_path):
    path = "data/role_runs/child/sessions/op-session.json"
    original = digest(parent_files[path])
    update(parent_files, path, lambda s: s.update(feeling={"reason": "[REDACTED]"}))
    projection = {
        path: {
            "original_sha256": original,
            "archive_sha256": digest(parent_files[path]),
            "reason": "credential_redaction",
        }
    }
    with pytest.raises(ConfigError, match="original content"):
        load(tmp_path, parent_files)
    assert (
        load(
            tmp_path, parent_files, receipt_updates={"public_projections": projection}
        ).selected_sessions[0]["feeling"]["reason"]
        == "[REDACTED]"
    )
    path = "materials/tasks/task/instruction"
    original = digest(parent_files[path])
    parent_files[path] = b"[REDACTED]"
    projection[path] = {
        "original_sha256": original,
        "archive_sha256": digest(parent_files[path]),
        "reason": "credential_redaction",
    }
    with pytest.raises(ConfigError, match="original content"):
        load(tmp_path, parent_files, receipt_updates={"public_projections": projection})


def test_repeated_continuation_requires_bootstrap_and_accumulates_round(parent_files, tmp_path):
    manifest = json.loads(parent_files["manifest.json"])
    manifest["config"]["continuation"] = {"archive": "parent.tar.gz", "sha256": "a" * 64}
    manifest["config"]["workload"] = {"source": "parent"}
    manifest["config_hash"] = config_hash(data=manifest["config"])
    manifest["lineage"] = {"base_round": 6, "parent_archive_sha256": "a" * 64}
    plan = json.loads(parent_files["materials/session-plan.json"])
    inherited_export = json.loads(parent_files[source.EXPORT_PATH])
    payload = encoded({"pairs": plan["rounds"][0], "export": inherited_export})
    parent_files["materials/continuation/input.json"] = payload
    manifest["materials"]["continuation_input"] = {
        "path": "materials/continuation/input.json",
        "sha256": digest(payload),
    }
    parent_files["manifest.json"] = encoded(manifest)
    update(
        parent_files,
        source.EXPORT_PATH,
        lambda e: (
            e["identity"].update(config_hash=manifest["config_hash"]),
            e["boundary"].update(lineage_round=7),
        ),
    )
    update(
        parent_files,
        "checkpoints/recovery.json",
        lambda e: e["identity"].update(config_hash=manifest["config_hash"]),
    )
    with pytest.raises(ConfigError, match="Incomplete"):
        load(tmp_path, parent_files)
    recovery = json.loads(parent_files["checkpoints/recovery.json"])
    bootstrap = {
        "identity": {**recovery["identity"], "plan_hash": digest(payload)},
        "rounds": {"1": {"status": "completed", "user_sha": "1" * 40, "sealed_sha": "1" * 40}},
    }
    parent_files["checkpoints/continuation-bootstrap/recovery.json"] = encoded(bootstrap)
    parent_files["runtime/continuation-issue-map.json"] = encoded(
        {
            "complete": True,
            "identity": {
                "child": bootstrap["identity"],
                "parent": inherited_export["identity"],
                "child_seed": "1" * 40,
                "parent_archive_sha256": "a" * 64,
            },
            "source_digest": config_hash(data=inherited_export["reports"]),
            "map_hash": config_hash(data={}),
            "issue_map": {},
        }
    )
    parent_files["runtime/continuation-bootstrap.json"] = encoded(
        {
            "status": "completed",
            "identity": bootstrap["identity"],
            "input_sha256": digest(payload),
            "sealed_sha": "1" * 40,
            "issue_map_sha256": digest(parent_files["runtime/continuation-issue-map.json"]),
        }
    )
    assert load(tmp_path, parent_files).summary()["base_round"] == 7
    update(
        parent_files, "runtime/continuation-bootstrap.json", lambda r: r.update(sealed_sha="3" * 40)
    )
    with pytest.raises(ConfigError, match="bootstrap"):
        load(tmp_path, parent_files)


def with_report(files, *, labels=None, state="open"):
    sid = "op-session"
    session_path = f"data/role_runs/child/sessions/{sid}.json"
    update(
        files,
        session_path,
        lambda s: s.update(issue_refs=[{"number": 3, "url": "https://forge/owner/repo/issues/3"}]),
    )
    issue = {
        "number": 3,
        "html_url": "https://forge/owner/repo/issues/3",
        "state": state,
        "title": "Fix output",
        "body": "Observed mismatch",
        "labels": [{"name": label} for label in (labels or ["report"])],
    }
    update(files, "runtime/gitea-evidence.json", lambda e: e.update(issues=[issue]))
    report = {key: issue[key] for key in ["number", "state", "title", "body"]}
    report.update(
        url=issue["html_url"],
        labels=[entry["name"] for entry in issue["labels"]],
        session_ids=[sid],
    )
    report["sha256"] = config_hash(data=report)
    update(
        files,
        source.EXPORT_PATH,
        lambda e: (
            e.update(reports=[report]),
            e["forge"].update(sha256=digest(files["runtime/gitea-evidence.json"])),
            e["boundary"]["sessions"][0].update(sha256=digest(files[session_path])),
        ),
    )


def test_report_associations_and_forge_namespace_are_explicit(parent_files, tmp_path):
    with_report(parent_files)
    assert load(tmp_path, parent_files).summary()["pending_reports"] == 1
    update(
        parent_files,
        source.EXPORT_PATH,
        lambda e: e["reports"][0].update(session_ids=["unrelated"]),
    )
    with pytest.raises(ConfigError, match="report"):
        load(tmp_path, parent_files)


@pytest.mark.parametrize("state,pending", [("open", 1), ("closed", 0)])
def test_current_sim_user_needs_triage_report_is_complete_and_counted(
    parent_files, tmp_path, state, pending
):
    with_report(parent_files, labels=["bug", "needs-triage", "round-1"], state=state)
    selected = load(tmp_path, parent_files)
    assert len(selected.reports) == 1
    assert selected.reports[0]["labels"] == ["bug", "needs-triage", "round-1"]
    assert selected.summary()["pending_reports"] == pending


def test_export_cannot_silently_omit_current_user_report(parent_files, tmp_path):
    with_report(parent_files, labels=["bug", "needs-triage", "round-1"])
    update(parent_files, source.EXPORT_PATH, lambda e: e.update(reports=[]))
    with pytest.raises(ConfigError, match="reports do not match selected feedback"):
        load(tmp_path, parent_files)


@pytest.mark.parametrize(
    "labels",
    [
        ["bug", "needs-triage", "declined"],
        ["bug", "needs-triage", "rejected"],
        ["bug", "needs-triage", "proposal"],
        ["bug", "needs-triage", "openagents"],
        ["bug", "needs-triage", "ready"],
    ],
)
def test_non_report_plane_refs_remain_forge_background(parent_files, tmp_path, labels):
    with_report(parent_files, labels=labels)
    update(parent_files, source.EXPORT_PATH, lambda e: e.update(reports=[]))
    selected = load(tmp_path, parent_files)
    assert selected.reports == []
    assert selected.summary()["pending_reports"] == 0


@pytest.mark.parametrize(
    "labels",
    [
        ["report", "declined"],
        ["report", "delivered"],
        ["report", "owner-rejected"],
    ],
)
def test_closed_or_decided_report_plane_refs_are_not_pending(parent_files, tmp_path, labels):
    with_report(parent_files, labels=labels)
    selected = load(tmp_path, parent_files)
    assert len(selected.reports) == 1
    assert selected.summary()["pending_reports"] == 0


def test_projected_report_retains_original_hash_and_declares_redaction(parent_files, tmp_path):
    with_report(parent_files)
    projections = {}
    for path in [source.EXPORT_PATH, "runtime/gitea-evidence.json"]:
        original = digest(parent_files[path])
        if path == source.EXPORT_PATH:
            update(parent_files, path, lambda e: e["reports"][0].update(body="[REDACTED]"))
        else:
            update(parent_files, path, lambda e: e["issues"][0].update(body="[REDACTED]"))
        projections[path] = {
            "original_sha256": original,
            "archive_sha256": digest(parent_files[path]),
            "reason": "credential_redaction",
        }
    with pytest.raises(ConfigError):
        load(tmp_path, parent_files)
    assert (
        load(tmp_path, parent_files, receipt_updates={"public_projections": projections}).reports[
            0
        ]["body"]
        == "[REDACTED]"
    )


def test_native_observation_manifest_hashes_are_verified(parent_files, tmp_path):
    prefix = "data/role_runs/child/observations/op-session"
    raw = b'{"event":"done"}\n'
    parent_files[prefix + "/runs/native/log.jsonl"] = raw
    native = {
        "session_id": "op-session",
        "run_id": "native",
        "artifact": {"harness_sha": "1" * 40},
        "files": [{"path": "log.jsonl", "sha256": digest(raw), "bytes": len(raw)}],
    }
    parent_files[prefix + "/runs/native/manifest.json"] = encoded(native)
    payload = parent_files[prefix + "/runs/native/manifest.json"]
    parent_files[prefix + "/manifest.json"] = encoded(
        {
            "session_id": "op-session",
            "runs": [{"run_id": "native", "manifest": "runs/native/manifest.json"}],
            "files": [
                {
                    "path": "runs/native/manifest.json",
                    "sha256": digest(payload),
                    "bytes": len(payload),
                }
            ],
        }
    )
    update(
        parent_files,
        source.EXPORT_PATH,
        lambda e: e["boundary"]["sessions"][0].update(observation_path=prefix),
    )
    assert load(tmp_path, parent_files).summary()["continuation_ready"]
    parent_files[prefix + "/runs/native/log.jsonl"] = b"changed\n"
    selected = load(tmp_path, parent_files)
    assert selected.selected_sessions[0]["observation_status"] == "unavailable"
    assert selected.summary()["gaps"][0]["kind"] == "native_observation"
    assert selected.export["boundary"]["sessions"][0]["observation_path"] == prefix
