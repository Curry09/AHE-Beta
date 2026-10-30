"""A system Python must never cause its entire shared prefix to be archived."""

import hashlib
import tarfile
from types import SimpleNamespace

import pytest

from evaluation.harbor import processes
from evaluation.harness import materials, python_runtime


@pytest.mark.parametrize("prefix", ["/", "/usr", "/usr/local"])
@pytest.mark.parametrize("builder", ["native", "harness"])
def test_system_prefix_rejected_before_any_archive_or_cache_write(
    tmp_path, monkeypatch, prefix, builder
):
    monkeypatch.setattr(
        python_runtime,
        "sys",
        SimpleNamespace(platform="linux", version_info=(3, 12), base_prefix=prefix),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("System prefix reached archive/cache creation")

    monkeypatch.setattr(tarfile, "open", forbidden)
    monkeypatch.setattr(processes, "user_cache_path", forbidden)
    with pytest.raises(ValueError, match="System installation prefixes cannot be archived"):
        if builder == "native":
            processes.prepare_process_runtime()
        else:
            materials.build_materials(tmp_path / "source", tmp_path / "output")
    assert list(tmp_path.iterdir()) == []


def test_ordinary_python_layout_without_standalone_marker_is_rejected(tmp_path, monkeypatch):
    for name in ("bin/python3.12", "lib/python3.12/os.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(
        python_runtime,
        "sys",
        SimpleNamespace(platform="linux", version_info=(3, 12), base_prefix=str(tmp_path)),
    )
    with pytest.raises(ValueError, match="self-contained Linux CPython 3.12"):
        python_runtime.portable_python_base()


def test_native_runtime_archives_only_portable_tree_and_reuses_it(tmp_path, monkeypatch):
    base = tmp_path / "portable"
    for name in ("BUILD", "bin/python3.12", "lib/python3.12/os.py", "lib/__pycache__/skip.pyc"):
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (tmp_path / "unrelated-secret.txt").write_text("outside portable tree")
    monkeypatch.setattr(
        python_runtime,
        "sys",
        SimpleNamespace(platform="linux", version_info=(3, 12), base_prefix=str(base)),
    )
    monkeypatch.setattr(processes, "user_cache_path", lambda name: tmp_path / "cache")
    descriptor = processes.prepare_process_runtime()
    archive = tmp_path / "cache/native-runtime"
    archives = list(archive.glob("*/python312.tar.gz"))
    assert len(archives) == 1
    assert descriptor["python_sha256"] == hashlib.sha256(archives[0].read_bytes()).hexdigest()
    with tarfile.open(archives[0]) as pack:
        files = {item.name for item in pack if item.isfile()}
    assert files == {
        "python312/BUILD",
        "python312/bin/python3.12",
        "python312/lib/python3.12/os.py",
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Unchanged portable runtime was repacked")

    monkeypatch.setattr(tarfile, "open", forbidden)
    assert processes.prepare_process_runtime() == descriptor
