"""Spec-0077/T1: optional local engineering CI fails closed before the controller."""

from __future__ import annotations

import copy
import io
import json
import tarfile
from pathlib import Path

import pytest

from auto_designer.experiment import materials
from auto_designer.experiment.config import (
    ConfigError,
    compose_project,
    config_hash,
    load_config_v2,
    local_ci_enabled,
)
from auto_designer.experiment.context import build_controller_environment
from test_experiment_config_v2 import definition, load_fixture_config, write
from test_experiment_engine import prepared as prepared
from test_experiment_materials import prepared_inputs as prepared_inputs

WORKFLOW = b"""name: smoke
on:
  pull_request:
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 -m compileall -q .
"""


def _enable(path: Path, **settings):
    document = json.loads(path.read_text())
    document["runtime"]["local"] = {"ci_enabled": True, **settings}
    write(path, document)
    return document


def _archive(path: Path, contents: dict[str, bytes]):
    with tarfile.open(path, "w:gz") as archive:
        for name, value in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    return path


def _archive_config(path: Path, archive: Path):
    document = json.loads(path.read_text())
    document["harness"] = {
        "source": "archive",
        "archive": str(archive),
        "sha256": materials.sha256_file(archive),
    }
    write(path, document)


def _receipt(manifest):
    project = compose_project(
        experiment_id=manifest["run_id"].lower(), cfg_hash=manifest["config_hash"]
    )
    return {
        "enabled": True,
        "state": "READY",
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "runner": {
            "id": 7,
            "name": "experiment-runner",
            "container_id": "d" * 64,
            "image_id": "sha256:" + "e" * 64,
        },
        "job_image_id": "sha256:" + "f" * 64,
        "network": project + "_ci",
        "topology": "private-docker-daemon-v1",
        "job_network": "host",
        "daemon": {
            "container_id": "a" * 64,
            "image_id": "sha256:" + "b" * 64,
            "network": project + "_ci",
            "storage_volume": project + "_ci_docker_data",
        },
        "readiness": {
            "head_sha": "b" * 40,
            "status_count": 1,
            "state": "success",
            "checked_at": "2026-10-03T01:02:03+00:00",
        },
    }


@pytest.mark.parametrize("local", [None, {}, {"ci_enabled": False}])
def test_omitted_or_disabled_ci_adds_no_frozen_defaults(tmp_path, local):
    document = definition()
    if local is not None:
        document["runtime"]["local"] = local
    expected_runtime = copy.deepcopy(document["runtime"])
    config = load_fixture_config(write(tmp_path / "config.json", document))
    assert config["runtime"] == expected_runtime
    before = config_hash(data=config)
    assert not local_ci_enabled(config)
    assert config_hash(data=config) == before
    assert "runner_image" not in config["runtime"].get("local", {})
    assert "ci_job_image" not in config["runtime"].get("local", {})


def test_old_frozen_hash_remains_stable():
    frozen = {
        "schema_version": 2,
        "runtime": {
            "backend": "local",
            "gitea": {"provider": "localhost", "repository_prefix": "old"},
        },
    }
    assert not local_ci_enabled(frozen)
    assert (
        config_hash(data=frozen)
        == "d19573e0e79eaccc0de3fc0caa16d8ddf2a068cf8f2914e49f31c97cbc5bc608"
    )


def test_legacy_frozen_ci_helper_accepts_absent_runtime():
    frozen = {"schema_version": 2, "workload": {"kind": "ordinary"}}
    before = copy.deepcopy(frozen)
    before_hash = config_hash(data=frozen)
    assert not local_ci_enabled(frozen)
    assert frozen == before
    assert config_hash(data=frozen) == before_hash


@pytest.mark.parametrize("flag", [True, False])
def test_local_ci_boolean_is_accepted(tmp_path, flag):
    document = definition()
    document["runtime"]["local"] = {"ci_enabled": flag}
    config = load_fixture_config(write(tmp_path / "config.json", document))
    assert config["runtime"]["local"]["ci_enabled"] is flag


@pytest.mark.parametrize("flag", ["true", 0, 1, None, []])
def test_ci_flag_rejects_non_boolean(tmp_path, flag):
    document = definition()
    document["runtime"]["local"] = {"ci_enabled": flag}
    with pytest.raises(ConfigError, match="boolean"):
        load_fixture_config(write(tmp_path / "config.json", document))


