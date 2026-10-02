"""Run dashboard reads real local/snapshot stores without provider or model calls."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from auto_designer.experiment import dashboard, runtime
from auto_designer.experiment.config import ConfigError, config_hash
from auto_designer.experiment.materials import sha256_file
from auto_designer.models import FeelingScore, Persona, SeedScenario, Session, Transcript
from auto_designer.usage import UsageStore
from auto_designer.user.session_store import SessionStore
from test_experiment_config_v2 import definition, write


def frozen_run(tmp_path, backend="local"):
    run = tmp_path / "selected-run"
    run.mkdir()
    config = definition()
    if backend == "e2b":
        config["runtime"] = {
            "backend": "e2b",
            "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
            "e2b": {"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 86400},
        }
    material = write(run / "materials/input.json", {"frozen": True})
    write(
        run / "manifest.json",
        {
            "schema_version": 2,
            "run_id": run.name,
            "experiment_id": run.name,
            "run_dir": str(run),
            "config": config,
            "config_hash": config_hash(data=config),
            "controller_sha": "a" * 40,
            "plan_hash": sha256_file(material),
            "materials": {
                "input": {"path": "materials/input.json", "sha256": sha256_file(material)}
            },
        },
    )
    return run


def observations(root, run_id, session_id="current-session"):
    data = root / "data"
    role_runs = data / "role_runs" / run_id
    SessionStore(role_runs / "sessions").save(
        Session(
            persona=Persona(
                identity="developer",
                level="intermediate",
                domain="Python",
                goal="fix",
                speaking_style="direct",
            ),
            scenario=SeedScenario(description="Fix visible issue"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=3, reason="tested"),
            session_id=session_id,
        )
    )
    UsageStore(role_runs / "usage.jsonl").append(
        {
            "run_id": run_id,
            "session_id": session_id,
            "role": "user",
            "total_tokens": 23,
        }
    )
    write(data / "live/run.json", {"round": 2, "running": True, "total_rounds": 5})
    write(data / "live/history.json", [{"round": 1, "agent_id": "current"}])
    write(
        data / "live/agents.json",
        {"current": {"agent_id": "current", "role": "user", "running": True}},
    )
    return data


@pytest.fixture(autouse=True)
def forbid_provider(monkeypatch):
    monkeypatch.setattr(runtime, "backend_v2", lambda **kw: pytest.fail("no provider discovery"))


def test_local_api_reads_only_selected_run_and_frozen_roster(tmp_path, monkeypatch):
    run = frozen_run(tmp_path)
    data = observations(run, run.name)
    # A sessions alias and process role env must not change the selected run's observations.
    other = tmp_path / "other"
    observations(other, "other", "unrelated-session")
    (data / "sessions").symlink_to(other / "data/role_runs/other/sessions")
    monkeypatch.setenv("N_USERS", "99")
    monkeypatch.setattr(
        "auto_designer.web.api.default_usage_store", lambda: pytest.fail("default usage")
    )
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    assert [s["session_id"] for s in client.get("/api/sessions").json()] == ["current-session"]
    assert client.get("/api/state").json()["round"] == 2
    assert client.get("/api/history").json()["items"][0]["agent_id"] == "current"
    assert client.get("/api/agents").json()["agents"][0]["agent_id"] == "current"
    assert client.get("/api/config").json()["roster"]["user"] == 1
    assert client.get("/api/usage/summary").json()["total_tokens"] == 23
    assert client.get("/api/usage/events").json()["events"][0]["run_id"] == run.name
    assert client.get("/api/runmeta").json()["source"] == "local-live"
    assert client.get("/api/issues").json()["connected"] is False


def snapshot(run):
    cloud = run / "runtime/cloud-snapshot"
    data = observations(cloud, run.name)
    inventory = {
        p.relative_to(cloud).as_posix(): sha256_file(p)
        for p in cloud.rglob("*")
        if p.is_file() and not p.name.endswith(".lock")
    }
    # Production collection excludes the SessionStore lock.
    (data / "role_runs" / run.name / "sessions/.sessions.lock").unlink()
    write(
        run / "runtime/e2b-collection.json",
        {
            "snapshot_dir": str(cloud),
            "files": inventory,
            "collected_at": "2026-10-03T01:00:00Z",
            "consistent": True,
            "terminal": False,
        },
    )
    return cloud


def stage_refresh(run):
    staged = run / "runtime/next-snapshot"
    data = observations(staged, run.name, "refreshed-session")
    (data / "role_runs" / run.name / "sessions/.sessions.lock").unlink()
    write(data / "live/run.json", {"round": 5, "running": False, "total_rounds": 5})
    receipt = {
        "snapshot_dir": str(run / "runtime/cloud-snapshot"),
        "files": {
            p.relative_to(staged).as_posix(): sha256_file(p)
            for p in staged.rglob("*")
            if p.is_file()
        },
        "collected_at": "2026-10-03T02:00:00Z",
        "consistent": True,
        "terminal": True,
    }
    return staged, receipt


def publish_snapshot_directory(run, staged):
    shutil.rmtree(run / "runtime/cloud-snapshot")
    staged.rename(run / "runtime/cloud-snapshot")


def test_e2b_refresh_updates_data_and_source_metadata_together(tmp_path, monkeypatch):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    assert client.get("/api/runmeta").json()["terminal"] is False
    staged, receipt = stage_refresh(run)
    publish_snapshot_directory(run, staged)
    write(run / "runtime/e2b-collection.json", receipt)
    assert [s["session_id"] for s in client.get("/api/sessions").json()] == ["refreshed-session"]
    assert client.get("/api/state").json()["round"] == 5
    assert client.get("/api/usage/events").json()["events"][0]["session_id"] == "refreshed-session"
    metadata = client.get("/api/runmeta").json()
    assert metadata["collected_at"] == receipt["collected_at"]
    assert metadata["terminal"] is True
    # An unchanged generation uses the verified inventory cache, not repeated file hashing.
    monkeypatch.setattr(
        dashboard, "sha256_file", lambda path: pytest.fail("unchanged generation rehashed")
    )
    assert client.get("/api/runmeta").status_code == 200
    assert client.get("/api/sessions").status_code == 200


def test_e2b_partial_snapshot_publication_returns_503_until_receipt(tmp_path):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    staged, receipt = stage_refresh(run)
    publish_snapshot_directory(run, staged)
    for endpoint in ("/api/sessions", "/api/runmeta", "/api/state", "/api/usage/events"):
        response = client.get(endpoint)
        assert response.status_code == 503
        assert "refreshed-session" not in response.text
        assert "2026-10-03T01:00:00Z" not in response.text
    write(run / "runtime/e2b-collection.json", receipt)
    assert client.get("/api/runmeta").json()["collected_at"] == receipt["collected_at"]


def test_e2b_corrupt_refresh_does_not_serve_new_data_with_old_time(tmp_path):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    staged, receipt = stage_refresh(run)
    publish_snapshot_directory(run, staged)
    (run / "runtime/cloud-snapshot/data/live/run.json").write_text("{}")
    write(run / "runtime/e2b-collection.json", receipt)
    for endpoint in ("/api/sessions", "/api/runmeta", "/api/state"):
        response = client.get(endpoint)
        assert response.status_code == 503
        assert "refreshed-session" not in response.text
        assert "2026-10-03T01:00:00Z" not in response.text


def test_e2b_collection_during_request_rejects_mixed_generation(tmp_path, monkeypatch):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    staged, receipt = stage_refresh(run)
    original = SessionStore.index

    def index(store, *args, **kwargs):
        publish_snapshot_directory(run, staged)
        write(run / "runtime/e2b-collection.json", receipt)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(SessionStore, "index", index)
    assert client.get("/api/sessions").status_code == 503
    assert client.get("/api/runmeta").json()["collected_at"] == receipt["collected_at"]


def test_e2b_api_uses_collected_slice_and_marks_snapshot(tmp_path):
    run = frozen_run(tmp_path, "e2b")
    cloud = snapshot(run)
    observations(run, run.name, "host-stale-session")
    (cloud / "data/sessions").symlink_to(tmp_path / "uncontrolled")
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    assert [s["session_id"] for s in client.get("/api/sessions").json()] == ["current-session"]
    assert client.get("/api/state").json()["round"] == 2
    assert client.get("/api/usage/summary").json()["total_tokens"] == 23
    metadata = client.get("/api/runmeta").json()
    assert metadata["source"] == "collected-snapshot"
    assert metadata["collected_at"] == "2026-10-03T01:00:00Z"
    assert str(tmp_path) not in json.dumps(metadata)


def test_e2b_without_collect_rejects_without_provider(tmp_path):
    run = frozen_run(tmp_path, "e2b")
    with pytest.raises(ConfigError, match="collect RUN_ID"):
        dashboard.dashboard_app(run_id=run.name, root=tmp_path)


def test_recorded_gitea_without_token_keeps_offline_data(tmp_path, monkeypatch):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    write(
        run / "resources.json",
        {
            "gitea": {"url": "https://gitea.com", "owner": "actual", "repo": "experiment"},
        },
    )
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.setattr(dashboard, "GiteaTracker", lambda **kw: pytest.fail("no credentials"))
    client = TestClient(dashboard.dashboard_app(run_id=run.name, root=tmp_path))
    assert client.get("/api/usage/summary").json()["total_tokens"] == 23
    assert client.get("/api/issues").json() == {
        "connected": False,
        "board_url": "https://gitea.com/actual/experiment/issues",
        "issues": [],
    }
    assert client.get("/api/runmeta").json()["gitea_credentials_available"] is False


def test_changed_snapshot_is_rejected(tmp_path):
    run = frozen_run(tmp_path, "e2b")
    cloud = snapshot(run)
    (cloud / "data/live/run.json").write_text("{}")
    with pytest.raises(ConfigError, match="checksum changed"):
        dashboard.dashboard_app(run_id=run.name, root=tmp_path)


def test_credentials_bind_recorded_gitea_without_leaking(tmp_path, monkeypatch):
    run = frozen_run(tmp_path)
    write(
        run / "resources.json",
        {"gitea": {"url": "https://gitea.com", "owner": "actual", "repo": "experiment"}},
    )
    secret = run / "secrets/provider.env"
    secret.parent.mkdir()
    secret.write_text("GITEA_TOKEN=private-dashboard-token\n")
    secret.chmod(0o600)
    seen = {}

    class Tracker:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def list_open_issues(self):
            return []

    monkeypatch.setattr(dashboard, "GiteaTracker", Tracker)
    client = TestClient(
        dashboard.dashboard_app(run_id=run.name, root=tmp_path, secrets_file=secret)
    )
    assert seen == {
        "base_url": "https://gitea.com",
        "owner": "actual",
        "repo": "experiment",
        "token": "private-dashboard-token",
    }
    for endpoint in ("/api/runmeta", "/api/issues", "/api/config", "/api/state"):
        assert "private-dashboard-token" not in client.get(endpoint).text
    assert client.get("/api/issues").json()["connected"] is True


@pytest.mark.parametrize("run_id", ["../escape", "missing-run"])
def test_invalid_run_rejects(tmp_path, run_id):
    with pytest.raises((ConfigError, ValueError)):
        dashboard.dashboard_app(run_id=run_id, root=tmp_path)


def test_old_manifest_rejects(tmp_path):
    write(tmp_path / "historical/manifest.json", {"schema_version": 1, "run_id": "historical"})
    with pytest.raises(ConfigError, match="frozen checkout"):
        dashboard.dashboard_app(run_id="historical", root=tmp_path)


def test_modified_frozen_input_rejects(tmp_path):
    run = frozen_run(tmp_path)
    (run / "materials/input.json").write_text("tampered")
    with pytest.raises(ConfigError, match="hash mismatch"):
        dashboard.dashboard_app(run_id=run.name, root=tmp_path)


def test_selected_sessions_symlink_rejects(tmp_path):
    run = frozen_run(tmp_path)
    role_runs = run / "data/role_runs" / run.name
    role_runs.mkdir(parents=True)
    (role_runs / "sessions").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ConfigError, match="escapes|symbolic"):
        dashboard.dashboard_app(run_id=run.name, root=tmp_path)


def test_server_defaults_and_snapshot_notice(tmp_path, monkeypatch, capsys):
    run = frozen_run(tmp_path, "e2b")
    snapshot(run)
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: seen.update(kwargs))
    dashboard.serve_dashboard(run_id=run.name, root=tmp_path)
    assert seen == {"host": "127.0.0.1", "port": 8000}
    assert "cloud activity is not live" in capsys.readouterr().err


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_server_port_rejects_before_loading_run(port):
    with pytest.raises(ConfigError, match="--port"):
        dashboard.serve_dashboard(run_id="unprepared", port=port)
