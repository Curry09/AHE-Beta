"""Spec-0069/T3: observed ownership, dynamic addresses and honest local state."""

from __future__ import annotations

import json
import sys
import time

import pytest

from auto_designer.experiment.backends import local
from auto_designer.experiment.backends.base import BackendError
from auto_designer.experiment.infrastructure import LABEL_EXPERIMENT, LABEL_MANIFEST


@pytest.fixture
def backend(tmp_path, monkeypatch):
    run_id = "20260930T123000Z-1234abcd"
    digest = "a" * 64
    config = {
        "rounds": {"count": 2},
        "runtime": {
            "backend": "local",
            "gitea": {"provider": "localhost", "repository_prefix": "n1"},
        },
        "models": {
            role: {"base_url_env": "MODEL_URL", "api_key_env": "MODEL_KEY", "model": "test"}
            for role in ("user", "harness", "demand", "delivery")
        },
    }
    manifest = {
        "run_id": run_id,
        "config_hash": digest,
        "config": config,
        "task_package": {"id": "task", "source": {"kind": "git", "revision": "b" * 40}},
    }
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/local-images.json").write_text(
        json.dumps(
            {
                "images": {
                    name: {"image_id": "sha256:" + name}
                    for name in ("gitea", "egress", "vigil", "seed")
                },
                "source_root": str(tmp_path / "source/controller"),
                "controller_python": "/frozen/python",
            }
        )
    )
    selected = local.LocalBackend(
        tmp_path,
        manifest,
        {"GITEA_TOKEN": "private-provider-key", "MODEL_URL": "http://35.220.164.252:3888/v1"},
    )
    calls = []
    labels = {
        LABEL_EXPERIMENT: run_id,
        LABEL_MANIFEST: digest,
        "com.docker.compose.project": selected.project,
    }
    facts = {"containers": [], "volumes": [], "networks": []}

    def command(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["docker", "ps", "-aq"]:
            return "\n".join(value["Id"] for value in facts["containers"])
        if argv[:3] == ["docker", "volume", "ls"]:
            return "\n".join(value["Name"] for value in facts["volumes"])
        if argv[:3] == ["docker", "network", "ls"]:
            return "\n".join(value["Id"] for value in facts["networks"])
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps(facts["containers"])
        if argv[:3] == ["docker", "volume", "inspect"]:
            return json.dumps(facts["volumes"])
        if argv[:3] == ["docker", "network", "inspect"]:
            return json.dumps(facts["networks"])
        if argv[:2] == ["docker", "compose"]:
            if "up" in argv:
                prepared_env = dict(
                    line.split("=", 1)
                    for line in (selected.dest / "compose.env").read_text().splitlines()
                )
                requested_port = int(prepared_env["GITEA_HOST_PORT"])
                facts.setdefault("up_ports", []).append(requested_port)
                actual_port = requested_port or facts.get("next_dynamic_port", 49173)
                if not facts["volumes"]:
                    facts["volumes"] = [
                        {"Name": selected.project + "_gitea_data", "Labels": labels}
                    ]
                facts["containers"] = [
                    {
                        "Id": "gitea-id",
                        "Name": "/gitea",
                        "Config": {"Labels": {**labels, "io.openagents.role": "gitea"}},
                        "State": {"Running": True},
                        "NetworkSettings": {
                            "Ports": {
                                "3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(actual_port)}]
                            }
                        },
                    },
                    {
                        "Id": "egress-id",
                        "Name": "/egress",
                        "Config": {"Labels": {**labels, "io.openagents.role": "egress"}},
                        "State": {"Running": True},
                    },
                ]
            if "stop" in argv:
                for fact in facts["containers"]:
                    fact["State"]["Running"] = False
            if "down" in argv:
                facts["containers"] = []
            return ""
        if argv[:3] == ["docker", "rm", "-f"]:
            facts["containers"] = [
                value for value in facts["containers"] if value["Id"] != argv[-1]
            ]
            return ""
        if argv[:2] == ["docker", "run"]:
            if "observation-capabilities" in argv:
                return json.dumps(
                    {"encodings": ["gzip", "zip"], "download_policies": ["same-origin-v1"]}
                )
            if argv[-3:] == ["git", "rev-parse", "HEAD"]:
                return "b" * 40
            return "Python 3.12.13"
        raise AssertionError(argv)

    repositories = {}

    def api(method, endpoint, *, json_data=None):
        if endpoint == "/user":
            return {"login": "experiment"}
        if method == "GET":
            return repositories.get(endpoint, {})
        created = {
            "id": 7,
            "owner": {"login": "experiment"},
            "description": json_data["description"],
        }
        repositories["/repos/experiment/" + json_data["name"]] = created
        return created

    class Ready:
        status_code = 200

    monkeypatch.setattr(local, "_command", command)
    monkeypatch.setattr(local.requests, "get", lambda *args, **kwargs: Ready())
    monkeypatch.setattr(selected, "_api", api)
    monkeypatch.setattr(selected, "_probe", lambda: {"status": "verified"})
    from auto_designer.experiment import collection

    monkeypatch.setattr(
        collection, "export_gitea_snapshot", lambda **kwargs: {"applicable": True, "complete": True}
    )
    return selected, calls, facts, labels


def test_provision_uses_actual_dynamic_port_and_only_infrastructure(backend):
    selected, calls, _, _ = backend
    result = selected.provision()
    assert result["gitea"]["url"] == "http://127.0.0.1:49173"
    assert result["gitea"]["internal_url"] == "http://gitea:3000"
    assert result["gitea"]["repository_id"] == 7
    assert result["vigil"]["network"] == selected.project + "_vigil_net"
    assert result["workspace"]["params"]["network"] == selected.project + "_vigil_net"
    assert result["workspace"]["params"]["env"]["HTTPS_PROXY"] == "http://egress-proxy:3128"
    assert selected.project == selected.project.lower()
    compose_up = next(argv for argv in calls if "up" in argv)
    assert compose_up[-4:] == ["up", "-d", "gitea", "egress-proxy"]
    assert "act-runner" not in (selected.dest / "docker-compose.yml").read_text()
    assert "\n  vigil:" not in (selected.dest / "docker-compose.yml").read_text()
    assert "private-provider-key" not in (selected.root / "resources.json").read_text()


def test_new_local_account_records_actual_browser_login_privately(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    selected.credentials.pop("GITEA_TOKEN")
    secret_dir = selected.root / "secrets"
    secret_dir.mkdir(mode=0o755)
    calls = []

    def admin(argv, **kwargs):
        calls.append(argv)
        return "new-account-private-token-123456789" if "generate-access-token" in argv else ""

    monkeypatch.setattr(local, "_command", admin)
    selected._bootstrap_account("owned-gitea-id")
    login = secret_dir / "local-gitea-login.env"
    create = next(argv for argv in calls if "create" in argv)
    used_password = create[create.index("--password") + 1]
    assert login.read_text() == f"GITEA_USER=experiment\nGITEA_PASSWORD={used_password}\n"
    assert login.stat().st_mode & 0o777 == 0o600
    assert secret_dir.stat().st_mode & 0o777 == 0o700
    assert selected.credentials["GITEA_PASSWORD"] == used_password
    assert selected.resources["gitea"]["login_file"] == "secrets/local-gitea-login.env"
    selected._save()
    assert used_password not in (selected.root / "resources.json").read_text()
    assert selected.credentials["GITEA_TOKEN"] not in (selected.root / "resources.json").read_text()


def test_token_failure_and_retry_preserve_successful_account_login(backend, monkeypatch):
    selected, _, _, _ = backend
    calls = []
    account_exists = False
    token_attempts = 0

    def admin(argv, **kwargs):
        nonlocal account_exists, token_attempts
        calls.append(argv)
        if argv[-1] == "list":
            return "1 experiment experiment@localhost.invalid" if account_exists else ""
        if "create" in argv:
            account_exists = True
            return ""
        if "generate-access-token" in argv:
            token_attempts += 1
            if token_attempts == 1:
                raise BackendError("simulated token failure")
            return "b" * 40
        raise AssertionError(argv)

    monkeypatch.setattr(local, "_command", admin)
    with pytest.raises(BackendError, match="simulated token failure"):
        selected._bootstrap_account("owned-gitea-id")
    login = selected.root / "secrets/local-gitea-login.env"
    before = login.read_bytes()
    selected._bootstrap_account("owned-gitea-id")
    assert login.read_bytes() == before
    assert sum("create" in argv for argv in calls) == 1
    assert selected.credentials["GITEA_PASSWORD"] in before.decode()
    assert selected.credentials["GITEA_TOKEN"] == "b" * 40


def test_existing_local_account_without_record_does_not_invent_login(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    calls = []

    def admin(argv, **kwargs):
        calls.append(argv)
        return "1 experiment" if argv[-1] == "list" else "c" * 40

    monkeypatch.setattr(local, "_command", admin)
    selected._bootstrap_account("owned-gitea-id")
    assert not any("create" in argv for argv in calls)
    assert not (selected.root / "secrets/local-gitea-login.env").exists()
    assert "GITEA_PASSWORD" not in selected.credentials
    assert "login_file" not in selected.resources["gitea"]


def test_resume_loads_browser_login_independently_of_provider_receipt(backend):
    selected, _, _, _ = backend
    selected.provision()
    directory = selected.root / "secrets"
    directory.mkdir(mode=0o700)
    login = directory / "local-gitea-login.env"
    login.write_text("GITEA_USER=experiment\nGITEA_PASSWORD=actual-created-password\n")
    login.chmod(0o600)
    (directory / "provider.env").write_text("GITEA_TOKEN=provider-overwritten-by-monitor\n")
    credentials = {"GITEA_TOKEN": "already-loaded-token"}
    resumed = local.LocalBackend(selected.root, selected.manifest, credentials)
    assert credentials["GITEA_PASSWORD"] == "actual-created-password"
    assert credentials["GITEA_TOKEN"] == "already-loaded-token"
    # A provision rebuilds gitea metadata and must restore only the login path.
    assert selected.provision()["gitea"]["login_file"] == "secrets/local-gitea-login.env"
    assert resumed.resources["gitea"]["login_file"] == "secrets/local-gitea-login.env"


def test_failed_account_create_does_not_record_unusable_login(backend, monkeypatch):
    selected, _, _, _ = backend

    def admin(argv, **kwargs):
        if "create" in argv:
            raise BackendError("simulated create failure")
        return ""

    monkeypatch.setattr(local, "_command", admin)
    with pytest.raises(BackendError, match="simulated create failure"):
        selected._bootstrap_account("owned-gitea-id")
    assert not (selected.root / "secrets/local-gitea-login.env").exists()
    assert "GITEA_PASSWORD" not in selected.credentials


def test_local_login_record_refuses_public_permissions(backend):
    selected, _, _, _ = backend
    directory = selected.root / "secrets"
    directory.mkdir(mode=0o700)
    login = directory / "local-gitea-login.env"
    login.write_text("GITEA_USER=experiment\nGITEA_PASSWORD=actual-created-password\n")
    login.chmod(0o644)
    with pytest.raises(BackendError, match="private regular file"):
        local.LocalBackend(selected.root, selected.manifest, {})


def test_creation_intent_survives_provider_failure(backend, monkeypatch):
    selected, _, _, _ = backend

    def failed(*args):
        raise BackendError("provider offline")

    monkeypatch.setattr(selected, "_compose", failed)
    with pytest.raises(BackendError, match="offline"):
        selected.provision()
    receipt = json.loads((selected.root / "resources.json").read_text())
    assert receipt["resource_state"] == "PROVISIONING"
    assert receipt["run_id"] == selected.run_id


def test_repeated_provision_reuses_run_identity_and_repository(backend):
    selected, _, _, _ = backend
    first = selected.provision()["gitea"].copy()
    second = selected.provision()["gitea"].copy()
    assert first == second


def test_existing_repository_requires_server_side_ownership(backend, monkeypatch):
    selected, _, _, _ = backend

    def api(method, endpoint, **kwargs):
        return (
            {"login": "experiment"}
            if endpoint == "/user"
            else {"id": 99, "description": "not ours", "owner": {"login": "experiment"}}
        )

    monkeypatch.setattr(selected, "_api", api)
    monkeypatch.setattr(selected, "_probe", lambda: {"status": "verified"})
    from auto_designer.experiment import collection

    monkeypatch.setattr(
        collection, "export_gitea_snapshot", lambda **kwargs: {"applicable": True, "complete": True}
    )
    with pytest.raises(BackendError, match="ownership"):
        selected.provision()


def test_preflight_does_not_call_a_model_and_requires_real_task_head(backend, monkeypatch):
    selected, calls, _, _ = backend
    selected.provision()
    result = selected.preflight()
    assert result["preflight"]["task_base_commit"] == "b" * 40
    assert not any("MODEL_KEY" in repr(argv) for argv in calls)
    original = local._command

    def wrong_head(argv, **kwargs):
        return "c" * 40 if argv[-3:] == ["git", "rev-parse", "HEAD"] else original(argv, **kwargs)

    monkeypatch.setattr(local, "_command", wrong_head)
    with pytest.raises(BackendError, match="base commit"):
        selected.preflight()


def test_infrastructure_alive_does_not_mean_controller_alive(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "ABSENT", "running": False}
    )
    result = selected.inspect()
    assert result["resource_state"] == "RUNNING"
    assert result["controller"]["state"] == "ABSENT"
    assert result["vigil_running"] is False


def test_provider_unreachable_does_not_claim_resource_lost(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()

    def unavailable(*args):
        raise BackendError("Docker unavailable")

    monkeypatch.setattr(selected, "_owned", unavailable)
    result = selected.inspect()
    assert result["resource_state"] == "UNKNOWN"
    assert result["observation"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["container", "network", "volume"])
def test_destroy_refuses_observed_cross_run_ownership(backend, kind):
    selected, calls, facts, labels = backend
    selected.provision()
    if kind == "container":
        facts["containers"][0]["Config"]["Labels"][LABEL_MANIFEST] = "foreign"
    else:
        facts[kind + "s"] = [
            {
                "Id": "foreign",
                "Name": "foreign",
                "Labels": {**labels, LABEL_EXPERIMENT: "other-run"},
            }
        ]
    calls.clear()
    with pytest.raises(BackendError, match="ownership"):
        selected.destroy()
    assert not any("down" in argv or argv[:3] == ["docker", "rm", "-f"] for argv in calls)


def test_stop_reaps_only_owned_vigil_and_sessions(backend, monkeypatch):
    selected, calls, facts, labels = backend
    selected.provision()
    facts["containers"].append(
        {
            "Id": "session-id",
            "Config": {"Labels": {**labels, "auto-designer.session": "session"}},
            "State": {"Running": True},
        }
    )
    # The shared runner always labels Vigil with its run ID, independently of
    # Compose; after a forced runner exit this is the cleanup ownership handle.
    facts["containers"].append(
        {
            "Id": "vigil-id",
            "Name": "/" + selected.resources["vigil"]["container"],
            "Config": {"Labels": {**labels, "io.auto-designer.run_id": selected.run_id}},
            "State": {"Running": True},
        }
    )
    monkeypatch.setattr(
        local, "stop_controller", lambda *args, **kwargs: {"state": "STOPPED", "running": False}
    )
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "STOPPED", "running": False}
    )
    result = selected.stop()
    assert ["docker", "rm", "-f", "session-id"] in calls
    assert ["docker", "rm", "-f", "vigil-id"] in calls
    assert ["docker", "rm", "-f", "egress-id"] not in calls
    assert ["docker", "rm", "-f", "gitea-id"] not in calls
    assert result["resource_state"] == "STOPPED"


def test_destroy_preserves_repository_volume(backend):
    selected, calls, facts, labels = backend
    selected.provision()
    facts["volumes"] = [{"Name": "owned_gitea_data", "Labels": labels}]
    result = selected.destroy()
    down = next(argv for argv in calls if "down" in argv)
    assert "--volumes" not in down
    assert result["retained_volumes"] == ["owned_gitea_data"]
    assert result["repository_retained"] is True


def test_destroy_refuses_live_controller(backend, monkeypatch):
    selected, calls, _, _ = backend
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "RUNNING", "running": True}
    )
    with pytest.raises(BackendError, match="Stop"):
        selected.destroy()
    assert calls == []


