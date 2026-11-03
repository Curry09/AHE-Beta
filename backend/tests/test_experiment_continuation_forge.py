"""Spec-0079/T2: retries reconcile remote reports and never replay closed work."""

import json

import pytest

from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.continuation.forge import project_reports, verify_report_projection
from ahe_beta.loop.recovery import digest_value
from ahe_beta.models import IssueDraft
from ahe_beta.tracker.fake import FakeTracker


@pytest.fixture
def parent(tmp_path):
    root = tmp_path / "parent"
    (root / "runtime").mkdir(parents=True)
    forge = {"repository": {"id": 41, "full_name": "old/repo"}}
    (root / "runtime/gitea-evidence.json").write_text(json.dumps(forge))
    reports = []
    for number, state in [(7, "open"), (8, "closed")]:
        report = {
            "number": number,
            "url": f"https://old/repo/issues/{number}",
            "state": state,
            "title": "Original feeling",
            "body": f"Historical #7 and https://old/repo/issues/{number}",
            "labels": ["report", "needs-triage", "round-5"],
            "session_ids": ["parent-sid"],
        }
        report["sha256"] = digest_value(report)
        reports.append(report)
    exported = {
        "identity": {"run_id": "parent"},
        "forge": {"path": "runtime/gitea-evidence.json"},
        "reports": reports,
    }
    return root, exported


def test_crash_after_remote_creation_reuses_actual_number(tmp_path, parent, monkeypatch):
    root, exported = parent
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="Unrelated current #1", body="", labels=[]))
    path = tmp_path / "map.json"
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
        "receipt_path": path,
    }
    from ahe_beta.experiment.continuation import forge

    original = forge._write_receipt
    calls = 0

    def crash(path, value):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("power loss before local receipt")
        original(path, value)

    monkeypatch.setattr(forge, "_write_receipt", crash)
    with pytest.raises(OSError, match="power loss"):
        project_reports(**args)
    monkeypatch.setattr(forge, "_write_receipt", original)
    result = project_reports(**args)
    again = project_reports(**args)
    assert again == result
    assert len(tracker.list_open_issues()) == 2
    mapped = next(iter(result["issue_map"].values()))
    assert mapped["source_number"] == 7 and mapped["current_number"] == 2
    issue = tracker.get_issue(number=2)
    assert issue["labels"] == ["report", "needs-triage"]
    assert "Historical #7" in issue["body"]
    assert "round-5" in mapped["source_labels"]


def test_remote_payload_mutation_is_not_silently_recreated(tmp_path, parent):
    root, exported = parent
    tracker = FakeTracker()
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
        "receipt_path": tmp_path / "receipt",
    }
    project_reports(**args)
    tracker._issues[1]["body"] = "external edit\n" + tracker._issues[1]["body"]
    with pytest.raises(ConfigError, match="payload changed remotely"):
        project_reports(**args)
    assert len(tracker.list_open_issues()) == 1


def test_child_identity_conflict_fails_without_new_remote_work(tmp_path, parent):
    root, exported = parent
    tracker = FakeTracker()
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
        "receipt_path": tmp_path / "receipt",
    }
    project_reports(**args)
    args["child_identity"] = {"run_id": "different-child"}
    with pytest.raises(ConfigError, match="identity changed"):
        project_reports(**args)
    assert len(tracker.list_open_issues()) == 1


def test_resume_after_triage_body_migration_keeps_original_mapping(tmp_path, parent):
    heading = "## Original user report (case evidence, not an implementation target)"
    title_prefix = "**Original title:**"
    root, exported = parent
    tracker = FakeTracker()
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
        "receipt_path": tmp_path / "receipt",
    }
    original = project_reports(**args)
    issue = tracker.get_issue(number=1)
    tracker.add_comment(
        1,
        f"{heading}\n\n{title_prefix} {issue['title']}\n\n{issue['body']}",
    )
    tracker.update_issue(
        1, title="Normalized proposal", body="Implementation contract", labels=["proposal"]
    )
    resumed = project_reports(**args)
    assert resumed == original
    assert len(tracker.list_open_issues()) == 1
    assert tracker.get_issue(number=1)["title"] == "Normalized proposal"


def test_verify_imported_projection_is_read_only_and_rejects_remote_tampering(
    tmp_path, parent, monkeypatch
):
    root, exported = parent
    tracker = FakeTracker()
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
        "parent_archive_sha256": "a" * 64,
    }
    path = tmp_path / "receipt"
    projected = project_reports(**args, receipt_path=path)
    before = path.read_bytes()
    monkeypatch.setattr(
        tracker, "create_issue_once", lambda *a, **k: pytest.fail("created on resume")
    )
    from ahe_beta.experiment.continuation import forge

    monkeypatch.setattr(forge, "_write_receipt", lambda *a, **k: pytest.fail("rewrote receipt"))
    verify_report_projection(**args, projection=projected)
    assert path.read_bytes() == before
    tracker._issues[1]["body"] = "tampered"
    with pytest.raises(ConfigError, match="payload changed remotely"):
        verify_report_projection(**args, projection=projected)


def test_verified_mapping_cannot_redirect_to_same_number_from_other_source(tmp_path, parent):
    root, exported = parent
    tracker = FakeTracker()
    args = {
        "tracker": tracker,
        "parent_root": root,
        "export": exported,
        "child_identity": {"run_id": "child"},
        "child_seed": "f" * 40,
    }
    projection = project_reports(**args, receipt_path=tmp_path / "receipt")
    row = next(iter(projection["issue_map"].values()))
    row["source_number"] = 8
    projection["map_hash"] = digest_value(projection["issue_map"])
    with pytest.raises(ConfigError, match="mapping changed"):
        verify_report_projection(**args, projection=projection)


@pytest.mark.parametrize(
    "labels,state",
    [
        (["bug", "needs-triage", "round-5"], "closed"),
        (["bug", "needs-triage", "declined"], "open"),
        (["report", "needs-triage", "rejected"], "open"),
        (["needs-triage", "needs-info"], "open"),
        (["needs-triage", "ready"], "open"),
        (["report", "openagents"], "open"),
        (["needs-triage", "proposal"], "open"),
    ],
)
def test_terminal_or_admitted_current_labels_are_background_not_new_report_work(
    tmp_path, parent, labels, state
):
    root, exported = parent
    exported["reports"][0].update(labels=labels, state=state)
    tracker = FakeTracker()
    projection = project_reports(
        tracker=tracker,
        parent_root=root,
        export=exported,
        child_identity={"run_id": "child"},
        child_seed="f" * 40,
        receipt_path=tmp_path / "receipt",
    )
    assert projection["issue_map"] == {}
    assert tracker.list_open_issues() == []
