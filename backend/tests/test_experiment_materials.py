"""Spec-0069: frozen run inputs preserve identity and never package env secrets."""

import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from auto_designer.experiment import materials
from auto_designer.experiment.config import ConfigError
from test_experiment_config_v2 import definition, package, write


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('task')\n")
    (repo / ".env").write_text("SECRET=never-package\n")
    (tmp_path / "instruction.md").write_text("Improve visible behavior.")
    (tmp_path / "setup.sh").write_text("#!/bin/sh\npython -m venv .venv\n")
    (tmp_path / "requirements.lock").write_text("# no external dependencies\n")
    write(tmp_path / "task.json", package())
    card_root = Path(__file__).resolve().parents[1] / "persona_library.json"
    cards = json.loads(card_root.read_text())
    write(tmp_path / "personas.json", [card for card in cards if card["id"] == "sr-15-swyx"])
    oa = tmp_path / "oa"
    oa.mkdir()
    (oa / "pyproject.toml").write_text("[project]\nname='openagents'\n")
    (oa / "openagents").mkdir()
    (oa / "openagents/__init__.py").write_text("")
    subprocess.run(["git", "init", "--quiet", str(oa)], check=True)
    subprocess.run(["git", "-C", str(oa), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(oa),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(oa), "rev-parse", "HEAD"], text=True
    ).strip()
    config = definition()
    config["source"] = {
        "openagents": {"repository": "https://example.com/openagents.git", "revision": revision}
    }
    config_path = write(tmp_path / "configs/example.json", config)

    def checkout(*, url, revision, destination):
        shutil.copytree(oa, destination)

    monkeypatch.setattr(materials, "_checkout_git", checkout)
    return config_path


def test_offline_check_has_no_resource_or_directory_side_effects(
    prepared_inputs, tmp_path, monkeypatch
):
    def forbidden(**kwargs):
        raise AssertionError("offline check attempted cloning")

    monkeypatch.setattr(materials, "_checkout_git", forbidden)
    before = {str(path) for path in tmp_path.rglob("*")}
    report = materials.check_materials(prepared_inputs)
    assert report["ok"]
    assert report["persona_ids"] == ["sr-15-swyx"]
    assert before == {str(path) for path in tmp_path.rglob("*")}


def test_freeze_generates_plan_archives_and_records_dirty_tree(prepared_inputs, tmp_path):
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert manifest["experiment_id"] == manifest["run_id"]
    assert len(manifest["controller_sha"]) == 40
    assert manifest["source_snapshot"]["files"]["backend/auto_designer/experiment/materials.py"]
    assert isinstance(manifest["source_snapshot"]["dirty"], bool)
    run = Path(manifest["run_dir"])
    plan = json.loads((run / manifest["materials"]["interaction_plan"]["path"]).read_text())
    assert len(plan) == 5
    assert plan[0] == [["sr-15-swyx", "simple-task"]]
    assert manifest["plan_hash"] == manifest["materials"]["interaction_plan"]["sha256"]
    with tarfile.open(run / manifest["materials"]["task_source_archive"]["path"]) as archive:
        assert archive.getnames() == ["main.py"]
    with tarfile.open(run / manifest["materials"]["harness_archive"]["path"]) as archive:
        assert "entry.py" in archive.getnames()
        assert ".env.example" in archive.getnames()
        assert not any(
            Path(path).name.startswith(".env") and Path(path).name != ".env.example"
            for path in archive.getnames()
        )
    materials.verify_materials(manifest)
    write(prepared_inputs, {"broken": "changed after prepare"})
    materials.verify_materials(manifest)
    assert (run / "manifest.json").exists()


def test_source_snapshot_preserves_public_env_template_but_excludes_private_envs(tmp_path):
    (tmp_path / "main.py").write_text("pass\n")
    (tmp_path / ".env.example").write_text("LLM_API_KEY=sk-your-api-key-here\n")
    for name in (".env", ".env.local", ".env.example.local", "credentials.env"):
        (tmp_path / name).write_text("LLM_API_KEY=private-value\n")
    private_directory = tmp_path / ".env.private"
    private_directory.mkdir()
    (private_directory / ".env.example").write_text("LLM_API_KEY=private-value\n")
    files = materials._snapshot_files(root=tmp_path, paths=None)
    archive_path = tmp_path / "source.tar.gz"
    materials._archive_snapshot(root=tmp_path, files=files, destination=archive_path)
    with tarfile.open(archive_path) as archive:
        assert archive.getnames() == [".env.example", "main.py"]
        assert b"private-value" not in b"".join(
            archive.extractfile(member).read() for member in archive.getmembers()
        )


def test_tampered_frozen_input_is_rejected(prepared_inputs, tmp_path):
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    path = Path(manifest["run_dir"]) / manifest["materials"]["persona_library"]["path"]
    path.write_text("[]")
    with pytest.raises(ConfigError, match="persona_library"):
        materials.verify_materials(manifest)