def test_collect_omits_secrets_git_venvs_and_live_build_context(backend, monkeypatch):
    selected, _, _, _ = backend
    for relative in (
        "secrets/provider.env",
        "data/harness/.git/config",
        "data/task/.venv/key",
        "runtime/image-build/task/key",
        "data/results.json",
        "checkpoints/recovery.json",
        "logs/controller.log",
    ):
        path = selected.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    monkeypatch.setattr(
        local,
        "inspect_controller",
        lambda root: {"state": "EXITED", "running": False, "nonce": "same"},
    )
    result = selected.collect()
    assert result["terminal"] and result["consistent"]
    assert set(result["files"]) >= {
        "data/results.json",
        "checkpoints/recovery.json",
        "logs/controller.log",
    }
    assert not any(
        "secrets" in name or ".git" in name or ".venv" in name or "image-build" in name
        for name in result["files"]
    )


def test_live_collection_is_explicitly_non_terminal(backend, monkeypatch):
    selected, _, _, _ = backend
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "RUNNING", "running": True}
    )
    assert selected.collect()["terminal"] is False


def test_egress_is_exact_and_accepts_nonstandard_model_ports():
    models = {role: {"base_url_env": role} for role in ("delivery", "harness")}
    rules = local.render_egress(
        {"models": models},
        {"delivery": "https://model.example/v1", "harness": "http://35.220.164.252:3888/v1"},
    )
    assert "dst 35.220.164.252" in rules
    assert "dstdomain model.example" in rules
    assert "port 3888" in rules
    assert "http_access allow all" not in rules
    assert "acl SSL_ports port 443 3888" in rules


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@model.example",
        "ftp://model.example",
        "https://model.example\nhttp_access allow all",
    ],
)
def test_egress_rejects_credential_and_config_injection(url):
    with pytest.raises(BackendError):
        local.render_egress({"models": {"delivery": {"base_url_env": "URL"}}}, {"URL": url})