@pytest.mark.parametrize("image_field", ["runner_image", "ci_job_image"])
@pytest.mark.parametrize(
    "image",
    ["gitea/act_runner:0.2.11", "registry.example:5000/job:v1-RC", "job@sha256:" + "a" * 64],
)
def test_ci_images_require_and_preserve_version_or_digest(tmp_path, image_field, image):
    document = definition()
    document["runtime"]["local"] = {"ci_enabled": True, image_field: image}
    config = load_fixture_config(write(tmp_path / "config.json", document))
    assert config["runtime"]["local"][image_field] == image


@pytest.mark.parametrize("image_field", ["runner_image", "ci_job_image"])
@pytest.mark.parametrize(
    "image",
    ["job", "registry.example:5000/job", "job:latest", "job:", "job@sha256:abc", "job:1\nBAD=1"],
)
def test_unpinned_or_malformed_ci_images_are_rejected(tmp_path, image_field, image):
    document = definition()
    document["runtime"]["local"] = {"ci_enabled": True, image_field: image}
    with pytest.raises(ConfigError, match="explicit version"):
        load_fixture_config(write(tmp_path / "config.json", document))


@pytest.mark.parametrize(
    "local", [{"runner_image": "runner:1"}, {"ci_enabled": False, "ci_job_image": "job:1"}]
)
def test_ci_images_cannot_be_configured_while_disabled(tmp_path, local):
    document = definition()
    document["runtime"]["local"] = local
    with pytest.raises(ConfigError, match="requires ci_enabled=true"):
        load_fixture_config(write(tmp_path / "config.json", document))