def test_prepare_failure_is_atomic_and_no_orphan_run(prepared_inputs, tmp_path, monkeypatch):
    def failure(**kwargs):
        raise ConfigError("download failed")

    monkeypatch.setattr(materials, "_checkout_git", failure)
    with pytest.raises(ConfigError, match="download failed"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert not list((tmp_path / "runs").glob("20*"))
    assert not list((tmp_path / "runs").glob(".preparing-*"))


def test_symlink_in_task_snapshot_is_rejected(prepared_inputs, tmp_path):
    (tmp_path / "repo/link").symlink_to(tmp_path / "instruction.md")
    with pytest.raises(ConfigError, match="symbolic"):
        materials.check_materials(prepared_inputs)


def test_missing_persona_reports_actual_id(prepared_inputs):
    document = json.loads(prepared_inputs.read_text())
    document["workload"]["persona_ids"] = ["missing-persona"]
    write(prepared_inputs, document)
    with pytest.raises(ConfigError, match="missing-persona"):
        materials.check_materials(prepared_inputs)


def test_plaintext_credentials_are_not_copied_into_run(prepared_inputs, tmp_path):
    secret = tmp_path / "credentials.env"
    secret.write_text("MODEL_API_KEY=never-package-this-secret")
    secret.chmod(0o600)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs", secret)
    assert manifest["secrets_file"] == str(secret)
    for path in Path(manifest["run_dir"]).rglob("*.json"):
        assert "never-package-this-secret" not in path.read_text()
    secret.chmod(0o644)
    with pytest.raises(ConfigError, match="0600"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs", secret)


def test_archive_harness_is_hash_checked_before_prepare(prepared_inputs, tmp_path):
    archive = tmp_path / "harness.tar.gz"
    archive.write_bytes(b"invalid")
    config = json.loads(prepared_inputs.read_text())
    config["harness"] = {"source": "archive", "archive": str(archive), "sha256": "0" * 64}
    write(prepared_inputs, config)
    with pytest.raises(ConfigError, match="SHA-256"):
        materials.check_materials(prepared_inputs)


def test_archive_escape_members_are_rejected(tmp_path):
    import io

    archive_path = tmp_path / "harness.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("../entry.py")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ConfigError, match="Unsafe"):
        materials._check_archive(path=archive_path)


def test_legitimate_task_data_is_preserved(prepared_inputs, tmp_path):
    data = tmp_path / "repo/data"
    data.mkdir()
    (data / "weather.csv").write_text("time,temperature\n0,20\n")
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert "data/weather.csv" in manifest["task_source_snapshot"]["files"]
    path = Path(manifest["run_dir"]) / manifest["materials"]["task_source_archive"]["path"]
    with tarfile.open(path) as archive:
        assert "data/weather.csv" in archive.getnames()


def test_swe_dataset_preserves_actual_runner_columns(tmp_path):
    import pyarrow.parquet as pq

    task = {
        "id": "org__repo-1",
        "source": {"repo": "org/repo", "revision": "a" * 40},
        "difficulty": "small",
    }
    destination = tmp_path / "instance.parquet"
    materials._write_dataset(task=task, instruction="Fix the issue", destination=destination)
    row = pq.read_table(
        destination,
        columns=["instance_id", "repo", "base_commit", "problem_statement", "difficulty"],
    ).to_pylist()[0]
    assert row == {
        "instance_id": "org__repo-1",
        "repo": "org/repo",
        "base_commit": "a" * 40,
        "problem_statement": "Fix the issue",
        "difficulty": "small",
    }
    assert "patch" not in pq.read_schema(destination).names


@pytest.mark.parametrize(
    "override",
    [
        {"repository": "https://github.com/nex-agi/NexAU.git", "revision": "a" * 40},
        {
            "repository": "https://example.com/fork.git",
            "revision": "5cd791b1382f1163621c9ff0b50c2cf01c4ba923",
        },
    ],
)
def test_nexau_override_cannot_disagree_with_installed_runtime(prepared_inputs, tmp_path, override):
    document = json.loads(prepared_inputs.read_text())
    document["source"]["nexau"] = override
    write(prepared_inputs, document)
    with pytest.raises(ConfigError, match="runtime is locked"):
        materials.prepare_materials(prepared_inputs, tmp_path / "runs")


def test_matching_nexau_override_records_real_installed_pin(prepared_inputs, tmp_path):
    document = json.loads(prepared_inputs.read_text())
    document["source"]["nexau"] = {
        "repository": "https://github.com/nex-agi/NexAU.git",
        "revision": "5cd791b1382f1163621c9ff0b50c2cf01c4ba923",
    }
    write(prepared_inputs, document)
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert manifest["source_pins"]["nexau"] == document["source"]["nexau"]
