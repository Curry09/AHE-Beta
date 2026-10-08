"""Spec-0079/T4: exact seed trees, resumable feedback and honest completion facts."""

import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from auto_designer.experiment import engine
from auto_designer.experiment.config import ConfigError, config_hash
from auto_designer.experiment.continuation.export import export_git_tree
from auto_designer.experiment.controllers import feedback, runtime
from auto_designer.experiment.materials import sha256_file
from auto_designer.loop.feedback_pipeline import FeedbackPipeline
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import current_usage_context
from auto_designer.user.session_store import SessionStore
from test_experiment_config_v2 import write


def _git(repo, *args, input=None):
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
        input=input,
    )
    return result.stdout.decode().strip()


@pytest.fixture
def inherited_run(tmp_path, monkeypatch):
    parent = tmp_path / "parent-repo"
    parent.mkdir()
    _git(parent, "init", "-b", "main")
    files = {
        ".gitignore": b"ignored.bin\nparent-custom-rule/\n",
        ".gitattributes": b"*.txt text eol=lf\nignored.bin export-ignore\npayload.txt export-subst\n",
        "ignored.bin": b"tracked despite ignore\n",
        "payload.txt": b"raw CRLF\r\n$Format:%H$\r\n",
        "run.sh": b"#!/bin/sh\nexit 0\n",
    }
    for relative, data in files.items():
        (parent / relative).write_bytes(data)
        oid = _git(parent, "hash-object", "-w", "--stdin", input=data)
        _git(
            parent,
            "update-index",
            "--add",
            "--cacheinfo",
            "100755" if relative == "run.sh" else "100644",
            oid,
            relative,
        )
    _git(parent, "commit", "-m", "parent raw tree")
    parent_commit = _git(parent, "rev-parse", "HEAD")
    root = tmp_path / "child"
    (root / "runtime").mkdir(parents=True)
    archive = root / "materials/harness.tar.gz"
    harness = export_git_tree(repo=parent, commit=parent_commit, destination=archive)
    harness["archive"] = "runtime/continuation-harness.tar.gz"
    parent_root = root / "materials/continuation/parent"
    write(
        parent_root / "runtime/gitea-evidence.json",
        {"repository": {"id": 1, "full_name": "owner/parent"}, "issues": []},
    )
    export = {
        "identity": {"run_id": "parent", "experiment_id": "parent"},
        "harness": harness,
        "boundary": {"sessions": []},
        "forge": {"path": "runtime/gitea-evidence.json"},
        "reports": [],
    }
    inherited = {
        "export": export,
        "parent_root": "materials/continuation/parent",
        "pairs": [],
        "lineage": {"base_round": 5, "parent_archive_sha256": "a" * 64},
    }
    input_path = write(root / "materials/continuation/input.json", inherited)
    config = {
        "continuation": {"archive": "parent.tar.gz", "sha256": "a" * 64},
        "rounds": {"count": 1},
    }
    manifest = {
        "run_id": "child",
        "experiment_id": "child",
        "controller_sha": "c" * 40,
        "plan_hash": "d" * 64,
        "config": config,
        "config_hash": config_hash(data=config),
        "materials": {
            "continuation_input": {
                "path": "materials/continuation/input.json",
                "sha256": sha256_file(input_path),
            },
            "harness_archive": {"path": "materials/harness.tar.gz", "sha256": sha256_file(archive)},
        },
    }
    write(root / "manifest.json", manifest)
    repo = root / "data/harness_sandbox/harness_repo"
    monkeypatch.setattr(runtime, "HARNESS_REPO", repo)
    monkeypatch.setenv("AUTO_DESIGNER_HARNESS_ARCHIVE", str(archive))
    monkeypatch.setenv("AUTO_DESIGNER_CONTINUATION_INPUT", str(input_path))
    return SimpleNamespace(
        root=root,
        repo=repo,
        manifest=manifest,
        parent=parent,
        parent_commit=parent_commit,
        files=files,
        input_path=input_path,
    )