def test_source_archives_reject_links_and_traversal(tmp_path):
    import tarfile

    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        entry = tarfile.TarInfo("outside")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "/tmp/private"
        bundle.addfile(entry)
    with pytest.raises(BackendError, match="Unsafe"):
        local._extract(archive, tmp_path / "extracted")


def test_real_transport_probe_uses_scoped_token_and_removes_technical_repo(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    seen = []

    def api(method, endpoint, *, json_data=None, files=None):
        seen.append((method, endpoint, json_data, files))
        if method == "GET":
            return {}
        if endpoint.endswith("/issues"):
            return {"number": 2}
        if endpoint.endswith("/assets"):
            import gzip

            payload = json.loads(gzip.decompress(files["attachment"][1]))
            assert payload["format"] == "auto-designer:observation-evidence-v1"
            assert payload["issue"] == 2
            return {"id": 4}
        return {"id": 1}

    def command(argv, **kwargs):
        import hashlib

        value = json.loads(argv[-1])
        assert "private-provider-key" not in repr(argv)
        assert kwargs["env"]["GITEA_TOKEN"] == "private-provider-key"
        assert argv[argv.index("--network") + 1] == selected.resources["vigil"]["network"]
        assert "download_observation_asset" in argv[-2]
        assert "encoding='gzip'" in argv[-2]
        uploaded = next(row[3]["attachment"][1] for row in seen if row[1].endswith("/assets"))
        assert value["sha256"] == hashlib.sha256(uploaded).hexdigest()
        return json.dumps({"status": "verified", "issue": 2, "sha256": value["sha256"]})

    monkeypatch.setattr(selected, "_api", api)
    monkeypatch.setattr(local, "_command", command)
    assert local.LocalBackend._probe(selected)["status"] == "verified"
    assert seen[-1][0] == "DELETE"
    assert seen[-1][1].startswith("/repos/experiment/preflight-")
    assert selected.resources["probe_state"] == "REMOVED"


def test_real_transport_probe_cleanup_runs_after_reader_failure(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    methods = []

    def api(method, endpoint, **kwargs):
        methods.append(method)
        if method == "GET":
            return {}
        return {"number": 1, "id": 2}

    def failed(*args, **kwargs):
        raise BackendError("actual reader failed")

    monkeypatch.setattr(selected, "_api", api)
    monkeypatch.setattr(local, "_command", failed)
    with pytest.raises(BackendError, match="reader failed"):
        local.LocalBackend._probe(selected)
    assert methods[-1] == "DELETE"


def test_stop_retains_infrastructure_if_terminal_gitea_export_fails(backend, monkeypatch):
    from auto_designer.experiment import collection

    selected, calls, _, _ = backend
    selected.provision()
    calls.clear()
    monkeypatch.setattr(
        local, "stop_controller", lambda *args, **kwargs: {"state": "STOPPED", "running": False}
    )
    monkeypatch.setattr(
        collection,
        "export_gitea_snapshot",
        lambda **kwargs: {"applicable": True, "complete": False},
    )
    with pytest.raises(BackendError, match="retained"):
        selected.stop()
    assert not any("stop" in argv for argv in calls)


def test_terminal_inventory_ignores_collector_monitor_files(backend):
    selected, _, _, _ = backend
    for relative in (
        "runtime/collection-stage-123/logs/monitor.log",
        "logs/monitor.log",
        "logs/collector.log",
        "runtime/collection.json",
        "runtime/monitor.json",
        "data/real-result.json",
    ):
        path = selected.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("result")
    files = selected._snapshot_files()
    assert "data/real-result.json" in files
    assert not any(
        "monitor" in name or "collection" in name or "collector" in name for name in files
    )


def test_prepare_builds_only_frozen_sources_and_never_passes_credentials(tmp_path, monkeypatch):
    import tarfile

    controller = tmp_path / "source/controller"
    (controller / "backend/deploy/vigil").mkdir(parents=True)
    (controller / "backend/deploy/vigil/Dockerfile").write_text("FROM fixed AS unified-vigil\n")
    materials = {}
    for key in ("controller_source_archive", "openagents_source_archive", "task_source_archive"):
        path = tmp_path / "materials" / (key + ".tar.gz")
        path.parent.mkdir(exist_ok=True)
        with tarfile.open(path, "w:gz"):
            pass
        materials[key] = {
            "path": str(path.relative_to(tmp_path)),
            "sha256": local.sha256_file(path),
        }
    for key in ("script", "requirements_lock"):
        path = tmp_path / "materials" / key
        path.write_text("# frozen\n")
        materials[key] = {
            "path": str(path.relative_to(tmp_path)),
            "sha256": local.sha256_file(path),
        }
    manifest = {
        "config": {"runtime": {"backend": "local"}},
        "materials": materials,
        "task_package": {"id": "fixed-task", "source": {"kind": "local", "path": "source/task"}},
        "task_source_snapshot": {"files": {}},
        "run_dir": str(tmp_path),
        "source_pins": {"nexau": {"revision": "n" * 40}},
    }
    monkeypatch.setattr(local, "verify_materials", lambda **kwargs: None)
    monkeypatch.setattr(local, "materialize_controller_source", lambda *args: controller)
    monkeypatch.setattr(local.shutil, "which", lambda name: "/usr/local/bin/uv")
    calls = []

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0].endswith("/uv") and "--version" in argv:
            return "uv 0.11.28"
        if argv[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "sha256:" + argv[-1],
                        "Config": {"Labels": {"org.auto-designer.seed-runtime": "1"}},
                    }
                ]
            )
        if "observation-capabilities" in argv:
            return json.dumps({"encodings": ["gzip"], "download_policies": ["same-origin-v1"]})
        if argv[:2] == ["docker", "run"] and "-c" in argv:
            return json.dumps({"verified": True, "nexau_commit": "n" * 40})
        return ""

    monkeypatch.setattr(local, "_command", command)
    result = local.prepare_images(
        tmp_path, manifest, {"MODEL_KEY": "never-in-build", "GITEA_TOKEN": "private"}
    )
    assert result["controller_python"] == str(controller / ".venv/bin/python")
    assert {argv[argv.index("--target") + 1] for argv, _ in calls if "--target" in argv} == {
        "unified-seed",
        "unified-vigil",
    }
    assert not any("never-in-build" in repr(call) or "private" in repr(call) for call in calls)
    assert any(
        "--locked" in argv and "--extra" in argv and "experiments" in argv for argv, _ in calls
    )
    assert (
        json.loads((tmp_path / "runtime/local-images.json").read_text())["recipe"]
        == local.RECIPE_VERSION
    )