@pytest.mark.parametrize("local", [{}, {"ci_enabled": False}, {"ci_enabled": True}])
def test_e2b_still_forbids_all_local_settings(tmp_path, local):
    document = definition()
    document["runtime"] = {
        "backend": "e2b",
        "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
        "e2b": {"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600},
        "local": local,
    }
    with pytest.raises(ConfigError, match="local settings are forbidden"):
        load_config_v2(write(tmp_path / "config.json", document))


def test_builtin_ci_workflow_check_is_offline(prepared_inputs, tmp_path, monkeypatch):
    _enable(prepared_inputs)
    before = {str(path) for path in tmp_path.rglob("*")}
    monkeypatch.setattr(materials, "_checkout_git", lambda **kwargs: pytest.fail("network access"))
    report = materials.check_materials(prepared_inputs)
    assert report["ok"]
    assert before == {str(path) for path in tmp_path.rglob("*")}


def test_missing_builtin_ci_workflow_fails_before_prepare_fetch(
    prepared_inputs, tmp_path, monkeypatch
):
    _enable(prepared_inputs)
    controller = tmp_path / "controller"
    seed = controller / "backend/harness_template"
    seed.mkdir(parents=True)
    (seed / "entry.py").write_text("pass\n")
    monkeypatch.setattr(materials, "_controller_root", lambda: controller)
    monkeypatch.setattr(materials, "_checkout_git", lambda **kwargs: pytest.fail("network access"))
    with pytest.raises(ConfigError, match=".gitea/workflows"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_archive_ci_checks_actual_selected_harness(prepared_inputs, tmp_path):
    _enable(prepared_inputs)
    archive = _archive(tmp_path / "harness.tar.gz", {"entry.py": b"pass\n"})
    _archive_config(prepared_inputs, archive)
    with pytest.raises(ConfigError, match=".gitea/workflows"):
        materials.check_materials(prepared_inputs)
    _archive(archive, {"entry.py": b"pass\n", ".gitea/workflows/smoke.yml": WORKFLOW})
    _archive_config(prepared_inputs, archive)
    assert materials.check_materials(prepared_inputs)["ok"]


def test_changed_harness_is_rejected_during_freeze_before_fetch(
    prepared_inputs, tmp_path, monkeypatch
):
    _enable(prepared_inputs)
    original = materials._archive_snapshot

    def archive_snapshot(*, root, files, destination):
        if destination.name == "harness.tar.gz":
            _archive(destination, {"entry.py": b"pass"})
        else:
            original(root=root, files=files, destination=destination)

    monkeypatch.setattr(materials, "_archive_snapshot", archive_snapshot)
    monkeypatch.setattr(materials, "_checkout_git", lambda **kwargs: pytest.fail("network access"))
    with pytest.raises(ConfigError, match=".gitea/workflows"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert not list((tmp_path / "runs").glob("20*"))
    assert not list((tmp_path / "runs").glob(".preparing-*"))


def test_frozen_ci_archive_is_rechecked_on_verification(prepared_inputs, tmp_path):
    _enable(prepared_inputs)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    materials.verify_materials(manifest)
    record = manifest["materials"]["harness_archive"]
    archive = Path(manifest["run_dir"]) / record["path"]
    _archive(archive, {"entry.py": b"pass"})
    record["sha256"] = materials.sha256_file(archive)
    with pytest.raises(ConfigError, match=".gitea/workflows"):
        materials.verify_materials(manifest)


@pytest.mark.parametrize(
    "trigger",
    ["pull_request", "[push, pull_request]", "{pull_request: {}}", "{pull_request: null}"],
)
def test_supported_pr_trigger_forms_are_accepted(tmp_path, trigger):
    workflow = WORKFLOW.replace(b"on:\n  pull_request:", f"on: {trigger}".encode())
    archive = _archive(
        tmp_path / "harness.tar.gz", {"entry.py": b"pass", ".gitea/workflows/smoke.yaml": workflow}
    )
    materials._check_ci_archive(path=archive)


@pytest.mark.parametrize(
    "workflow",
    [
        b"[unterminated",
        b"name: duplicate\nname: duplicate\n",
        b"[not, a, workflow]",
        WORKFLOW.replace(b"pull_request:", b"push:"),
        WORKFLOW.replace(b"pull_request:", b"pull_request: {paths: ['src/**']}"),
        WORKFLOW.replace(b"ubuntu-latest", b"windows-latest"),
        WORKFLOW.replace(b"runs-on: ubuntu-latest", b"runs-on: '${{ matrix.os }}'"),
        WORKFLOW.replace(b"runs-on: ubuntu-latest", b"if: false\n    runs-on: ubuntu-latest"),
        WORKFLOW.replace(b"steps:", b"steps: []\n    unused:"),
    ],
)
def test_invalid_or_unsupported_workflow_is_rejected(tmp_path, workflow):
    archive = _archive(
        tmp_path / "harness.tar.gz", {"entry.py": b"pass", ".gitea/workflows/smoke.yml": workflow}
    )
    with pytest.raises(ConfigError, match="workflow"):
        materials._check_ci_archive(path=archive)


def test_nested_archive_workflow_is_not_at_harness_repository_root(tmp_path):
    archive = _archive(
        tmp_path / "harness.tar.gz",
        {"entry.py": b"pass", "sub/.gitea/workflows/smoke.yml": WORKFLOW},
    )
    with pytest.raises(ConfigError, match=".gitea/workflows"):
        materials._check_ci_archive(path=archive)


def test_ci_archive_still_rejects_unsafe_members(tmp_path):
    archive = _archive(
        tmp_path / "harness.tar.gz",
        {"entry.py": b"pass", "../.gitea/workflows/smoke.yml": WORKFLOW},
    )
    with pytest.raises(ConfigError, match="Unsafe"):
        materials._check_ci_archive(path=archive)


def test_ci_archive_does_not_follow_workflow_symlink(tmp_path):
    archive = tmp_path / "harness.tar"
    with tarfile.open(archive, "w") as bundle:
        entry = tarfile.TarInfo("entry.py")
        entry.size = 4
        bundle.addfile(entry, io.BytesIO(b"pass"))
        workflow = tarfile.TarInfo(".gitea/workflows/smoke.yml")
        workflow.type = tarfile.SYMTYPE
        workflow.linkname = "/tmp/outside.yml"
        bundle.addfile(workflow)
    with pytest.raises(ConfigError, match="Unsafe"):
        materials._check_ci_archive(path=archive)


def test_ci_archive_bounds_workflow_size(tmp_path):
    archive = _archive(
        tmp_path / "harness.tar.gz",
        {"entry.py": b"pass", ".gitea/workflows/smoke.yml": b"#" * (1024 * 1024 + 1)},
    )
    with pytest.raises(ConfigError, match="too large"):
        materials._check_ci_archive(path=archive)


def test_ci_archive_rejects_duplicate_workflow_overwrite(tmp_path):
    archive = _archive(
        tmp_path / "harness.tar.gz",
        {
            "entry.py": b"pass",
            ".gitea/workflows/smoke.yml": WORKFLOW,
            "./.gitea/workflows/smoke.yml": WORKFLOW,
        },
    )
    with pytest.raises(ConfigError, match="Duplicate"):
        materials._check_ci_archive(path=archive)


def test_disabled_ci_keeps_harness_without_workflows_valid(prepared_inputs, tmp_path):
    archive = _archive(tmp_path / "harness.tar.gz", {"entry.py": b"pass"})
    _archive_config(prepared_inputs, archive)
    assert materials.check_materials(prepared_inputs)["ok"]


def test_enabled_ci_environment_requires_ready_matching_receipt(prepared):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"].update(
        local={"ci_enabled": True}, gitea={"provider": "localhost"}
    )
    resources["ci"] = _receipt(manifest)
    before = copy.deepcopy(manifest)
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["VIGIL_CI_STAGE"] == "agent"
    assert manifest == before


def test_ci_project_matches_uppercase_public_run_identity(prepared):
    root, manifest, credentials, resources = prepared
    manifest["run_id"] = "20261003T010203Z-abcdef12"
    manifest["config"]["runtime"].update(
        local={"ci_enabled": True}, gitea={"provider": "localhost"}
    )
    resources["ci"] = _receipt(manifest)
    resources["compose_project"] = "adx-20261003t010203z-abcdef12-" + manifest["config_hash"][:8]
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["VIGIL_CI_STAGE"] == "agent"


@pytest.mark.parametrize("receipt", [None, {}, {"enabled": True, "state": "READY"}])
def test_missing_ci_receipt_never_silently_downgrades(prepared, receipt):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"].update(
        local={"ci_enabled": True}, gitea={"provider": "localhost"}
    )
    resources["ci"] = receipt
    with pytest.raises(ConfigError, match="CI"):
        build_controller_environment(
            run_dir=root, manifest=manifest, credentials=credentials, resources=resources
        )
    assert not (root / "runtime/controller-context.json").exists()


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("enabled",), False),
        (("state",), "STOPPED"),
        (("run_id",), "other-run"),
        (("config_hash",), "0" * 64),
        (("network",), "other_ci"),
        (("topology",), "host-docker-daemon"),
        (("topology",), None),
        (("job_network",), "other_ci"),
        (("job_network",), None),
        (("daemon",), None),
        (("daemon",), {}),
        (("daemon", "container_id"), ""),
        (("daemon", "container_id"), None),
        (("daemon", "image_id"), ""),
        (("daemon", "image_id"), None),
        (("daemon", "network"), "other_ci"),
        (("daemon", "storage_volume"), "other_ci_docker_data"),
        (("runner",), None),
        (("runner", "id"), 0),
        (("runner", "id"), True),
        (("runner", "name"), ""),
        (("runner", "container_id"), ""),
        (("runner", "image_id"), None),
        (("job_image_id",), ""),
        (("readiness",), None),
        (("readiness", "head_sha"), "b" * 39),
        (("readiness", "head_sha"), "A" * 40),
        (("readiness", "status_count"), 0),
        (("readiness", "status_count"), True),
        (("readiness", "state"), "pending"),
        (("readiness", "state"), "failure"),
        (("readiness", "checked_at"), "not-a-time"),
        (("readiness", "checked_at"), "2026-10-03T01:02:03"),
    ],
)
def test_invalid_ci_identity_and_readiness_cannot_enable_agent(prepared, location, value):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"].update(
        local={"ci_enabled": True}, gitea={"provider": "localhost"}
    )
    receipt = _receipt(manifest)
    target = receipt
    for key in location[:-1]:
        target = target[key]
    target[location[-1]] = value
    resources["ci"] = receipt
    with pytest.raises(ConfigError, match="CI"):
        build_controller_environment(
            run_dir=root, manifest=manifest, credentials=credentials, resources=resources
        )


def test_mismatched_compose_project_cannot_enable_agent(prepared):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"].update(
        local={"ci_enabled": True}, gitea={"provider": "localhost"}
    )
    resources["ci"] = _receipt(manifest)
    resources["compose_project"] = "other-project"
    with pytest.raises(ConfigError, match="identity"):
        build_controller_environment(
            run_dir=root, manifest=manifest, credentials=credentials, resources=resources
        )


@pytest.mark.parametrize("local", [None, {"ci_enabled": False}])
def test_old_disabled_environment_skips_ci_and_ignores_unrelated_receipt(
    prepared, local, monkeypatch
):
    root, manifest, credentials, resources = prepared
    if local is not None:
        manifest["config"]["runtime"]["local"] = local
    resources["ci"] = {"enabled": True, "state": "READY", "run_id": "other-run"}
    monkeypatch.setenv("VIGIL_CI_STAGE", "agent")
    before = copy.deepcopy(manifest)
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["VIGIL_CI_STAGE"] == "skip"
    assert manifest == before
