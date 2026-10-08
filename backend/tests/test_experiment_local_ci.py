"""Spec-0077/T2: readiness uses real current-head facts and cleanup stays owned."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from auto_designer.experiment.backends import local_ci
from auto_designer.experiment.backends.base import BackendError
from auto_designer.experiment.infrastructure import render_stack


@pytest.fixture
def backend(tmp_path):
    value = SimpleNamespace(
        run_id="RUN",
        digest="a" * 64,
        project="adx-run-aaaaaaaa",
        dest=tmp_path,
        root=tmp_path,
        credentials={"GITEA_TOKEN": "opaque-private-pat"},
        manifest={"config": {"runtime": {"backend": "local", "local": {"ci_enabled": True}}}},
        images={
            "images": {
                "runner": {"image_id": "sha256:runner"},
                "ci_job": {"image_id": "sha256:job"},
                "ci_daemon": {"image_id": "sha256:daemon"},
            }
        },
        resources={"gitea": {"owner": "experiment", "container_id": "gitea-id"}},
        calls=[],
        containers=[],
    )

    def save(**changes):
        value.resources.update(changes)
        return value.resources

    value._save = save
    value._owned = lambda kind: value.containers
    value._compose = lambda *args: value.calls.append(list(args))
    value._ci_command = lambda argv: value.calls.append(argv) or ""
    value.containers = [daemon_fact(value)]
    return value


def daemon_fact(backend):
    return {
        "Id": "daemon-id",
        "Image": "sha256:daemon",
        "State": {"Running": True},
        "Config": {
            "Labels": {
                local_ci.EXPERIMENT_LABEL: backend.run_id,
                local_ci.MANIFEST_LABEL: backend.digest,
                local_ci.ROLE_LABEL: "ci-daemon",
            }
        },
        "NetworkSettings": {"Networks": {backend.project + "_ci": {}}},
        "Mounts": [{"Name": backend.project + "_ci_docker_data", "Destination": "/var/lib/docker"}],
    }


def ci_receipt(backend):
    return {
        "enabled": True,
        "state": "REGISTERED",
        "run_id": backend.run_id,
        "config_hash": backend.digest,
        "network": backend.project + "_ci",
        "runner": {
            "id": 7,
            "name": backend.project + "-ci",
            "container_id": "runner-id",
            "image_id": "sha256:runner",
        },
        "job_image_id": "sha256:job",
        "daemon": {
            "container_id": "daemon-id",
            "image_id": "sha256:daemon",
            "network": backend.project + "_ci",
            "storage_volume": backend.project + "_ci_docker_data",
        },
        "topology": "private-docker-daemon-v1",
        "job_network": "host",
    }


def test_default_stack_does_not_create_runner_and_enabled_stack_is_owned(tmp_path):
    common = dict(experiment_id="RUN", manifest_sha="a" * 64, vigil_image="sha256:vigil")
    path = render_stack(dest=tmp_path / "disabled", **common)
    assert "act-runner:" not in path.read_text()
    path = render_stack(dest=tmp_path / "enabled", ci_enabled=True, **common)
    text = path.read_text()
    assert 'GITEA__actions__ENABLED: "true"' in text
    assert "act-runner:" in text and "runner_data:" in text
    assert "container_name:" not in text and "TOKEN" not in text
    assert "io.openagents.role: ci-runner" in text


def test_job_config_uses_fixed_image_isolated_network_and_labels(backend):
    local_ci.write_config(backend)
    config = json.loads((backend.dest / "runner-config.yaml").read_text())
    assert config["cache"] == {"enabled": False}
    assert config["runner"]["capacity"] == 1
    assert config["runner"]["labels"] == ["ubuntu-latest:docker://sha256:job"]
    assert config["container"]["network"] == "host"
    assert "io.openagents.experiment_id=RUN" in config["container"]["options"]
    assert backend.digest in config["container"]["options"]
    assert config["container"]["docker_host"] == "-"
    assert config["container"]["force_pull"] is False


def test_private_registration_failure_does_not_echo_output(backend, monkeypatch):
    import subprocess

    secret = "registration-secret-that-must-not-leak"
    monkeypatch.setattr(
        local_ci.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, secret, secret),
    )
    with pytest.raises(BackendError) as error:
        local_ci._private_command(["docker", "exec", "registration"], input_text=secret)
    assert secret not in str(error.value)


def test_existing_registration_reuses_identity_without_new_token(backend, monkeypatch):
    backend.resources["ci"] = ci_receipt(backend)
    backend.containers = [
        {
            "Id": "runner-id",
            "Image": "sha256:runner",
            "Config": {"Labels": {"io.openagents.role": "ci-runner"}},
            "State": {"Running": True},
            "NetworkSettings": {"Networks": {backend.project + "_ci": {}}},
        }
    ]
    registration = {
        "id": 7,
        "name": backend.project + "-ci",
        "address": "http://gitea:3000",
        "labels": ["ubuntu-latest:docker://sha256:job"],
        "token": "private-secret",
    }
    private_calls = []
    monkeypatch.setattr(
        local_ci,
        "_private_command",
        lambda argv, **kw: private_calls.append(argv) or json.dumps(registration),
    )
    backend._ci_command = lambda argv: json.dumps([{"Id": argv[-1]}])
    monkeypatch.setattr(local_ci, "_provision_daemon", lambda _: None)
    result = local_ci.provision(backend)
    assert result["ci"]["state"] == "REGISTERED"
    assert result["ci"]["runner"]["id"] == 7
    assert len(private_calls) == 1
    assert "private-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "change", [{"id": 9}, {"address": "http://foreign:3000"}, {"labels": ["wrong"]}]
)
def test_existing_registration_rejects_identity_drift(backend, monkeypatch, change):
    backend.resources["ci"] = ci_receipt(backend)
    registration = {
        "id": 7,
        "name": backend.project + "-ci",
        "address": "http://gitea:3000",
        "labels": ["ubuntu-latest:docker://sha256:job"],
        **change,
    }
    monkeypatch.setattr(local_ci, "_private_command", lambda *args, **kw: json.dumps(registration))
    with pytest.raises(BackendError):
        local_ci._registration(backend, container_id=None)


def probe_api(backend, *, drift=False):
    main, red, green = "1" * 40, "2" * 40, "3" * 40
    reads = 0

    def api(method, path, *, json_data=None):
        nonlocal reads
        backend.calls.append((method, path))
        if path == "/user/repos":
            return {"id": 42}
        if path.endswith("/status"):
            return {
                "state": "failure" if red in path else "success",
                "statuses": [{"context": "smoke"}],
            }
        if "/contents/" in path:
            return {"sha": "blob"} if method == "GET" else {"commit": {"sha": main}}
        if path.endswith("/pulls"):
            return {"number": 5, "head": {"sha": red}}
        if path.endswith("/pulls/5"):
            reads += 1
            return {"number": 5, "head": {"sha": "4" * 40 if drift and reads > 1 else green}}
        return {}

    return api


def test_readiness_requires_red_and_green_current_pr_heads(backend, monkeypatch):
    monkeypatch.setattr(local_ci, "_reader_status", lambda *args, **kwargs: {"verified": True})
    backend.resources["ci"] = ci_receipt(backend)
    backend._api = probe_api(backend)
    result = local_ci.readiness(backend)
    receipt = result["ci"]
    assert receipt["state"] == "READY"
    assert receipt["readiness"]["head_sha"] == "3" * 40
    assert receipt["readiness"]["failed_pr"]["head_sha"] == "2" * 40
    assert receipt["readiness"]["main"]["head_sha"] == "1" * 40
    assert receipt["readiness"]["status_count"] == 1
    assert receipt["probe"]["state"] == "REMOVED"


def test_readiness_does_not_reuse_old_head_success(backend, monkeypatch):
    monkeypatch.setattr(local_ci, "_reader_status", lambda *args, **kwargs: {"verified": True})
    backend.resources["ci"] = ci_receipt(backend)
    backend._api = probe_api(backend, drift=True)
    with pytest.raises(BackendError, match="head changed"):
        local_ci.readiness(backend)
    assert backend.resources["ci"]["state"] == "FAILED"
    assert not any(method == "DELETE" for method, path in backend.calls)


def test_zero_checks_cannot_make_runner_ready(backend, monkeypatch):
    backend.resources["ci"] = ci_receipt(backend)
    backend._api = lambda *args, **kw: {"state": "success", "statuses": []}
    ticks = iter([0, 1, 3])
    monkeypatch.setattr(local_ci.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(local_ci.time, "sleep", lambda _: None)
    with pytest.raises(BackendError, match="timed out"):
        local_ci._wait_status(backend, "/repo", "a" * 40, "success", 2)


def test_nested_cleanup_never_queries_or_removes_host_job_names(backend):
    backend.resources["ci"] = ci_receipt(backend)
    inner_job = {
        "Id": "inner-job",
        "Config": {
            "Labels": {
                local_ci.EXPERIMENT_LABEL: backend.run_id,
                local_ci.MANIFEST_LABEL: backend.digest,
                local_ci.ROLE_LABEL: local_ci.JOB_ROLE,
            }
        },
        "HostConfig": {"NetworkMode": "host"},
    }
    removed = False

    def command(argv):
        nonlocal removed
        backend.calls.append(argv)
        assert argv[:4] == ["docker", "exec", "daemon-id", "docker"]
        args = argv[4:]
        if args == ["ps", "--no-trunc", "-aq"]:
            return "" if removed else "inner-job"
        if args == ["inspect", "inner-job"]:
            return json.dumps([inner_job])
        if args == ["rm", "-f", "-v", "inner-job"]:
            removed = True
        if args == ["volume", "ls", "-q"]:
            return "act-toolcache"
        return ""

    backend._ci_command = command
    result = local_ci.stop(backend)
    assert [
        "docker",
        "exec",
        "daemon-id",
        "docker",
        "volume",
        "rm",
        "act-toolcache",
    ] in backend.calls
    assert result["ci"]["state"] == "STOPPED"
    assert result["ci"]["retained_runner_volume"] == backend.project + "_runner_data"


def test_private_daemon_rejects_forged_host_container_identity(backend):
    backend.resources["ci"] = ci_receipt(backend)
    backend.containers[0]["Config"]["Labels"][local_ci.EXPERIMENT_LABEL] = "other-run"
    with pytest.raises(BackendError, match="identity changed"):
        local_ci._docker(backend, "volume", "ls")
    assert backend.calls == []


def test_resume_does_not_adopt_replaced_private_daemon_container(backend):
    backend.resources["ci"] = ci_receipt(backend)
    backend.containers[0]["Id"] = "replaced-daemon"
    with pytest.raises(BackendError, match="was replaced"):
        local_ci._provision_daemon(backend)
    assert backend.resources["ci"]["daemon"]["container_id"] == "daemon-id"


def test_nested_jobs_must_still_have_matching_run_and_config_labels(backend):
    backend.resources["ci"] = ci_receipt(backend)

    def command(argv):
        return (
            "foreign"
            if argv[-3:] == ["ps", "--no-trunc", "-aq"]
            else json.dumps(
                [{"Id": "foreign", "Config": {"Labels": {}}, "HostConfig": {"NetworkMode": "host"}}]
            )
        )

    backend._ci_command = command
    with pytest.raises(BackendError, match="ownership"):
        local_ci.jobs(backend)


def test_stop_is_idempotent_with_already_stopped_private_daemon(backend):
    backend.resources["ci"] = ci_receipt(backend)
    backend.containers[0]["State"]["Running"] = False
    assert local_ci.stop(backend)["ci"]["state"] == "STOPPED"
    assert not any(call[:2] == ["docker", "exec"] for call in backend.calls)


def test_inspection_requires_original_running_container_and_registration(backend):
    backend.resources["ci"] = {**ci_receipt(backend), "state": "READY"}
    assert local_ci.inspect(backend, [])["state"] == "UNAVAILABLE"
    runner = {"Id": "runner-id", "Image": "different-image", "State": {"Running": True}}
    with pytest.raises(BackendError, match="identity changed"):
        local_ci.inspect(backend, [runner, daemon_fact(backend)])


def test_destroy_removes_only_labelled_private_docker_storage(backend):
    backend.resources["ci"] = ci_receipt(backend)
    own = {
        "Name": backend.project + "_ci_docker_data",
        "Labels": {
            local_ci.EXPERIMENT_LABEL: backend.run_id,
            local_ci.MANIFEST_LABEL: backend.digest,
        },
    }
    backend._owned = lambda kind: [
        own,
        {"Name": backend.project + "_runner_data"},
        {"Name": "unrelated"},
    ]
    local_ci.destroy_storage(backend)
    assert ["docker", "volume", "rm", own["Name"]] in backend.calls
    assert not any(
        "unrelated" in call or backend.project + "_runner_data" in call for call in backend.calls
    )


def test_reader_compares_real_head_and_classification_without_secret_arguments(backend):
    backend.root = backend.dest
    backend.images["images"]["vigil"] = {"image_id": "sha256:frozen-reader"}
    result = {"head_sha": "a" * 40, "state": "fail", "status_count": 1, "ci_state": "failure"}
    backend._ci_command = lambda argv: backend.calls.append(argv) or json.dumps(result)
    actual = local_ci._reader_status(
        backend, "probe", 5, {"head_sha": "a" * 40, "state": "failure"}, deadline=float("inf")
    )
    assert actual == result
    assert "--env-file" in backend.calls[-1]
    assert "opaque-private-pat" not in " ".join(backend.calls[-1])
    assert "sha256:frozen-reader" in backend.calls[-1]
    result["head_sha"] = "b" * 40
    with pytest.raises(BackendError, match="did not confirm"):
        local_ci._reader_status(
            backend, "probe", 5, {"head_sha": "a" * 40, "state": "failure"}, deadline=float("inf")
        )


def test_reader_env_uses_docker_literal_token_semantics_and_only_one_selected_key(backend):
    import stat
    from pathlib import Path

    directory = backend.root / "secrets"
    directory.mkdir()
    (directory / "provider.env").write_text(
        "GITEA_TOKEN='opaque-private-pat'\nGITEA_PASSWORD='password'\n"
    )
    backend.credentials["GITEA_PASSWORD"] = "password"
    path = Path(local_ci._reader_environment(backend))
    assert path.read_text() == "GITEA_TOKEN=opaque-private-pat\n"
    # Docker keeps quotes literal, unlike the shell-quoted provider receipt.
    parsed = dict(line.split("=", 1) for line in path.read_text().splitlines())
    assert parsed == {"GITEA_TOKEN": backend.credentials["GITEA_TOKEN"]}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o666)
    local_ci._reader_environment(backend)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("token", ["", "pat\nextra", "pat\rextra", "pat\x00extra"])
def test_reader_env_rejects_invalid_values_before_writing(backend, token):
    backend.credentials["GITEA_TOKEN"] = token
    with pytest.raises(BackendError, match="valid private"):
        local_ci._reader_environment(backend)
    assert not (backend.root / "secrets/ci-reader.env").exists()


def test_reader_env_refuses_to_follow_a_symlink(backend):
    directory = backend.root / "secrets"
    directory.mkdir()
    outside = backend.root / "unrelated.txt"
    outside.write_text("preserved")
    (directory / "ci-reader.env").symlink_to(outside)
    with pytest.raises(BackendError, match="could not be written"):
        local_ci._reader_environment(backend)
    assert outside.read_text() == "preserved"


@pytest.mark.parametrize(
    "transient",
    [
        {"state": "pending", "status_count": 1, "ci_state": "pending"},
        {"state": "pass", "status_count": 0, "ci_state": "none"},
    ],
)
def test_reader_retries_only_same_head_transient_status_until_expected_red(
    backend, monkeypatch, transient
):
    backend.images["images"]["vigil"] = {"image_id": "sha256:frozen-reader"}
    head = "a" * 40
    replies = iter(
        [
            {"head_sha": head, **transient},
            {"head_sha": head, "state": "fail", "status_count": 1, "ci_state": "failure"},
        ]
    )
    backend._ci_command = lambda argv: backend.calls.append(argv) or json.dumps(next(replies))
    monkeypatch.setattr(local_ci.time, "sleep", lambda seconds: None)
    result = local_ci._reader_status(
        backend, "probe", 5, {"head_sha": head, "state": "failure"}, deadline=float("inf")
    )
    assert result["ci_state"] == "failure"
    assert len(backend.calls) == 2
    assert backend.resources["ci"]["reader_observation"]["head_sha"] == head


@pytest.mark.parametrize(
    "unexpected,reason",
    [
        (
            {"head_sha": "b" * 40, "state": "pending", "status_count": 0, "ci_state": "none"},
            "head changed",
        ),
        (
            {"head_sha": "a" * 40, "state": "pass", "status_count": 1, "ci_state": "success"},
            "terminal classification",
        ),
    ],
)
def test_reader_records_and_rejects_wrong_head_or_opposite_terminal_without_retry(
    backend, monkeypatch, unexpected, reason
):
    backend.images["images"]["vigil"] = {"image_id": "sha256:frozen-reader"}
    backend._ci_command = lambda argv: (
        backend.calls.append(argv) or json.dumps({**unexpected, "secret_extra_field": "excluded"})
    )
    monkeypatch.setattr(local_ci.time, "sleep", lambda seconds: pytest.fail("should not retry"))
    with pytest.raises(BackendError, match=reason):
        local_ci._reader_status(
            backend, "probe", 5, {"head_sha": "a" * 40, "state": "failure"}, deadline=float("inf")
        )
    assert len(backend.calls) == 1
    assert backend.resources["ci"]["reader_observation"]["head_sha"] == unexpected["head_sha"]
    assert "secret_extra_field" not in backend.resources["ci"]["reader_observation"]


def test_jobs_skips_only_container_proven_to_have_disappeared(backend):
    backend.resources["ci"] = ci_receipt(backend)
    head_job = {
        "Id": "live-job",
        "Config": {
            "Labels": {
                local_ci.EXPERIMENT_LABEL: backend.run_id,
                local_ci.MANIFEST_LABEL: backend.digest,
                local_ci.ROLE_LABEL: local_ci.JOB_ROLE,
            }
        },
        "HostConfig": {"NetworkMode": "host"},
    }
    listings = iter(["gone-job\nlive-job", "live-job"])

    def command(argv):
        args = argv[4:]
        if args == ["ps", "--no-trunc", "-aq"]:
            return next(listings)
        if args == ["inspect", "gone-job"]:
            raise BackendError("Docker operation failed")
        if args == ["inspect", "live-job"]:
            return json.dumps([head_job])
        pytest.fail(str(args))

    backend._ci_command = command
    assert local_ci.jobs(backend) == [head_job]
    assert backend.resources["ci"]["job_container_ids"] == ["live-job"]


@pytest.mark.parametrize("transport_failed", [False, True])
def test_jobs_does_not_swallow_live_inspect_or_daemon_transport_error(backend, transport_failed):
    backend.resources["ci"] = ci_receipt(backend)
    reads = 0

    def command(argv):
        nonlocal reads
        args = argv[4:]
        if args == ["ps", "--no-trunc", "-aq"]:
            reads += 1
            if reads > 1 and transport_failed:
                raise BackendError("daemon transport unavailable")
            return "live-job"
        if args == ["inspect", "live-job"]:
            raise BackendError("inspect genuinely failed")
        pytest.fail(str(args))

    backend._ci_command = command
    with pytest.raises(
        BackendError,
        match="transport unavailable" if transport_failed else "inspect genuinely failed",
    ):
        local_ci.jobs(backend)


def test_stop_accepts_auto_removed_job_but_only_after_fresh_observation(backend):
    backend.resources["ci"] = ci_receipt(backend)
    gone = False
    job = {
        "Id": "finished-job",
        "Config": {
            "Labels": {
                local_ci.EXPERIMENT_LABEL: backend.run_id,
                local_ci.MANIFEST_LABEL: backend.digest,
                local_ci.ROLE_LABEL: local_ci.JOB_ROLE,
            }
        },
        "HostConfig": {"NetworkMode": "host"},
    }

    def command(argv):
        nonlocal gone
        args = argv[4:]
        if args == ["ps", "--no-trunc", "-aq"]:
            return "" if gone else "finished-job"
        if args == ["inspect", "finished-job"]:
            return json.dumps([job])
        if args == ["rm", "-f", "-v", "finished-job"]:
            gone = True
            raise BackendError("auto-removal won race")
        if args == ["volume", "ls", "-q"]:
            return ""
        pytest.fail(str(args))

    backend._ci_command = command
    assert local_ci.stop(backend)["ci"]["state"] == "STOPPED"


def test_stop_keeps_failure_if_job_removal_failed_and_job_remains(backend):
    backend.resources["ci"] = ci_receipt(backend)
    job = {
        "Id": "live-job",
        "Config": {
            "Labels": {
                local_ci.EXPERIMENT_LABEL: backend.run_id,
                local_ci.MANIFEST_LABEL: backend.digest,
                local_ci.ROLE_LABEL: local_ci.JOB_ROLE,
            }
        },
        "HostConfig": {"NetworkMode": "host"},
    }

    def command(argv):
        args = argv[4:]
        if args == ["ps", "--no-trunc", "-aq"]:
            return "live-job"
        if args == ["inspect", "live-job"]:
            return json.dumps([job])
        if args == ["rm", "-f", "-v", "live-job"]:
            raise BackendError("removal genuinely failed")
        pytest.fail(str(args))

    backend._ci_command = command
    with pytest.raises(BackendError, match="removal genuinely failed"):
        local_ci.stop(backend)
    assert backend.resources["ci"]["state"] == "REGISTERED"