def test_seed_preserves_raw_parent_tree_ignored_files_modes_and_attributes(
    inherited_run, monkeypatch
):
    run = inherited_run
    # Host settings would transform a normal git-add path; inherited seed uses raw blobs.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    runtime._seed_harness_repo()
    child_commit = _git(run.repo, "rev-parse", "HEAD")
    assert child_commit != run.parent_commit
    assert _git(run.repo, "rev-parse", "HEAD^{tree}") == _git(
        run.parent, "rev-parse", "HEAD^{tree}"
    )
    assert "ignored.bin" in _git(run.repo, "ls-files").splitlines()
    for relative, expected in run.files.items():
        assert (run.repo / relative).read_bytes() == expected
        assert (
            subprocess.check_output(["git", "-C", str(run.repo), "show", "HEAD:" + relative])
            == expected
        )
    assert (run.repo / "run.sh").stat().st_mode & 0o111
    assert (run.repo / ".git/hooks/pre-commit").is_file()
    assert ".openagents/" in (run.repo / ".git/info/exclude").read_text()


def test_seed_rejects_changed_blob_before_committing(inherited_run):
    run = inherited_run
    document = json.loads(run.input_path.read_text())
    document["export"]["harness"]["files"]["payload.txt"]["sha256"] = "0" * 64
    write(run.input_path, document)
    with pytest.raises(SystemExit, match="file content"):
        runtime._seed_harness_repo()
    result = subprocess.run(
        ["git", "-C", str(run.repo), "rev-parse", "--verify", "HEAD"], capture_output=True
    )
    assert result.returncode != 0


def test_ordinary_seed_retains_existing_ignore_and_hook_behavior(tmp_path, monkeypatch):
    root = tmp_path / "controller"
    (root / "harness_template").mkdir(parents=True)
    (root / "harness_template/entry.py").write_text("pass\n")
    (root / "harness_template/.gitignore").write_text("custom\n")
    monkeypatch.setattr(runtime, "ROOT", root)
    monkeypatch.setattr(runtime, "HARNESS_REPO", tmp_path / "ordinary-repo")
    monkeypatch.delenv("AUTO_DESIGNER_HARNESS_ARCHIVE", raising=False)
    monkeypatch.delenv("AUTO_DESIGNER_CONTINUATION_INPUT", raising=False)
    repo = runtime._seed_harness_repo()
    assert (repo / ".gitignore").read_text() == "__pycache__/\n*.pyc\n.openagents/\n"
    assert (repo / ".git/hooks/pre-commit").exists()
    assert _git(repo, "log", "-1", "--format=%s") == "seed: harness v0"


def _bootstrap(run, tracker=None):
    tracker = tracker or FakeTracker()
    return feedback.run_continuation_bootstrap(
        run_root=run.root,
        manifest=run.manifest,
        tracker=tracker,
        child_store=SessionStore(run.root / "data/role_runs/child/sessions"),
        repo=run.repo,
        definitions_root=run.root / "definitions",
        roster={},
        resolve_head=lambda: _git(run.repo, "rev-parse", "main"),
        assert_descendant=lambda **sha: _git(
            run.repo, "merge-base", "--is-ancestor", sha["ancestor"], sha["descendant"]
        ),
        integrity_guard=lambda: None,
        status_factory=lambda *args: None,
        event_factory=lambda *args: None,
    )


def _empty_roles(monkeypatch):
    monkeypatch.setattr(
        feedback,
        "assemble_feedback_roles",
        lambda **kwargs: {"triagers": [], "synthesizers": [], "divergents": [], "owner": None},
    )


def test_bootstrap_resume_skips_models_and_rebuilds_receipt_after_seal(inherited_run, monkeypatch):
    run = inherited_run
    runtime._seed_harness_repo()
    _empty_roles(monkeypatch)
    receipt = _bootstrap(run)
    assert receipt["status"] == "completed"
    assert receipt["no_admissions"] is True
    ledger = json.loads((run.root / "checkpoints/continuation-bootstrap/recovery.json").read_text())
    assert "users" not in ledger["rounds"]["1"]["stages"]
    assert receipt["identity"]["plan_hash"] == sha256_file(run.input_path)
    assert receipt["identity"]["run_id"] == "child"
    assert not (run.root / "checkpoints/recovery.json").exists()
    monkeypatch.setattr(
        feedback, "assemble_feedback_roles", lambda **kwargs: pytest.fail("bootstrap reran roles")
    )
    assert _bootstrap(run) == receipt
    (run.root / "runtime/continuation-bootstrap.json").unlink()
    assert _bootstrap(run) == receipt
    assert json.loads((run.root / "runtime/continuation-bootstrap.json").read_text()) == receipt


