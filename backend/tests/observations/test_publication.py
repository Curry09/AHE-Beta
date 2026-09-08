"""Test collection contracts independently of a particular harness event schema."""

import io
import json
import os
import sys
import tarfile

import pytest

from auto_designer.designer.observation_provider import ObservationProvider
from auto_designer.observations.publication import (
    ObservationSource,
    archive_files,
    bounded_command,
    local_files,
    publish,
)
from auto_designer.user.session_store import SessionStore


def bundle(name="events.log", text="request started"):
    return {
        "manifest.json": json.dumps({"reading": "READING.md", "status": "complete",
            "files": [{"path": "READING.md"}, {"path": name}]}).encode(),
        "READING.md": b"Version-specific diagnostics, not user-visible behavior.",
        name: text.encode(),
    }


def test_versions_and_formats_remain_independently_readable(tmp_path):
    root = tmp_path / "observations"
    for sid, rid, sha, name, text in [
        ("s1", "r1", "v1", "events.log", "error=true"),
        ("s2", "r2", "v2", "different.tsv", "worker\twaiting"),
        ("s1", "r3", "v1", "after-restart.txt", "cancelled"),
    ]:
        receipt = publish(root=root, session_id=sid, run_id=rid,
                          version={"harness_sha": sha}, files=bundle(name, text))
        assert receipt["status"] == "complete"
    store = SessionStore(tmp_path / "sessions")
    provider = ObservationProvider(store, allowed_session_ids=frozenset({"s1", "s2"}))
    assert set(provider.files) == {"s1", "s2"}
    assert (root / "s1/runs/r1/events.log").read_text() == "error=true"
    assert (root / "s2/runs/r2/different.tsv").read_text() == "worker\twaiting"
    assert len(json.loads((root / "s1/manifest.json").read_text())["runs"]) == 2


def test_publication_is_idempotent_but_cannot_replace_history(tmp_path):
    kwargs = dict(root=tmp_path, session_id="s", run_id="r", version={"harness_sha": "v1"})
    publish(**kwargs, files=bundle())
    publish(**kwargs, files=bundle())
    with pytest.raises(ValueError, match="immutable"):
        publish(**kwargs, files=bundle(text="new facts"))
    assert (tmp_path / "s/runs/r/events.log").read_text() == "request started"


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "dir/../../escape", "dir\\escape"])
def test_unsafe_declared_paths_are_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        publish(root=tmp_path, session_id="s", run_id="r", version={}, files=bundle(path))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_archive_links_and_special_files_are_not_extracted(kind):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        member = tarfile.TarInfo("root/evil")
        member.type = kind
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ValueError):
        archive_files(raw.getvalue())


def test_archive_regular_files_and_local_links(tmp_path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, data in bundle().items():
            member = tarfile.TarInfo(f"root/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    assert archive_files(raw.getvalue()) == bundle()
    for name, data in bundle().items():
        (tmp_path / name).write_bytes(data)
    target = tmp_path / "events.log"
    target.unlink()
    target.symlink_to(tmp_path / "READING.md")
    with pytest.raises(ValueError):
        local_files(tmp_path)
    target.unlink()
    os.link(tmp_path / "READING.md", target)
    with pytest.raises(ValueError):
        local_files(tmp_path)


def test_command_output_and_time_are_bounded():
    assert bounded_command([sys.executable, "-c", "print(123)"], timeout=2, limit=32) == b"123\n"
    with pytest.raises(ValueError):
        bounded_command([sys.executable, "-c", "print(123456789*1000)"], timeout=2, limit=2)
    with pytest.raises(TimeoutError):
        bounded_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05, limit=32)


def test_missing_bundle_is_receipted_not_replaced_with_old_logs(tmp_path):
    source = ObservationSource(directory=str(tmp_path / "missing"), container_id=None,
                               version={"harness_sha": "v2"})
    receipt = source.collect(root=tmp_path / "published", session_id="s2")
    assert receipt["status"] == "unavailable"
    assert not (tmp_path / "published/s2/manifest.json").exists()
    assert list((tmp_path / "published/collection-failures").glob("*.json"))


def test_publication_redacts_credentials_before_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNER_LLM_API_KEY", "known-secret-for-test")
    publish(root=tmp_path, session_id="s", run_id="r", version={},
            files=bundle(text="known-secret-for-test"))
    assert "known-secret-for-test" not in (tmp_path / "s/runs/r/events.log").read_text()


def test_recovery_reuses_identity_and_keeps_source(tmp_path):
    from auto_designer.observations.publication import recover

    root = tmp_path / "published"
    directory = tmp_path / "source"
    source = ObservationSource(directory=str(directory), container_id=None, version={"harness_sha": "v1"})
    failure = source.collect(root=root, session_id="s")
    directory.mkdir()
    for name, data in bundle().items():
        (directory / name).write_bytes(data)
    receipt = next((root / "collection-failures").glob("*.json"))
    result = recover(receipt_path=receipt, root=root)
    assert result["status"] == "complete" and result["run_id"] == failure["run_id"]
    assert not receipt.exists() and (directory / "events.log").exists()


def test_failed_collection_retains_stopped_container_without_removing_it(monkeypatch):
    from types import SimpleNamespace

    from auto_designer.user.sim.runtime import DockerWorkspaceRuntime

    calls = []
    monkeypatch.setattr("auto_designer.user.sim.runtime.subprocess.run",
                        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0))
    ws = DockerWorkspaceRuntime(container_id="fixture", container_name="fixture", image="i",
                                image_digest="sha", cwd="/tmp")
    ws.evidence["observation"] = {"status": "unavailable", "retain_source": True}
    ws.close()
    ws.close()
    assert calls == [["docker", "stop", "--time", "2", "fixture"]]
    assert ws.evidence["retained_for_observations"] and ws.evidence["stop_confirmed"]
