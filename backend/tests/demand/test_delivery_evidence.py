import gzip
import hashlib
import json

import pytest

from auto_designer.demand.delivery_evidence import build_package, publish_delivery_evidence
from auto_designer.demand.owner import Owner
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


def test_verified_existing_footer_does_not_rewrite_delivery_labels(tmp_path, monkeypatch):
    store, tracker, issue = setup(tmp_path)
    first = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    tracker.set_labels(issue.number, ["openagents", "ready", "openagents-dispatching"])
    reads = []
    download = tracker.download_issue_asset

    def readback(**kwargs):
        reads.append(kwargs["asset_id"])
        return download(**kwargs)

    def unexpected_update(*args, **kwargs):
        pytest.fail("an already verified publication must not rewrite downstream labels")

    monkeypatch.setattr(tracker, "download_issue_asset", readback)
    monkeypatch.setattr(tracker, "update_issue", unexpected_update)
    assert publish_delivery_evidence(tracker=tracker, store=store, issue=issue) == first
    assert reads == [first["asset_id"]]
    assert tracker.issue(issue.number)["labels"] == [
        "openagents",
        "ready",
        "openagents-dispatching",
    ]
    monkeypatch.setattr(tracker, "download_issue_asset", lambda **kwargs: b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        publish_delivery_evidence(tracker=tracker, store=store, issue=issue)


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


def test_zip_is_deterministic_single_file_and_reuses_verified_asset(tmp_path):
    import io
    import zipfile

    from auto_designer.observations.transport import make_transport_profile

    store, tracker, issue = setup(tmp_path)
    tracker.observation_transport = make_transport_profile(
        repository="https://gitea.com/api/v1/repos/o/r",
        encoding="zip",
        download_policy="gitea-com-r2-v1",
    )
    zipped = build_package(store=store, issue=issue.number, encoding="zip")
    assert zipped == build_package(store=store, issue=issue.number, encoding="zip")
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        assert archive.namelist() == ["evidence.json"]
        entry = archive.infolist()[0]
        assert entry.date_time == (1980, 1, 1, 0, 0, 0)
        assert entry.compress_type == zipfile.ZIP_DEFLATED
        assert entry.external_attr >> 16 == 0o100644
        assert archive.read(entry) == gzip.decompress(
            build_package(store=store, issue=issue.number)
        )
    first = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    second = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert first == second
    assert first["encoding"] == "zip"
    assert first["name"].endswith(".zip")
    assert len(tracker.assets[issue.number]) == 1
    assert (
        json.loads(
            tracker.issue(issue.number)["body"]
            .split("auto-designer:observation-evidence-v1 ")[1]
            .split(" -->")[0]
        )["encoding"]
        == "zip"
    )


def test_gzip_original_bytes_and_footer_remain_unchanged(tmp_path):
    store, tracker, issue = setup(tmp_path)
    packed = build_package(store=store, issue=issue.number)
    value = json.loads(gzip.decompress(packed))
    assert packed == gzip.compress(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(), mtime=0
    )
    result = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert "encoding" not in result
    assert (
        result["name"] == "observation-evidence-" + hashlib.sha256(packed).hexdigest() + ".json.gz"
    )


def test_failed_zip_readback_preserves_issue_and_retry_reuses_asset(tmp_path, monkeypatch):
    from auto_designer.observations.transport import make_transport_profile

    store, tracker, issue = setup(tmp_path)
    tracker.observation_transport = make_transport_profile(
        repository="https://gitea.com/api/v1/repos/o/r", encoding="zip"
    )
    original = tracker.download_issue_asset
    body = tracker.issue(issue.number)["body"]
    monkeypatch.setattr(tracker, "download_issue_asset", lambda **kw: b"wrong")
    with pytest.raises(ValueError, match="integrity"):
        publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert tracker.issue(issue.number)["body"] == body
    monkeypatch.setattr(tracker, "download_issue_asset", original)
    publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
    assert len(tracker.assets[issue.number]) == 1


@pytest.mark.parametrize("encoding", ["gzip", "zip"])
def test_final_serialized_package_expanded_limit_enforced(tmp_path, monkeypatch, encoding):
    from auto_designer.demand import delivery_evidence as module

    store, tracker, issue = setup(tmp_path)
    monkeypatch.setattr(module, "MAX_EXPANDED", 100)
    with pytest.raises(ValueError, match="budget"):
        build_package(store=store, issue=issue.number, encoding=encoding)


def test_unknown_encoding_is_not_guessed(tmp_path):
    store, tracker, issue = setup(tmp_path)
    with pytest.raises(ValueError, match="encoding"):
        build_package(store=store, issue=issue.number, encoding="tar")


def test_current_execution_contract_and_public_material_survive_missing_logs(tmp_path):
    from test_evidence_contract import contract_session

    from auto_designer.execution_contract import canonical_bytes

    store = SessionStore(tmp_path / "sessions")
    session = contract_session()
    store.save(session)
    grant(store=store, issue=7, sessions={session.session_id})
    value = json.loads(gzip.decompress(build_package(store=store, issue=7)))
    contract = value["execution_evidence"]["execution_contracts"][0]
    assert contract == session.execution_contract
    row = value["sessions"][0]
    assert row["observation_status"] == "unavailable"
    assert row["status"] == "available"
    assert row["files"]["execution/task.json"].encode() == canonical_bytes(
        session.scenario.to_dict()
    )
    assert "session.json" not in row["files"]
    assert "private" not in row["files"]


def test_public_material_must_match_frozen_contract_not_current_text(tmp_path):
    from test_evidence_contract import contract_session

    store = SessionStore(tmp_path / "sessions")
    session = contract_session()
    session.scenario.description = "mutated after declaration"
    store.save(session)
    grant(store=store, issue=7, sessions={session.session_id})
    with pytest.raises(ValueError, match="immutable declaration"):
        build_package(store=store, issue=7)


def test_owner_merge_preserves_conditions_of_both_sources(tmp_path):
    from test_evidence_contract import contract_session

    store = SessionStore(tmp_path / "sessions")
    tracker = AssetTracker()
    refs = []
    sessions = [
        contract_session(sid="source-one"),
        contract_session(sid="source-two", followup="possible"),
    ]
    for session in sessions:
        store.save(session)
        ref = tracker.create_issue(IssueDraft(title="same", body="same", labels=["proposal"]))
        grant(store=store, issue=ref.number, sessions={session.session_id})
        refs.append(ref)
    owner = Owner(tracker, store, str(tmp_path), "unused", review=False)
    owner._merge(tracker.list_open_issues()[0], into=refs[1].number)
    package = json.loads(gzip.decompress(tracker.assets[refs[1].number][-1]["data"]))
    contracts = package["execution_evidence"]["execution_contracts"]
    assert {row["followup_input"] for row in contracts} == {"unavailable", "possible"}
    assert {row["session_id"] for row in contracts} == {s.session_id for s in sessions}
