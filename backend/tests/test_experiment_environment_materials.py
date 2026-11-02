"""Spec-0081/T2: verified materials, relocatable freeze, and ordinary-task compatibility."""

import copy
import hashlib
import io
import json
import runpy
import shutil
import tarfile
from pathlib import Path

import pytest

from ahe_beta.experiment import materials
from ahe_beta.experiment.task_environments.materials import (
    MaterialError,
    execution_environment,
    fetch_material,
    materialize_input,
)
from ahe_beta.experiment.workload import read_task_catalog
from test_experiment_materials import prepared_inputs as prepared_inputs


def archive(path, entries):
    with tarfile.open(path, "w:gz") as bundle:
        for name, content in entries.items():
            row = tarfile.TarInfo(name)
            row.mode = 0o644
            row.size = len(content)
            bundle.addfile(row, io.BytesIO(content))
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "format": "tar.gz",
    }


def task(package_path, material):
    package_path.parent.mkdir(parents=True, exist_ok=True)
    (package_path.parent / "instruction.md").write_text("Inspect the supplied workbook.")
    value = {
        "schema_version": 3,
        "id": "order-service",
        "kind": "ordinary",
        "not_in_benchmark": True,
        "interaction": "simulated_user",
        "instruction_file": "instruction.md",
        "environment": {
            "kind": "container",
            "image": "example.test/task@sha256:" + "a" * 64,
            "workdir": "/app",
            "inputs": [{"id": "data", "material": material, "target": "/app/data"}],
            "readiness": {"argv": ["true"], "timeout_seconds": 5},
        },
    }
    package_path.write_text(json.dumps(value))
    return value


def test_content_addressed_cache_verifies_local_and_detects_tampering(tmp_path):
    original = tmp_path / "source.tar.gz"
    ref = archive(original, {"table.csv": b"value\n1\n"})
    cached = fetch_material(material=ref, cache=tmp_path / "cache")
    assert cached.name == ref["sha256"]
    assert cached.read_bytes() == original.read_bytes()
    cached.write_bytes(b"corrupt")
    with pytest.raises(MaterialError, match="SHA-256"):
        fetch_material(material=ref, cache=tmp_path / "cache")


def test_no_partial_download_is_published(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("connection lost")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    ref = {"url": "https://example.test/data.tar.gz", "sha256": "b" * 64, "format": "tar.gz"}
    with pytest.raises(MaterialError):
        fetch_material(material=ref, cache=tmp_path / "cache")
    assert not (tmp_path / "cache" / ref["sha256"]).exists()
    assert not list((tmp_path / "cache").glob(".material-*"))


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../../escape", "a\\escape"])
def test_archive_cannot_escape_owned_input_directory(tmp_path, name):
    ref = archive(tmp_path / "bad.tar.gz", {name: b"bad"})
    with pytest.raises(MaterialError):
        materialize_input(material=ref, destination=tmp_path / "unpacked")
    assert not (tmp_path / "escape").exists()


def test_declared_inventory_is_checked_before_runtime(tmp_path):
    ref = archive(tmp_path / "data.tar.gz", {"a.txt": b"actual"})
    ref["files"] = {"a.txt": hashlib.sha256(b"expected").hexdigest()}
    with pytest.raises(MaterialError, match="inventory"):
        materialize_input(material=ref, destination=tmp_path / "out")


def test_plain_file_identity_survives_content_cache_rename(tmp_path):
    source = tmp_path / "original.xlsx"
    source.write_bytes(b"workbook")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    ref = {"path": str(source), "sha256": digest, "format": "file", "files": {"input": digest}}
    cached = fetch_material(material=ref, cache=tmp_path / "cache")
    result = materialize_input(material={**ref, "path": str(cached)}, destination=tmp_path / "out")
    assert result == {"input": digest}
    assert (tmp_path / "out/input").read_bytes() == b"workbook"


def test_offline_check_lists_remote_inputs_without_creating_cache(
    prepared_inputs, tmp_path, monkeypatch
):
    config = json.loads(prepared_inputs.read_text())
    package_path = (prepared_inputs.parent / config["workload"]["task_package"]).resolve()
    task(
        package_path,
        {"url": "https://example.test/input.tar.gz", "sha256": "f" * 64, "format": "tar.gz"},
    )
    config["workload"]["kind"] = "ordinary"
    prepared_inputs.write_text(json.dumps(config))
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("offline networking")
    )
    before = set(tmp_path.rglob("*"))
    report = materials.check_materials(prepared_inputs)
    assert report["container_materials"]["order-service"][0]["status"] == "pending_download"
    assert set(tmp_path.rglob("*")) == before


