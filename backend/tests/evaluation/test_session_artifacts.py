"""Spec-0083/T3: genuine bounded file export and receipt binding failures."""

import hashlib
from pathlib import Path

import pytest

from auto_designer.evaluation.artifacts import collect_session_artifacts
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.grading_inputs import archived_artifacts
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime


def declaration(path="output.xlsx", **values):
    return {
        "id": "workbook",
        "source": "workspace",
        "path": path,
        "content_type": "application/octet-stream",
        "required": True,
        "max_bytes": 16384,
        **values,
    }


def identity():
    return {
        "run_id": "trial",
        "round_no": 6,
        "slot": 0,
        "task_id": "excel",
        "task_digest": "a" * 64,
        "harness_sha": "b" * 40,
        "session_id": "session-1",
    }


def collect(tmp_path, declarations=None):
    runtime = LocalWorkspaceRuntime(str(tmp_path / "workspace"))
    Path(runtime.cwd).mkdir(exist_ok=True)
    evidence = collect_session_artifacts(
        workspace=runtime,
        sessions_root=tmp_path / "data/sessions",
        session_id="session-1",
        provenance=identity(),
        declarations=declarations or [declaration()],
    )
    return evidence


def test_binary_output_preserved_and_bound_to_original_session(tmp_path):
    source = tmp_path / "workspace/output.xlsx"
    source.parent.mkdir()
    payload = b"PK\x00\xff" + b"x" * 15000
    source.write_bytes(payload)
    receipt = collect(tmp_path)
    assert receipt["complete"]
    item = receipt["entries"][0]
    assert item["bytes"] == len(payload)
    assert item["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "data" / item["path"]).read_bytes() == payload
    archive = {"data/role_runs/trial/" + item["path"]: payload}
    assert (
        archived_artifacts(
            receipt=receipt, provenance=identity(), declarations=[declaration()], files=archive
        )["workbook"]["payload"]
        == payload
    )
    with pytest.raises(ConfigError, match="ownership"):
        archived_artifacts(
            receipt=receipt,
            provenance={**identity(), "slot": 1},
            declarations=[declaration()],
            files=archive,
        )
    with pytest.raises(ConfigError, match="digest"):
        archived_artifacts(
            receipt=receipt,
            provenance=identity(),
            declarations=[declaration()],
            files={next(iter(archive)): b"tampered"},
        )


@pytest.mark.parametrize(
    "case", ["missing", "over_limit", "symlink", "parent_symlink", "fifo", "directory"]
)
def test_unsafe_missing_or_over_limit_output_does_not_claim_complete(tmp_path, case):
    source = tmp_path / "workspace/output.xlsx"
    source.parent.mkdir()
    if case == "over_limit":
        source.write_bytes(b"x" * 16385)
    elif case == "symlink":
        source.symlink_to(tmp_path / "outside")
    elif case == "parent_symlink":
        directory = tmp_path / "outside"
        directory.mkdir()
        (directory / "output.xlsx").write_bytes(b"x")
        (source.parent / "link").symlink_to(directory, target_is_directory=True)
    elif case == "fifo":
        import os

        os.mkfifo(source)
    elif case == "directory":
        source.mkdir()
    receipt = (
        collect(tmp_path, [declaration("link/output.xlsx")])
        if case == "parent_symlink"
        else collect(tmp_path)
    )
    assert not receipt["complete"]
    assert receipt["entries"][0]["status"] != "collected"
    assert "path" not in receipt["entries"][0]


def test_optional_missing_and_required_present_are_distinct(tmp_path):
    receipt = collect(tmp_path, [declaration(required=False)])
    assert receipt["complete"] and receipt["entries"][0]["status"] == "missing"


def test_managed_measurement_never_uses_user_written_path(tmp_path):
    source = tmp_path / "workspace/output.xlsx"
    source.parent.mkdir()
    source.write_bytes(b"fake measurement")
    receipt = collect(tmp_path, [declaration(source="managed_service", handle="loadgen")])
    assert not receipt["complete"] and receipt["entries"][0]["status"] == "collection_failed"