def test_harness_launcher_uses_controller_python_while_task_shell_is_separate(
    tmp_path, monkeypatch
):
    from auto_designer.harness import launcher
    from auto_designer.user.sim.runtime import DockerWorkspaceRuntime

    product = tmp_path / "harness"
    product.mkdir()
    runtime = DockerWorkspaceRuntime(
        container_id="owned",
        container_name="owned",
        image="fixed",
        image_digest="fixed",
        cwd="/workspace/task/repo",
    )
    runtime.evidence["harness_python"] = "/opt/controller/.venv/bin/python"
    runtime.evidence["proxy_environment"] = {
        "HTTP_PROXY": "http://egress-proxy:3128",
        "HTTPS_PROXY": "http://egress-proxy:3128",
        "NO_PROXY": "gitea,127.0.0.1,localhost",
    }
    monkeypatch.setenv("NO_PROXY", "model.example,host-only")
    monkeypatch.setenv("no_proxy", "model.example,host-only")
    monkeypatch.setenv("HTTP_PROXY", "http://host-only:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://host-only:9999")
    # The model destination remains valid even when its hostname also appeared
    # in the host's NO_PROXY. Only proxy routing is replaced inside Docker.
    monkeypatch.setenv("LLM_BASE_URL", "https://model.example/v1")
    selected = launcher.HarnessLauncher(str(tmp_path), tmp_path / "runs")
    monkeypatch.setattr(selected, "_resolve_sha", lambda **kwargs: "b" * 40)
    monkeypatch.setattr(selected, "_checkout", lambda **kwargs: product)
    monkeypatch.setattr(selected, "_read_params", lambda dest: {"entry": ["python3", "entry.py"]})
    monkeypatch.setattr(runtime, "stage_directory", lambda *args: None)
    invocation = {}

    def handle(**kwargs):
        invocation.update(kwargs)
        return type("Handle", (), {})()

    monkeypatch.setattr(launcher, "_HarnessHandle", handle)
    selected.launch("main", runtime)
    argv = invocation["entry"]
    assert "/opt/controller/.venv/bin/python" in argv
    assert "python3" not in argv
    assert "SANDBOX_WORK_DIR=/workspace/task/repo" in argv
    proxy_names = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"}
    proxies = {
        item.partition("=")[0]: item.partition("=")[2]
        for index, item in enumerate(argv)
        if index > 0 and argv[index - 1] == "-e" and item.partition("=")[0] in proxy_names
    }
    assert proxies == runtime.evidence["proxy_environment"]
    assert "LLM_BASE_URL=https://model.example/v1" in argv


