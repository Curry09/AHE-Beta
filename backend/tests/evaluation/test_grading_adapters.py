"""Verify adapter material/isolation and official-result boundaries (Spec-0083/T4)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from dataclasses import replace

import pytest

from auto_designer.evaluation.adapters import container, profiles
from auto_designer.evaluation.adapters.custom import CustomAdapter
from auto_designer.evaluation.adapters.terminal_bench import official_reward
from auto_designer.evaluation.contracts import (
    ArtifactInput,
    GradingRequest,
    InputValidationError,
    MaterialInput,
)
from auto_designer.evaluation.registry import get_adapter
from auto_designer.evaluation.results import ExecutionEvidence


def material(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return MaterialInput(path, container.sha256(data))


def tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, data, mode in entries:
            info = tarfile.TarInfo(name)
            info.mode = mode
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


@pytest.mark.parametrize("name", ["../escape", "/escape", "tests/../../escape", "tests\\escape"])
def test_archive_rejects_escape_paths(name):
    with pytest.raises(InputValidationError):
        container.archive_files(tar([(name, b"bad", 0o644)]))


def test_archive_rejects_symlinks_and_duplicate_normalized_paths():
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        entry = tarfile.TarInfo("link")
        entry.type = tarfile.SYMTYPE
        entry.linkname = "/etc/passwd"
        archive.addfile(entry)
    with pytest.raises(InputValidationError):
        container.archive_files(out.getvalue())
    with pytest.raises(InputValidationError):
        container.archive_files(tar([("./same", b"a", 0o644), ("same", b"b", 0o644)]))


def test_log_stream_is_bounded_even_when_child_spams_stdout(tmp_path):
    path = tmp_path / "bounded.log"
    with pytest.raises(RuntimeError, match="16 MiB"):
        container.logged_process(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * (17 * 1024 * 1024))"],
            path,
            timeout=10,
        )
    assert path.stat().st_size <= 16 * 1024 * 1024


def test_log_stream_timeout_stops_a_silent_child(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        container.logged_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path / "timeout.log",
            timeout=0.1,
        )


def test_directory_staging_copies_contents_without_nested_tests(tmp_path, monkeypatch):
    calls = []
    tests = tmp_path / "tests"
    tests.mkdir()
    verifier = container.VerifierContainer("sha256:" + "a" * 64, tmp_path)
    monkeypatch.setattr(verifier, "command", lambda *args, **kwargs: (0, ""))
    monkeypatch.setattr(container, "run_docker", lambda args, **kwargs: calls.append(args))
    verifier.copy_in(tests, "/tests")
    assert calls[0] == ["cp", str(tests) + "/.", verifier.name + ":/tests"]


def test_failed_container_cleanup_cannot_silently_publish_success(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("daemon failed while removing verifier")

    monkeypatch.setattr(container, "run_docker", failed)
    verifier = container.VerifierContainer("sha256:" + "a" * 64, tmp_path)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        verifier.__exit__(None, None, None)
    receipt = json.loads((tmp_path / "container-cleanup.json").read_text())
    assert receipt["completed"] is False
    assert receipt["container_name"] == verifier.name


def test_successful_container_cleanup_has_an_explicit_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(container, "run_docker", lambda *args, **kwargs: "")
    verifier = container.VerifierContainer("sha256:" + "a" * 64, tmp_path)
    verifier.__exit__(None, None, None)
    assert json.loads((tmp_path / "container-cleanup.json").read_text())["completed"] is True


def test_offline_artifact_payload_needs_no_exported_files(tmp_path):
    artifact = ArtifactInput(
        tmp_path / "not-written", container.sha256(b"value"), 5, payload=b"value"
    )
    assert container.artifact_bytes(artifact) == b"value"
    with pytest.raises(InputValidationError):
        container.artifact_bytes(replace(artifact, bytes=6))


def test_builtin_registry_dispatch_is_fixed():
    for name in ("swebench", "terminal-bench", "tua-bench", "nl2repo", "custom"):
        assert get_adapter(name).name == name


def test_official_tree_check_detects_extra_tests_and_changed_modes(tmp_path, monkeypatch):
    files = {
        "task.toml": b"schema_version='1'",
        "tests/test.sh": b"echo 1",
        "environment/Dockerfile": b"FROM pinned",
    }
    modes = {name: 0o644 for name in files}
    profile = {
        "adapter": "terminal-bench",
        "revision": "revision",
        "task_blob": profiles.git_object("blob", files["task.toml"]).hex(),
        "tests_tree": profiles.git_tree(files, modes, "tests/").hex(),
        "environment_tree": profiles.git_tree(files, modes, "environment/").hex(),
    }
    monkeypatch.setitem(profiles.PROFILES, "fixture", profile)
    data = tar([(name, value, modes[name]) for name, value in files.items()])
    request = GradingRequest(
        "terminal-bench",
        1,
        "fixture",
        "d",
        "s",
        source={"revision": "revision"},
        config={"revision": "revision"},
        materials={"task_bundle": material(tmp_path, "task.tar", data)},
    )
    assert profiles.validate_task_bundle(request)[0] == files
    altered = tar(
        [
            (name, value, 0o755 if name == "tests/test.sh" else mode)
            for name, value, mode in [(name, value, modes[name]) for name, value in files.items()]
        ]
    )
    request = replace(
        request, materials={"task_bundle": material(tmp_path, "changed.tar", altered)}
    )
    with pytest.raises(InputValidationError, match="tests tree"):
        profiles.validate_task_bundle(request)


def test_custom_offline_validation_has_no_docker_or_allocation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline validation invoked Docker")

    monkeypatch.setattr(container, "run_docker", forbidden)
    script = material(tmp_path, "script.py", b"fixed script")
    request = GradingRequest(
        "custom",
        1,
        "task",
        "d",
        "session",
        materials={"script": script},
        config={"image": "sha256:" + "a" * 64, "argv": ["python3", "/grader/script.py"]},
    )
    CustomAdapter().validate_inputs(request)
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize(
    "destination", ["/tests/test.sh", "/inputs/../tests/test.sh", "/etc/passwd"]
)
def test_custom_inputs_cannot_replace_grader_or_container_files(tmp_path, destination):
    request = GradingRequest(
        "custom",
        1,
        "t",
        "d",
        "s",
        materials={"script": material(tmp_path, "script.py", b"script")},
        config={
            "image": "sha256:" + "a" * 64,
            "argv": ["python3", "/grader/script.py"],
            "artifact_map": {"artifact": destination},
        },
    )
    with pytest.raises(ValueError, match="below /inputs"):
        CustomAdapter().validate_inputs(request)


@pytest.mark.parametrize("environment_failure", [True, False])
def test_official_kv_precondition_zero_is_not_a_technical_failure(tmp_path, environment_failure):
    (tmp_path / "reward.txt").write_text("0")
    (tmp_path / "verifier.log").write_text("official diagnostics")
    (tmp_path / "ctrf.json").write_text(
        json.dumps(
            {
                "results": {
                    "tests": [
                        {
                            "name": "environment" if environment_failure else "throughput",
                            "status": "failed",
                        }
                    ]
                }
            }
        )
    )

    class FakeContainer:
        def copy_out(self, path, name):
            return tmp_path / name

    result = official_reward(
        GradingRequest("terminal-bench", 1, "kv", "d", "s"),
        tmp_path,
        FakeContainer(),
        ExecutionEvidence("trusted_recorded_measurement", True, "sha256:" + "a" * 64),
        exit_code=1,
        log="official diagnostics",
        binary=True,
    )
    assert result.raw_report["reward"] == 0
    assert result.status == ("ungradable" if environment_failure else "completed")
    assert result.passed is (None if environment_failure else False)
