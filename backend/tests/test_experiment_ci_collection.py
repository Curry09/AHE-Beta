"""Spec-0077/T4: archive CI facts for current heads without private registration."""

import json
import tarfile

import pytest

from auto_designer.experiment.collection import collect_archive, export_gitea_snapshot

OLD = "a" * 40
NEW = "b" * 40


def _provider(monkeypatch, *, new_status, malformed=False):
    calls = []
    replies = {
        "": {"id": 1, "name": "harness"},
        "/issues": [],
        "/pulls": [{"number": 2, "head": {"sha": NEW}}],
        "/branches": [{"name": "main", "commit": {"id": OLD}}],
        "/issues/2/comments": [],
        f"/commits/{OLD}/status": {
            "state": "success",
            "statuses": [{"state": "success", "context": "smoke"}],
        },
        f"/commits/{NEW}/status": (
            []
            if malformed
            else {"state": new_status, "statuses": [{"state": new_status, "context": "smoke"}]}
        ),
    }

    class Response:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    def get(url, **kwargs):
        route = url.partition("/api/v1/repos/experiment/harness")[2]
        calls.append(route)
        return Response(replies[route])

    monkeypatch.setattr("requests.get", get)
    return calls


@pytest.fixture
def resources():
    return {
        "gitea": {"url": "http://127.0.0.1:32123", "owner": "experiment", "repo": "harness"},
        "ci": {
            "enabled": True,
            "state": "READY",
            "run_id": "run",
            "config_hash": "hash",
            "network": "owned_ci",
            "job_image_id": "sha256:job",
            "daemon": {
                "container_id": "owned-daemon",
                "image_id": "sha256:daemon",
                "token": "private",
            },
            "registration_token": "private-registration-secret",
            "runner": {"id": 3, "name": "owned", "image_id": "sha256:runner", "token": "private"},
            "readiness": {
                "head_sha": OLD,
                "status_count": 1,
                "state": "success",
                "checked_at": "2026-10-03T12:00:00+00:00",
                "opaque": "private",
            },
        },
    }


@pytest.mark.parametrize("state", ["failure", "pending", "success"])
def test_new_pr_head_keeps_its_own_status_despite_old_green(
    tmp_path, monkeypatch, resources, state
):
    calls = _provider(monkeypatch, new_status=state)
    receipt = export_gitea_snapshot(
        run_dir=tmp_path, resources=resources, credentials={"GITEA_TOKEN": "provider-secret"}
    )
    assert receipt["complete"]
    doc = json.loads((tmp_path / "runtime/gitea-evidence.json").read_text())
    statuses = doc["ci"]["commit_statuses"]
    assert statuses[OLD]["state"] == "success"
    assert statuses[NEW]["state"] == state
    assert calls.count(f"/commits/{NEW}/status") == 1
    assert "private" not in json.dumps(doc)


def test_ci_disabled_does_not_call_status_endpoints(tmp_path, monkeypatch, resources):
    calls = _provider(monkeypatch, new_status="failure")
    resources.pop("ci")
    receipt = export_gitea_snapshot(run_dir=tmp_path, resources=resources, credentials={})
    assert receipt["complete"]
    assert not any("/commits/" in path for path in calls)
    assert "ci" not in json.loads((tmp_path / "runtime/gitea-evidence.json").read_text())


def test_invalid_status_does_not_produce_complete_receipt(tmp_path, monkeypatch, resources):
    _provider(monkeypatch, new_status="success", malformed=True)
    receipt = export_gitea_snapshot(run_dir=tmp_path, resources=resources, credentials={})
    assert receipt["complete"] is False
    assert not (tmp_path / "runtime/gitea-evidence.json").exists()


def test_collection_excludes_runner_credentials_and_keeps_ci_evidence(tmp_path):
    root = tmp_path / "run"
    for directory in ("runtime", "secrets", "infrastructure/runner-data"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": "run", "config_hash": "hash", "materials": {}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    for path in (".runner", "secrets/registration.env", "infrastructure/runner-data/.runner"):
        (root / path).write_text("private-registration-secret")
    public = {"ci": {"commit_statuses": {NEW: {"state": "failure"}}}}
    (root / "runtime/gitea-evidence.json").write_text(json.dumps(public))
    result = collect_archive(
        run_dir=root,
        manifest=manifest,
        snapshot={"snapshot_dir": str(root), "terminal": True, "consistent": True},
        credentials={},
    )
    assert result["collection_state"] == "COMPLETE"
    with tarfile.open(result["archive"]) as bundle:
        assert "runtime/gitea-evidence.json" in bundle.getnames()
        assert all(".runner" not in name and "secrets/" not in name for name in bundle.getnames())
        assert all(
            b"private-registration-secret" not in bundle.extractfile(p).read() for p in bundle
        )