def test_vigil_ready_checks_actual_process_and_workspace_not_only_docker_state(
    backend, monkeypatch
):
    selected, _, facts, labels = backend
    selected.provision()
    facts["containers"].append(
        {
            "Id": "vigil-id",
            "Name": "/" + selected.resources["vigil"]["container"],
            "Config": {"Labels": {**labels, "io.auto-designer.run_id": selected.run_id}},
            "State": {"Running": True},
        }
    )
    original = local._command
    seen = []

    def command(argv, **kwargs):
        if argv[:5] == ["docker", "exec", "--user", "root", "vigil-id"]:
            seen.append(argv[-1])
            return "ready"
        return original(argv, **kwargs)

    monkeypatch.setattr(local, "_command", command)
    assert selected._vigil_ready()
    assert "str(os.getpid())" in seen[0]
    assert "/work/harness/.openagents/openagents.yml" in seen[0]
    assert "int(uid)==expected" in seen[0]


def test_vigil_ready_script_rejects_root_or_wrong_worker_uid(backend, tmp_path, monkeypatch):
    selected, _, facts, labels = backend
    selected.provision()
    facts["containers"].append(
        {
            "Id": "vigil-id",
            "Name": "/" + selected.resources["vigil"]["container"],
            "Config": {"Labels": {**labels, "io.auto-designer.run_id": selected.run_id}},
            "State": {"Running": True},
        }
    )
    proc = tmp_path / "proc/987654321"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"openagents\x00vigil\x00")
    config = tmp_path / "openagents.yml"
    config.write_text("version: 1\n")
    monkeypatch.setenv("VIGIL_EXEC_UID", "1201")
    original = local._command

    def command(argv, **kwargs):
        if argv[:5] != ["docker", "exec", "--user", "root", "vigil-id"]:
            return original(argv, **kwargs)
        script = argv[-1].replace("Path('/proc')", f"Path({str(proc.parent)!r})")
        script = script.replace("'/work/harness/.openagents/openagents.yml'", repr(str(config)))
        try:
            exec(compile(script, "readiness", "exec"), {})
        except AssertionError as exc:
            raise BackendError("Not ready") from exc
        return "ready"

    monkeypatch.setattr(local, "_command", command)
    for uid in (0, 1000, 1201):
        (proc / "status").write_text(f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        assert selected._vigil_ready() is (uid == 1201)


def test_cloud_prebuilt_harness_inherits_task_shell_env_with_controller_interpreter(
    tmp_path, monkeypatch
):
    import sys

    from auto_designer.harness import launcher
    from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

    product = tmp_path / "harness"
    product.mkdir()
    runtime = LocalWorkspaceRuntime(str(tmp_path / "task"))
    runtime.evidence.update(
        task_virtual_env="/workspace/session/.venv", harness_python="/frozen/controller/python"
    )
    selected = launcher.HarnessLauncher(str(tmp_path), tmp_path / "runs")
    monkeypatch.setattr(selected, "_resolve_sha", lambda **kwargs: "b" * 40)
    monkeypatch.setattr(selected, "_checkout", lambda **kwargs: product)
    monkeypatch.setattr(selected, "_read_params", lambda dest: {"entry": ["python3", "entry.py"]})
    invocation = {}

    def handle(**kwargs):
        invocation.update(kwargs)
        return type("Handle", (), {})()

    monkeypatch.setattr(launcher, "_HarnessHandle", handle)
    selected.launch("main", runtime)
    assert invocation["entry"][0] == "/frozen/controller/python"
    assert invocation["env"]["VIRTUAL_ENV"] == "/workspace/session/.venv"
    assert invocation["env"]["PATH"].startswith("/workspace/session/.venv/bin:")
    assert sys.executable not in invocation["env"]["PATH"].split(":")


def test_launch_requires_real_vigil_before_reporting_running(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "ABSENT", "running": False}
    )
    monkeypatch.setattr(
        local, "build_controller_environment", lambda **kwargs: {"PATH": "/usr/bin"}
    )
    monkeypatch.setattr(
        local, "controller_command", lambda *args: ["/frozen/python", "controller.py"]
    )
    monkeypatch.setattr(
        local,
        "launch_controller",
        lambda **kwargs: {"state": "RUNNING", "running": True, "runner_pid": 123},
    )
    monkeypatch.setattr(selected, "_vigil_ready", lambda: True)
    receipt = selected.launch()
    assert receipt["state"] == "RUNNING"
    assert receipt["vigil_ready"] is True


