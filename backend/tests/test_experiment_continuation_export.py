"""Spec-0079/T2: final exports follow commits rather than mutable checkout contents."""

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from ahe_beta.experiment.collection import collect_archive
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.continuation.export import export_continuation, export_git_tree
from ahe_beta.experiment.continuation.forge import project_reports
from ahe_beta.experiment.continuation.source import load_continuation_source
from ahe_beta.loop.recovery import digest_value
from ahe_beta.loop.sim_user import _issue_draft_from_body
from ahe_beta.tracker.fake import FakeTracker
from test_experiment_continuation_source import parent_files as parent_files


def git(repo, *args):
    return (
        subprocess.check_output(
            ["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@x", *args]
        )
        .decode()
        .strip()
    )


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "git"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("ignored.py\n")
    (repo / "ignored.py").write_text("exact original blob\n")
    (repo / "executable").write_text("#!/bin/sh\necho original\n")
    (repo / "executable").chmod(0o755)
    git(repo, "add", "-f", ".gitignore", "ignored.py", "executable")
    git(repo, "commit", "-q", "-m", "selected")
    selected = git(repo, "rev-parse", "HEAD")
    (repo / "ignored.py").write_text("WRONG CHECKOUT\n")
    git(repo, "add", "-f", "ignored.py")
    git(repo, "commit", "-q", "-m", "unselected")
    return repo, selected


def test_git_export_reads_selected_blob_and_mode_and_is_repeatable(tmp_path, repository):
    repo, selected = repository
    path = tmp_path / "first.tar.gz"
    exported = export_git_tree(repo=repo, commit=selected, destination=path)
    assert exported["tree_id"] == git(repo, "rev-parse", selected + "^{tree}")
    assert exported["files"]["executable"]["mode"] == "100755"
    assert (
        exported["files"]["ignored.py"]["sha256"]
        == hashlib.sha256(b"exact original blob\n").hexdigest()
    )
    with tarfile.open(path) as archive:
        assert archive.extractfile("ignored.py").read() == b"exact original blob\n"
        assert archive.getmember("executable").mode == 0o755
    second = export_git_tree(repo=repo, commit=selected, destination=tmp_path / "second.tar.gz")
    assert second == exported


@pytest.mark.parametrize("mode", ["symlink", "private"])
def test_git_export_rejects_unsupported_or_private_tracked_file(tmp_path, repository, mode):
    repo, _ = repository
    if mode == "symlink":
        (repo / "linked").symlink_to("executable")
        git(repo, "add", "linked")
    else:
        (repo / ".env").write_text("not portable\n")
        git(repo, "add", "-f", ".env")
    git(repo, "commit", "-q", "-m", "unsupported")
    with pytest.raises(ConfigError, match="Unsupported or private"):
        export_git_tree(
            repo=repo, commit=git(repo, "rev-parse", "HEAD"), destination=tmp_path / "bad"
        )


