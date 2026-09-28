import gzip
import hashlib
import json

import pytest

from auto_designer.designer.delivery_evidence import build_package, publish_delivery_evidence
from auto_designer.designer.owner import Owner
from auto_designer.models import IssueDraft
from auto_designer.observations.grants import grant
from auto_designer.observations.publication import publish
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class AssetTracker(FakeTracker):
    def __init__(self):
        super().__init__()
        self.assets = {}

    def list_issue_assets(self, *, number):
        return self.assets.get(number, [])

    def upload_issue_asset(self, *, number, name, data):
        asset = {"id": 1, "name": name, "data": data}
        self.assets.setdefault(number, []).append(asset)
        return asset

    def download_issue_asset(self, *, number, asset_id, limit):
        return next(a["data"] for a in self.assets[number] if a["id"] == asset_id)

    def get_issue(self, *, number):
        return self.issue(number)


def setup(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    tracker = AssetTracker()
    issue = tracker.create_issue(
        IssueDraft(title="A", body="session_id: other", labels=["proposal"])
    )
    grant(store=store, issue=issue.number, sessions={"s1"})
    files = {"READING.md": b"current meaning", "events.log": b"old or new?"}
    files["manifest.json"] = json.dumps(
        {"reading": "READING.md", "status": "complete", "files": [{"path": n} for n in files]}
    ).encode()
    publish(
        root=tmp_path / "observations",
        session_id="s1",
        run_id="r1",
        version={"harness_sha": "actual-v1"},
        files=files,
    )
    return store, tracker, tracker.list_open_issues()[0]


def test_package_uses_grants_not_model_authored_references(tmp_path):
    store, tracker, issue = setup(tmp_path)
    data = build_package(store=store, issue=issue.number)
    value = json.loads(gzip.decompress(data))
    assert [s["session_id"] for s in value["sessions"]] == ["s1"]
    manifest = json.loads(value["sessions"][0]["files"]["runs/r1/manifest.json"])
    assert manifest["artifact"]["harness_sha"] == "actual-v1"
    result = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert len(tracker.assets[issue.number]) == 1


def test_owner_publishes_before_admission_without_gaining_raw_tools(tmp_path):
    store, tracker, issue = setup(tmp_path)
    original = tracker.set_labels

    def admission(number, labels):
        assert "auto-designer:observation-evidence-v1" in tracker.issue(number)["body"]
        original(number, labels)

    tracker.set_labels = admission
    owner = Owner(tracker, store, str(tmp_path), "unused", review=False)
    assert owner.admit_once().admitted == [issue.number]


def test_failed_upload_preserves_proposal_and_retry(tmp_path, monkeypatch):
    store, tracker, issue = setup(tmp_path)
    original = tracker.upload_issue_asset
    monkeypatch.setattr(
        tracker, "upload_issue_asset", lambda **kw: (_ for _ in ()).throw(OSError("offline"))
    )
    owner = Owner(tracker, store, str(tmp_path), "unused", review=False)
    assert owner.admit_once().failed
    assert tracker.issue(issue.number)["labels"] == ["proposal"]
    monkeypatch.setattr(tracker, "upload_issue_asset", original)
    assert owner.admit_once().admitted == [issue.number]


def test_corrupt_history_is_reported_unavailable_not_sent(tmp_path):
    store, tracker, issue = setup(tmp_path)
    (tmp_path / "observations/s1/runs/r1/events.log").write_text("changed")
    value = json.loads(gzip.decompress(build_package(store=store, issue=issue.number)))
    assert value["sessions"][0]["status"] == "unavailable"
    assert "files" not in value["sessions"][0]


def test_attachment_read_has_an_absolute_deadline_even_if_bytes_keep_arriving(monkeypatch):
    from types import SimpleNamespace

    from auto_designer.tracker import gitea

    tracker = gitea.GiteaTracker("http://trusted", "o", "r", "test-only-token")
    calls = []

    class Response:
        status_code = 200
        raw = SimpleNamespace(read1=lambda *a, **kw: b"a")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tracker._session = SimpleNamespace(get=lambda url, **kw: calls.append(kw) or Response())
    ticks = iter([0, 16])
    monkeypatch.setattr(gitea, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(ValueError, match="budget"):
        tracker._observation_bytes(url="http://trusted/attachments/id", limit=100)
    assert calls[0]["allow_redirects"] is False