def test_launch_rejects_controller_that_exits_before_vigil_ready(backend, monkeypatch):
    selected, _, _, _ = backend
    selected.provision()
    observed = iter([{"state": "ABSENT", "running": False}, {"state": "EXITED", "running": False}])
    monkeypatch.setattr(local, "inspect_controller", lambda root: next(observed))
    monkeypatch.setattr(
        local, "build_controller_environment", lambda **kwargs: {"PATH": "/usr/bin"}
    )
    monkeypatch.setattr(
        local, "controller_command", lambda *args: ["/frozen/python", "controller.py"]
    )
    monkeypatch.setattr(
        local,
        "launch_controller",
        lambda **kwargs: {"state": "RUNNING", "running": True, "runner_pid": 123},
    )
    monkeypatch.setattr(selected, "_vigil_ready", lambda: False)
    monkeypatch.setattr(local.time, "sleep", lambda seconds: None)
    with pytest.raises(BackendError, match="exited before"):
        selected.launch()


def test_single_round_finishes_without_waiting_for_absent_vigil(backend, monkeypatch):
    # Spec-0072/T3: a real supervised runner seals its only round with no delivery.
    selected, _, _, _ = backend
    selected.provision()
    selected.manifest["config"]["rounds"]["count"] = 1
    (selected.root / "manifest.json").write_text(json.dumps(selected.manifest))
    selected.resources["controller_python"] = sys.executable
    program = """import json,pathlib,sys,time
root=pathlib.Path(sys.argv[1]);run_id=sys.argv[2]
time.sleep(0.2)
target=root/'data/role_runs'/run_id;target.mkdir(parents=True)
(target/'manifest.json').write_text(json.dumps({'rounds':[{'round':1,'sealed_sha':'done'}]}))
(root/'checkpoints').mkdir()
(root/'checkpoints/recovery.json').write_text(json.dumps({'rounds':{'1':{'status':'completed','sealed_sha':'done'}}}))
"""
    monkeypatch.setattr(local, "build_controller_environment", lambda **kwargs: {})
    monkeypatch.setattr(
        local,
        "controller_command",
        lambda *args: [sys.executable, "-c", program, str(selected.root), selected.run_id],
    )
    readiness = pytest.fail
    monkeypatch.setattr(selected, "_vigil_ready", readiness)
    try:
        selected.launch()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            receipt = local.inspect_controller(selected.root)
            if "exit_code" in receipt:
                break
            time.sleep(0.05)
        assert receipt["exit_code"] == 0
        assert receipt["experiment_complete"] is True
        assert receipt["sealed_rounds"] == [1]
    finally:
        local.stop_controller(selected.root, grace_seconds=1)