def test_container_freeze_has_no_fake_source_and_can_be_relocated(prepared_inputs, tmp_path):
    config = json.loads(prepared_inputs.read_text())
    package_path = (prepared_inputs.parent / config["workload"]["task_package"]).resolve()
    ref = archive(tmp_path / "data.tar.gz", {"data.csv": b"id,value\n1,2\n"})
    task(package_path, ref)
    config["workload"]["kind"] = "ordinary"
    prepared_inputs.write_text(json.dumps(config))
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    assert (
        "source_archive"
        not in read_task_catalog(Path(manifest["run_dir"]), manifest)["tasks"][0]["materials"]
    )
    materials.verify_materials(manifest)
    relocated = tmp_path / "cloud"
    shutil.copytree(manifest["run_dir"], relocated)
    moved = copy.deepcopy(manifest)
    moved["run_dir"] = str(relocated)
    materials.verify_materials(moved)
    record = read_task_catalog(relocated, moved)["tasks"][0]
    environment = execution_environment(package=record["package"], run_root=relocated)
    assert Path(environment["inputs"][0]["material"]["path"]).is_relative_to(relocated)
    assert "setup" not in record["package"]
    assert "source" not in record["package"]
    assert "inputs" in record["package"]["environment"]
    remote = execution_environment(
        package=record["package"], run_root=relocated, destination_root=Path("/owned-cloud-run")
    )
    assert remote["inputs"][0]["material"]["path"].startswith("/owned-cloud-run/")
    assert not Path("/owned-cloud-run").exists()


def test_exporter_preserves_original_bytes_and_sanitizes_image_facts(tmp_path):
    tool = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/dev/export-evolution-task-materials.py")
    )
    payloads = tmp_path / "payloads"
    payloads.mkdir()
    ref = archive(payloads / "case.tar.gz", {"case/input.csv": b"pristine\n"})
    manifest = tmp_path / "tasks.json"
    manifest.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_key": "case",
                        "task_id": "original-task",
                        "agent_payload_sha256": ref["sha256"],
                    }
                ]
            }
        )
    )
    images = tmp_path / "images.json"
    images.write_text(
        json.dumps(
            {
                "case": {
                    "image": "original-image:fixed",
                    "image_id": "sha256:" + "a" * 64,
                    "Env": ["API_KEY=private-value"],
                }
            }
        )
    )
    result = tool["export_materials"](
        manifest=manifest, payloads=payloads, output=tmp_path / "export", images=images
    )
    assert result["task_count"] == 1
    assert result["publication"] == "not_attempted"
    assert (tmp_path / "export/payloads/case.tar.gz").read_bytes() == (
        payloads / "case.tar.gz"
    ).read_bytes()
    assert "private-value" not in json.dumps(result)
    assert result["tasks"][0]["material"]["files"] == {
        "case/input.csv": hashlib.sha256(b"pristine\n").hexdigest()
    }
    with pytest.raises(tool["ExportError"], match="new directory"):
        tool["export_materials"](manifest=manifest, payloads=payloads, output=tmp_path / "export")
    (payloads / "case.tar.gz").write_bytes(b"changed input")
    with pytest.raises(MaterialError):
        tool["export_materials"](manifest=manifest, payloads=payloads, output=tmp_path / "failed")
    assert not (tmp_path / "failed").exists()