def test_bootstrap_nonempty_admission_uses_isolated_external_identity(inherited_run, monkeypatch):
    run = inherited_run
    runtime._seed_harness_repo()
    tracker = FakeTracker()
    operations = []

    class Owner:
        def admit_once(self):
            operations.append(current_usage_context().operation)
            ref = tracker.create_issue_once(
                IssueDraft("delivery", "work", ["ready"]),
                operation_key=current_usage_context().operation,
            )
            tracker.set_state(ref.number, "closed", "delivered")
            return SimpleNamespace(admitted=[ref.number])

    monkeypatch.setattr(
        feedback,
        "assemble_feedback_roles",
        lambda **kwargs: {"triagers": [], "synthesizers": [], "divergents": [], "owner": Owner()},
    )
    receipt = _bootstrap(run, tracker)
    assert receipt["no_admissions"] is False
    assert receipt["admitted_issue_ids"] == [1]
    assert len(operations) == 1
    assert operations[0] != "owner"
    assert _bootstrap(run, tracker) == receipt
    assert len(operations) == 1


def test_bootstrap_does_not_seal_or_publish_receipt_after_guard_failure(inherited_run, monkeypatch):
    run = inherited_run
    runtime._seed_harness_repo()
    _empty_roles(monkeypatch)
    original = FeedbackPipeline.seal

    def interrupt(self, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(FeedbackPipeline, "seal", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _bootstrap(run)
    assert not (run.root / "runtime/continuation-bootstrap.json").exists()
    ledger = json.loads((run.root / "checkpoints/continuation-bootstrap/recovery.json").read_text())
    assert ledger["rounds"]["1"]["status"] != "completed"
    monkeypatch.setattr(FeedbackPipeline, "seal", original)
    assert _bootstrap(run)["status"] == "completed"


def _complete_user_round(run, sha):
    identity = RecoveryIdentity(
        **{
            key: run.manifest[key]
            for key in ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash")
        }
    )
    store = RecoveryStore.initialize(root=run.root / "checkpoints", identity=identity)
    store.freeze_round(round_no=1, user_sha=sha, plan=[])
    pipeline = FeedbackPipeline(
        recovery=store, resolve_head=lambda: sha, assert_descendant=lambda **kwargs: None
    )
    pipeline.mark_stage(round_no=1, stage="users", input_value={"sessions": []})
    pipeline.seal(round_no=1, user_sha=sha)
    write(
        run.root / "data/role_runs/child/manifest.json",
        {"run_id": "child", "rounds": [{"round": 1, "sealed_sha": sha}]},
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "mapping",
        "r1_sha",
        "receipt_status",
        "imported_stage",
        "receipt_missing",
        "input_hash",
    ],
)
def test_completion_requires_bootstrap_identity_map_and_first_user_sha(
    inherited_run, monkeypatch, mutation
):
    run = inherited_run
    runtime._seed_harness_repo()
    _empty_roles(monkeypatch)
    receipt = _bootstrap(run)
    _complete_user_round(run, receipt["sealed_sha"])
    assert engine._completion(run.root)["experiment_complete"] is True
    receipt_path = run.root / "runtime/continuation-bootstrap.json"
    if mutation == "mapping":
        path = run.root / "runtime/continuation-issue-map.json"
        document = json.loads(path.read_text())
        document["issue_map"]["forged"] = {"current_number": 99}
        write(path, document)
    elif mutation == "r1_sha":
        path = run.root / "checkpoints/recovery.json"
        document = json.loads(path.read_text())
        document["rounds"]["1"]["user_sha"] = "f" * 40
        write(path, document)
    elif mutation == "imported_stage":
        path = run.root / "checkpoints/continuation-bootstrap/recovery.json"
        document = json.loads(path.read_text())
        document["rounds"]["1"]["stages"]["feedback_imported"]["status"] = "running"
        write(path, document)
    elif mutation == "receipt_missing":
        receipt_path.unlink()
    elif mutation == "input_hash":
        document = json.loads(run.input_path.read_text())
        document["extra"] = "changed"
        write(run.input_path, document)
    else:
        document = copy.deepcopy(receipt)
        if mutation == "identity":
            document["identity"]["run_id"] = "other-child"
        else:
            document["status"] = "running"
        write(receipt_path, document)
    assert engine._completion(run.root)["experiment_complete"] is False


def test_ordinary_completion_ignores_unrelated_bootstrap_domain(inherited_run):
    run = inherited_run
    run.manifest["config"].pop("continuation")
    write(run.root / "manifest.json", run.manifest)
    _complete_user_round(run, "f" * 40)
    write(run.root / "runtime/continuation-bootstrap.json", {"identity": "corrupt"})
    assert engine._completion(run.root)["experiment_complete"] is True
    assert "continuation_bootstrap" not in engine._completion(run.root)


@pytest.mark.parametrize("receipt_missing", [False, True])
def test_completed_bootstrap_rejects_changed_mapping_on_resume(
    inherited_run, monkeypatch, receipt_missing
):
    run = inherited_run
    runtime._seed_harness_repo()
    _empty_roles(monkeypatch)
    _bootstrap(run)
    path = run.root / "runtime/continuation-issue-map.json"
    document = json.loads(path.read_text())
    document["issue_map"] = {"different": {"current_number": 99}}
    write(path, document)
    if receipt_missing:
        (run.root / "runtime/continuation-bootstrap.json").unlink()
    with pytest.raises(ConfigError, match="(?i)mapping|projection|bootstrap import"):
        _bootstrap(run)


def _add_report_with_native_evidence(run):
    from auto_designer.loop.recovery import digest_value
    from auto_designer.models import (
        FeelingScore,
        IssueRef,
        Persona,
        SeedScenario,
        Session,
        Transcript,
        WorkspaceSpec,
    )

    inherited = json.loads(run.input_path.read_text())
    parent_root = run.root / inherited["parent_root"]
    session = Session(
        persona=Persona("parent-persona", "senior", "tools", "finish task", "concise"),
        scenario=SeedScenario(
            "complete the task",
            WorkspaceSpec(
                params={
                    "task_id": "parent-task",
                    "task_digest": "f" * 64,
                    "task_kind": "ordinary",
                    "interaction": "direct",
                }
            ),
        ),
        transcript=Transcript([]),
        feeling=FeelingScore(2, "no progress"),
        session_id="parent-session",
        issue_refs=[IssueRef(12, "https://parent.example/issues/12", "open")],
        session_provenance={
            "contract_version": 1,
            "run_id": "parent",
            "round_no": 5,
            "slot": 0,
            "persona_id": "parent-persona",
            "task_id": "parent-task",
            "task_digest": "f" * 64,
            "task_kind": "ordinary",
            "interaction": "direct",
            "harness_sha": run.parent_commit,
        },
    )
    relative = "data/role_runs/parent/sessions/parent-session.json"
    path = write(parent_root / relative, session.to_dict())
    observation = "data/role_runs/parent/observations/parent-session"
    native = parent_root / observation
    native.mkdir(parents=True)
    (native / "events.jsonl").write_text('{"event":"no-progress"}\n')
    write(
        native / "manifest.json",
        {
            "session_id": "parent-session",
            "files": [{"path": "events.jsonl", "sha256": sha256_file(native / "events.jsonl")}],
        },
    )
    inherited["export"]["boundary"]["sessions"] = [
        {
            "session_id": "parent-session",
            "path": relative,
            "sha256": sha256_file(path),
            "observation_path": observation,
        }
    ]
    report = {
        "number": 12,
        "url": "https://parent.example/issues/12",
        "title": "Task stalled",
        "body": "No visible progress. Historical #12.",
        "state": "open",
        "labels": ["report", "round-5"],
        "session_ids": ["parent-session"],
    }
    report["sha256"] = digest_value(report)
    inherited["export"]["reports"] = [report]
    write(run.input_path, inherited)
    run.manifest["materials"]["continuation_input"]["sha256"] = sha256_file(run.input_path)
    for frozen_path in [path, native / "manifest.json", native / "events.jsonl"]:
        relative = frozen_path.relative_to(run.root).as_posix()
        run.manifest["materials"]["continuation:" + relative] = {
            "path": relative,
            "sha256": sha256_file(frozen_path),
        }
    write(run.root / "manifest.json", run.manifest)


def test_resume_after_triage_reuses_frozen_projection_and_native_install(
    inherited_run, monkeypatch
):
    from auto_designer.demand.triage import Triager
    from auto_designer.experiment.continuation import evidence, forge
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    run = inherited_run
    _add_report_with_native_evidence(run)
    runtime._seed_harness_repo()
    tracker = FakeTracker()
    calls = {"projection": 0, "native": 0, "triage": 0, "divergent": 0}
    original_projection = forge.project_reports
    original_native = evidence.install_parent_observations

    def project(**kwargs):
        calls["projection"] += 1
        return original_projection(**kwargs)

    def install(**kwargs):
        calls["native"] += 1
        return original_native(**kwargs)

    class ModelTriager(Triager):
        def _run_agent(self, *, pending):
            calls["triage"] += 1
            return json.dumps(
                {
                    "dispositions": [
                        {
                            "issue": pending[0].number,
                            "disposition": "accept",
                            "kind": "bug",
                            "priority": "P1",
                            "proposal_title": "Investigated",
                            "fields": {
                                "根因区域": "harness fails to report progress",
                                "边界": "general harness capability",
                                "验收": "progress is visible",
                            },
                            "artifact": {
                                "reported_problem": "Task stalled",
                                "user_impact": "user cannot complete task",
                                "scope_boundary": "general harness capability",
                                "evidence": [f"report:#{pending[0].number}"],
                                "uncertainties": [],
                                "implementation_target": "harness",
                            },
                        }
                    ]
                }
            )

    class Divergent:
        def propose_once(self):
            calls["divergent"] += 1
            if calls["divergent"] == 1:
                raise RuntimeError("interrupt after triage")

    monkeypatch.setattr(forge, "project_reports", project)
    monkeypatch.setattr(evidence, "install_parent_observations", install)

    def roles(**kwargs):
        return {
            "triagers": [
                ModelTriager(
                    kwargs["tracker"],
                    kwargs["store"],
                    str(kwargs["repo"]),
                    str(kwargs["definitions_root"]),
                )
            ],
            "divergents": [Divergent()],
            "synthesizers": [],
            "owner": None,
        }

    monkeypatch.setattr(feedback, "assemble_feedback_roles", roles)
    with pytest.raises(RoundDeliveryBlocked, match="divergent-incomplete"):
        _bootstrap(run, tracker)
    imported = run.root / "data/role_runs/child/observations/parent-session/events.jsonl"
    assert imported.read_text() == '{"event":"no-progress"}\n'
    assert not (run.root / "data/role_runs/child/sessions/parent-session.json").exists()
    assert _bootstrap(run, tracker)["status"] == "completed"
    assert calls == {"projection": 1, "native": 1, "triage": 1, "divergent": 2}
    assert len(tracker.list_open_issues()) == 1


def test_resume_real_triager_reuses_saved_model_output_after_failed_side_effect(
    inherited_run, monkeypatch
):
    from auto_designer.demand.triage import Triager
    from auto_designer.loop.round_gate import RoundDeliveryBlocked

    run = inherited_run
    _add_report_with_native_evidence(run)
    runtime._seed_harness_repo()
    tracker = FakeTracker()
    calls = {"model": 0, "apply": 0}

    class ModelTriager(Triager):
        def _run_agent(self, *, pending):
            calls["model"] += 1
            return json.dumps(
                {
                    "dispositions": [
                        {
                            "issue": pending[0].number,
                            "disposition": "reject",
                            "reason": "outside product scope",
                        }
                    ]
                }
            )

        def _apply_with_retry(self, *args, **kwargs):
            calls["apply"] += 1
            if calls["apply"] == 1:
                raise RuntimeError("lost connection after model output")
            return super()._apply_with_retry(*args, **kwargs)

    def roles(**kwargs):
        return {
            "triagers": [
                ModelTriager(
                    kwargs["tracker"],
                    kwargs["store"],
                    str(kwargs["repo"]),
                    str(kwargs["definitions_root"]),
                )
            ],
            "synthesizers": [],
            "divergents": [],
            "owner": None,
        }

    monkeypatch.setattr(feedback, "assemble_feedback_roles", roles)
    with pytest.raises(RoundDeliveryBlocked, match="triage-incomplete"):
        _bootstrap(run, tracker)
    saved = json.loads((run.root / "checkpoints/continuation-bootstrap/recovery.json").read_text())
    units = list(saved["rounds"]["1"]["stages"]["triage"]["units"].values())
    assert any(unit.get("output_digest") for unit in units)
    assert _bootstrap(run, tracker)["status"] == "completed"
    assert calls == {"model": 1, "apply": 2}
    assert tracker.issue(1)["state"] == "closed"