def test_vigil_toolchain_rejects_wrong_actual_nexau_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(
        local,
        "_command",
        lambda *args, **kwargs: json.dumps({"verified": True, "nexau_commit": "wrong"}),
    )
    with pytest.raises(BackendError, match="source pins"):
        local._verify_toolchain("immutable-image", tmp_path, "5" * 40)


def test_stop_refuses_foreign_execution_container_before_any_removal(backend, monkeypatch):
    selected, calls, facts, labels = backend
    selected.provision()
    facts["containers"].append(
        {
            "Id": "foreign-vigil",
            "Name": "/" + selected.resources["vigil"]["container"],
            "Config": {
                "Labels": {
                    **labels,
                    LABEL_EXPERIMENT: "foreign-run",
                    "io.auto-designer.run_id": "foreign-run",
                }
            },
            "State": {"Running": True},
        }
    )
    monkeypatch.setattr(
        local, "stop_controller", lambda *args, **kwargs: {"state": "STOPPED", "running": False}
    )
    calls.clear()
    with pytest.raises(BackendError, match="ownership"):
        selected.stop()
    assert not any(argv[:3] == ["docker", "rm", "-f"] or "stop" in argv for argv in calls)
    assert facts["containers"][-1]["Id"] == "foreign-vigil"


def test_prepare_command_streams_private_log_before_child_exits(tmp_path):
    import concurrent.futures
    import stat
    import sys
    import time

    log = tmp_path / "prepare.log"
    log.touch()
    log.chmod(0o666)
    release = tmp_path / "release-child"
    program = """import pathlib,sys,time
print('build started',flush=True)
while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)
print('build finished',file=sys.stderr,flush=True)
"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        child = executor.submit(
            local._command, [sys.executable, "-c", program, str(release)], log_path=log, timeout=10
        )
        try:
            deadline = time.monotonic() + 5
            while "build started" not in log.read_text() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert "build started" in log.read_text()
            assert not child.done(), "the log must be readable while the build still runs"
            assert stat.S_IMODE(log.stat().st_mode) == 0o600
        finally:
            release.touch()
        assert child.result(timeout=5) == ""
    assert "build finished" in log.read_text()


def test_prepare_timeout_retains_partial_log_without_exposing_arguments(tmp_path):
    import sys

    log = tmp_path / "prepare.log"
    program = "import time; print('download started',flush=True); time.sleep(5)"
    with pytest.raises(BackendError, match="timed out") as failure:
        local._command(
            [sys.executable, "-c", program, "secret-provider-argument"], log_path=log, timeout=0.2
        )
    assert "download started" in log.read_text()
    assert "secret-provider-argument" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_prepare_failure_keeps_private_stderr_and_plain_commands_keep_stdout(tmp_path):
    import sys

    log = tmp_path / "prepare.log"
    with pytest.raises(BackendError, match="exit 3") as failure:
        local._command(
            [
                sys.executable,
                "-c",
                "import sys; print('private-download-error',file=sys.stderr); sys.exit(3)",
            ],
            log_path=log,
        )
    assert "private-download-error" in log.read_text()
    assert "private-download-error" not in str(failure.value)
    assert local._command([sys.executable, "-c", "print('small reply')"]) == "small reply"


def test_default_egress_reference_matches_compose_and_is_immutable(tmp_path):
    from auto_designer.experiment.infrastructure import COMPOSE_TEMPLATE

    assert "@sha256:" in local.DEFAULT_EGRESS_IMAGE
    assert ":latest" not in local.DEFAULT_EGRESS_IMAGE
    assert local.DEFAULT_EGRESS_IMAGE in COMPOSE_TEMPLATE.read_text()
    local.render_stack(
        dest=tmp_path,
        experiment_id="proxy-default-proof",
        manifest_sha="test",
        vigil_image="unused",
    )
    assert "EGRESS_IMAGE=" + local.DEFAULT_EGRESS_IMAGE in (tmp_path / "compose.env").read_text()


@pytest.mark.parametrize("replacement", [None, 8])
def test_resume_never_recreates_or_replaces_recorded_repository(backend, monkeypatch, replacement):
    selected, _, _, _ = backend
    selected.provision()
    calls = []
    previous = selected.resources["gitea"].copy()

    def api(method, endpoint, **kwargs):
        calls.append((method, endpoint))
        if endpoint == "/user":
            return {"login": "experiment"}
        if replacement is None:
            return {}
        return {
            "id": replacement,
            "owner": {"login": "experiment"},
            "description": f"auto-designer experiment {selected.run_id} config {selected.digest}",
        }

    monkeypatch.setattr(selected, "_api", api)
    with pytest.raises(BackendError, match="missing|replaced"):
        selected.provision()
    assert not any(method == "POST" for method, _ in calls)
    persisted = json.loads((selected.root / "resources.json").read_text())
    assert persisted["gitea"]["repository_id"] == previous["repository_id"]
    assert persisted["gitea"]["repo"] == previous["repo"]
    assert "repo_id" not in persisted["gitea"]
    # A second resume still refuses instead of forgetting the old identity.
    with pytest.raises(BackendError, match="missing|replaced"):
        selected.provision()
    assert not any(method == "POST" for method, _ in calls)


def test_development_repo_id_normalizes_to_repository_id_on_resume(backend):
    selected, _, _, _ = backend
    selected.provision()
    selected.resources["gitea"]["repo_id"] = selected.resources["gitea"].pop("repository_id")
    result = selected.provision()
    assert result["gitea"]["repository_id"] == 7
    assert "repo_id" not in result["gitea"]


def test_stop_and_resume_keep_first_observed_gitea_origin(backend, monkeypatch):
    selected, _, facts, _ = backend
    first = selected.provision()["gitea"].copy()
    assert first["host_port"] == 49173
    assert first["canonical_url"] == "http://127.0.0.1:49173"
    assert facts["up_ports"] == [0]
    monkeypatch.setattr(
        local, "stop_controller", lambda *args, **kwargs: {"state": "STOPPED", "running": False}
    )
    monkeypatch.setattr(
        local, "inspect_controller", lambda root: {"state": "STOPPED", "running": False}
    )
    selected.stop()
    facts["next_dynamic_port"] = 55555
    second = selected.provision()["gitea"].copy()
    assert facts["up_ports"] == [0, 49173]
    assert first["url"] == second["url"] == second["canonical_url"]
    assert first["repository_id"] == second["repository_id"]
    assert "GITEA_HOST_PORT=49173" in (selected.dest / "compose.env").read_text()


def _frozen_local_profile(selected, url):
    from auto_designer.observations.transport import make_transport_profile

    observations = selected.root / "data/role_runs" / selected.run_id / "observations"
    observations.mkdir(parents=True, exist_ok=True)
    repository = url + "/api/v1/repos/experiment/" + selected.resources["gitea"]["repo"]
    profile = observations / ".transport-profile.json"
    profile.write_text(json.dumps(make_transport_profile(repository=repository)))
    (observations / ".framework-contract.json").write_text(
        json.dumps(
            {
                "format": "artifact-observations-v1",
                "repository": repository,
                "max_transfer_bytes": 4_000_000,
            }
        )
    )
    return profile


def test_development_dynamic_port_mismatch_restores_frozen_origin_with_identity_proof(backend):
    selected, _, facts, _ = backend
    selected.provision()
    profile = _frozen_local_profile(selected, "http://127.0.0.1:49173")
    original = profile.read_bytes()
    selected.resources["gitea"].pop("host_port")
    selected.resources["gitea"].pop("canonical_url")
    selected.resources["gitea"]["url"] = "http://127.0.0.1:55555"
    facts["containers"][0]["NetworkSettings"]["Ports"]["3000/tcp"][0]["HostPort"] = "55555"
    result = selected.provision()
    assert facts["up_ports"] == [0, 49173]
    assert result["gitea"]["url"] == "http://127.0.0.1:49173"
    assert result["gitea"]["host_port"] == 49173
    assert result["gitea"]["repository_id"] == 7
    assert profile.read_bytes() == original


def test_frozen_port_recovery_refuses_replaced_live_repository_before_compose_up(
    backend, monkeypatch
):
    selected, calls, facts, _ = backend
    selected.provision()
    profile = _frozen_local_profile(selected, "http://127.0.0.1:49173")
    original = profile.read_bytes()
    selected.resources["gitea"].pop("host_port")
    selected.resources["gitea"].pop("canonical_url")
    selected.resources["gitea"]["url"] = "http://127.0.0.1:55555"
    monkeypatch.setattr(selected, "_api", lambda *args, **kwargs: {"id": 99})
    calls.clear()
    with pytest.raises(BackendError, match="identity"):
        selected.provision()
    assert not any("up" in argv for argv in calls)
    assert facts["up_ports"] == [0]
    assert profile.read_bytes() == original


@pytest.mark.parametrize(
    "unsafe",
    [
        "http://127.0.0.2:49173",
        "https://127.0.0.1:49173",
        "http://credential@127.0.0.1:49173",
        "http://127.0.0.1:49173/other-repo",
    ],
)
def test_frozen_origin_cannot_redirect_resume_to_another_service(backend, unsafe):
    selected, calls, _, _ = backend
    selected.provision()
    _frozen_local_profile(selected, unsafe)
    calls.clear()
    with pytest.raises(BackendError, match="binding"):
        selected.provision()
    assert not any("up" in argv for argv in calls)


def test_occupied_canonical_port_fails_without_changing_identity_or_profile(backend, monkeypatch):
    selected, _, _, _ = backend
    first = selected.provision()["gitea"].copy()
    profile = _frozen_local_profile(selected, first["url"])
    original = profile.read_bytes()

    def port_in_use(*args):
        assert "GITEA_HOST_PORT=49173" in (selected.dest / "compose.env").read_text()
        raise BackendError("Canonical port is already occupied")

    monkeypatch.setattr(selected, "_compose", port_in_use)
    with pytest.raises(BackendError, match="occupied"):
        selected.provision()
    assert selected.resources["gitea"]["url"] == first["url"]
    assert selected.resources["gitea"]["host_port"] == first["host_port"]
    assert selected.resources["gitea"]["repository_id"] == first["repository_id"]
    assert profile.read_bytes() == original
