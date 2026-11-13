"""Pinned AHE source, SDK identity and both current task-source contracts."""

import hashlib
import importlib.util
import json
import zipfile
from importlib.metadata import distribution
from pathlib import Path

import pytest
import yaml

from evaluation.configuration import Configuration
from evaluation.harness.ahe import materialize, prepare_runtime, verify_native_wheel, verify_source
from evaluation.preparation import ahe_runtime, freeze_harness


@pytest.fixture
def native_wheel(tmp_path):
    pytest.importorskip("nexau")
    package = Path(importlib.util.find_spec("nexau").origin).parent
    wheel = tmp_path / "nexau-0.4.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, "nexau/" + path.relative_to(package).as_posix())
        license_file = "nexau-0.4.1.dist-info/licenses/LICENSE"
        archive.write(distribution("nexau").locate_file(license_file), license_file)
    return wheel


def test_upstream_source_is_fixed_and_extra_code_is_rejected(tmp_path):
    source = materialize(tmp_path / "ahe")
    assert len(verify_source(source)["upstream_files"]) == 14
    (source / "systemprompt.md").write_text("changed")
    with pytest.raises(ValueError, match="systemprompt"):
        freeze_harness("ahe", source, tmp_path / "cache", {})
    source = materialize(tmp_path / "another")
    (source / "sitecustomize.py").write_text("raise RuntimeError('unreviewed code')")
    with pytest.raises(ValueError, match="inventory"):
        verify_source(source)


def test_runtime_import_verifies_native_code_and_never_replaces_output(
    tmp_path, native_wheel, monkeypatch
):
    verify_native_wheel(native_wheel)
    parent = tmp_path / "runtime"
    python_archive = tmp_path / "python312.tar.gz"
    python_archive.write_bytes(b"separately tested Python archive")
    kit = prepare_runtime(parent / "ahe", native_wheel, python_archive)
    base = {"runtime_wheel": str(parent / native_wheel.name), "python_sha256": "shared"}
    result = ahe_runtime(base)
    assert result["python_sha256"] == hashlib.sha256(python_archive.read_bytes()).hexdigest()
    assert Path(result["python_archive"]).read_bytes() == python_archive.read_bytes()
    from evaluation.harness import ahe

    monkeypatch.setattr(ahe, "runtime_directory", lambda: parent)
    assert ahe_runtime()["python_sha256"] == result["python_sha256"]
    assert result["runtime_sha256"] == hashlib.sha256(native_wheel.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="must not exist"):
        prepare_runtime(kit, native_wheel)
    with zipfile.ZipFile(kit / native_wheel.name, "a") as archive:
        archive.writestr("nexau/extra_patch.py", "raise RuntimeError('patched runtime')")
    # Updating an ordinary material hash must not bypass the upstream package identity.
    manifest = kit / "manifest.json"
    hashes = json.loads(manifest.read_text())
    hashes[native_wheel.name] = hashlib.sha256((kit / native_wheel.name).read_bytes()).hexdigest()
    manifest.write_text(json.dumps(hashes))
    with pytest.raises(ValueError, match="unmodified pinned NexAU"):
        ahe_runtime(base)


def test_materialization_never_overwrites_a_checkout(tmp_path):
    source = materialize(tmp_path / "ahe")
    with pytest.raises(FileExistsError):
        materialize(source)


def test_native_wheel_cannot_install_extra_python_hooks(native_wheel):
    with zipfile.ZipFile(native_wheel, "a") as archive:
        archive.writestr("unreviewed.pth", "import unreviewed_install_hook")
    with pytest.raises(ValueError, match="Unexpected files"):
        verify_native_wheel(native_wheel)


@pytest.mark.parametrize("task_source", ["harbor_index", "harbor"])
def test_ahe_selection_preserves_task_profiles_and_freezing(tmp_path, monkeypatch, task_source):
    from evaluation import preparation
    from evaluation.tests.test_execution import task

    source = materialize(tmp_path / "harnesses/ahe")
    case = task(tmp_path / "task")
    raw = {
        "version": 1,
        "task_source": task_source,
        "tasks": [str(case)]
        if task_source == "harbor"
        else ["swebenchpro-fix-file-suffix-chooser"],
        "paths": {"harnesses": str(source.parent)},
        "harnesses": ["ahe"],
        "actor": {"base_url": "https://fixture.invalid", "api_type": "anthropic_chat_completion"},
    }
    config = Configuration.from_mapping(raw, tmp_path / "evaluation.yaml")
    config.validate_sources()
    assert config.data["task_source"] == task_source
    assert len(config.task_names()) == 1
    if task_source == "harbor":
        monkeypatch.setattr(
            preparation, "runtime_descriptor", lambda: pytest.fail("Legacy kit requested")
        )
        monkeypatch.setattr(preparation, "ahe_runtime", lambda: {"runtime_sha256": "native"})
        _dataset, cases, _resolved, harnesses = preparation.prepare(config, download=False)
        assert len(cases) == 1 and harnesses[0]["runtime"]["runtime_sha256"] == "native"


def test_public_messages_example_is_valid_without_private_configuration():
    root = Path(__file__).resolve().parents[2]
    sample = root / "examples/evaluation/ahe-messages.yaml"
    config = Configuration.from_mapping(yaml.safe_load(sample.read_text()), sample)
    assert config.data["actor"]["api_type"] == "anthropic_chat_completion"
    assert config.data["harnesses"] == ["ahe"]
    assert config.data["execution"]["time_adaptation"] is False
    assert len(config.task_names()) == 1