@pytest.mark.parametrize("redact_code", [False, True])
@pytest.mark.parametrize("report_count", [0, 3])
def test_export_and_collection_preserve_declared_session_redaction(
    tmp_path, repository, parent_files, redact_code, report_count
):
    root = tmp_path / "run"
    for name, content in parent_files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    repo, selected = repository
    manifest = json.loads((root / "manifest.json").read_text())
    recovery = json.loads((root / "checkpoints/recovery.json").read_text())
    last = recovery["rounds"]["1"]
    last["user_sha"] = last["sealed_sha"] = selected
    for unit in last["stages"]["users"]["units"].values():
        unit["input"]["user_sha"] = selected
        unit["input_digest"] = digest_value(unit["input"])
    (root / "checkpoints/recovery.json").write_text(json.dumps(recovery))
    invocation_path = root / "data/role_runs/child/manifest.json"
    invocation = json.loads(invocation_path.read_text())
    invocation["rounds"][0].update(user_sha=selected, sealed_sha=selected)
    invocation_path.write_text(json.dumps(invocation))
    session_root = root / "data/role_runs/child/sessions"
    session_path = session_root / "op-session.json"
    session = json.loads(session_path.read_text())
    session["session_provenance"]["harness_sha"] = selected
    session["comment"] = "provider-secret-for-test"
    forge_path = root / "runtime/gitea-evidence.json"
    forge = json.loads(forge_path.read_text())
    original_tracker = FakeTracker()
    session["issue_refs"] = []
    for index in range(report_count):
        # Exercise the actual current writer: its tags have needs-triage,
        # bug/feature and round-1, without an explicit report label.
        draft = _issue_draft_from_body(f"Bug {index}: current observed user issue", round_no=1)
        assert "report" not in draft.labels and "needs-triage" in draft.labels
        ref = original_tracker.create_issue_once(
            draft, operation_key=f"fixture-current-report-{index}"
        )
        session["issue_refs"].append(ref.to_dict())
        issue = original_tracker.get_issue(number=ref.number)
        forge["issues"].append(
            {
                **issue,
                "number": ref.number,
                "html_url": ref.url,
                "labels": [{"name": label} for label in issue["labels"]],
            }
        )
    forge_path.write_text(json.dumps(forge))
    session_path.write_text(json.dumps(session))
    for unit in last["stages"]["users"]["units"].values():
        unit["output_digest"] = digest_value(session)
        receipt_path = root / "checkpoints" / unit["output_artifact"]
        original_receipt = json.loads(receipt_path.read_text())
        original_receipt.update(
            input_digest=unit["input_digest"], output_digest=unit["output_digest"], output=session
        )
        receipt_path.write_text(json.dumps(original_receipt))
    (root / "checkpoints/recovery.json").write_text(json.dumps(recovery))
    exported = export_continuation(
        root=root,
        manifest=manifest,
        recovery=recovery,
        harness_repo=repo,
        sessions_root=session_root,
    )
    assert exported["status"] == "ready"
    assert exported["harness"]["commit"] == selected
    assert len(exported["reports"]) == report_count
    receipt = collect_archive(
        run_dir=root,
        manifest=manifest,
        snapshot={
            "snapshot_dir": str(root),
            "consistent": True,
            "terminal": True,
            "controller": {
                "experiment_complete": True,
                "nonce": "nonce",
                "expected_rounds": 1,
                "sealed_rounds": [1],
                "exit_code": 0,
                "running": False,
                "stopped_by_user": False,
            },
        },
        credentials={
            "MODEL_API_KEY": "provider-secret-for-test",
            **({"SECOND_API_KEY": "instruction"} if redact_code else {}),
        },
    )
    assert receipt["collection_state"] == "COMPLETE"
    assert receipt["continuation_ready"] is not redact_code
    relative = session_path.relative_to(root).as_posix()
    projected = receipt["public_projections"][relative]
    assert projected["original_sha256"] == exported["boundary"]["sessions"][0]["sha256"]
    assert projected["archive_sha256"] != projected["original_sha256"]
    assert "provider-secret-for-test" not in json.dumps(projected)
    if redact_code:
        with pytest.raises(ConfigError):
            load_continuation_source(
                archive=Path(receipt["archive"]), sha256=receipt["archive_sha256"]
            )
    else:
        loaded = load_continuation_source(
            archive=Path(receipt["archive"]), sha256=receipt["archive_sha256"]
        )
        assert loaded.export["harness"]["commit"] == selected
        assert loaded.summary()["pending_reports"] == report_count
        child_tracker = FakeTracker()
        projection = project_reports(
            tracker=child_tracker,
            parent_root=root,
            export=loaded.export,
            child_identity={"run_id": "new-child"},
            child_seed="f" * 40,
            receipt_path=tmp_path / "child-map.json",
            parent_archive_sha256=receipt["archive_sha256"],
        )
        assert len(projection["issue_map"]) == report_count
        assert len(child_tracker.list_open_issues()) == report_count


def test_missing_git_object_is_explicitly_unavailable(tmp_path, parent_files):
    root = tmp_path / "run"
    root.mkdir()
    manifest = json.loads(parent_files["manifest.json"])
    recovery = json.loads(parent_files["checkpoints/recovery.json"])
    for name, content in parent_files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    result = export_continuation(
        root=root,
        manifest=manifest,
        recovery=recovery,
        harness_repo=tmp_path,
        sessions_root=root / "data/role_runs/child/sessions",
    )
    assert result["status"] == "unavailable"
    assert "stderr" not in result
