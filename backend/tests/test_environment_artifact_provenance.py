"""Spec-0081/T3: retained service output binds to a frozen public recipe and attempt."""

import copy
import hashlib
import json

import pytest

from auto_designer.evaluation.artifacts import collect_session_artifacts
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.grading_inputs import archived_artifacts
from auto_designer.experiment.task_environments.contract import environment_identity


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


def package(placement):
    return {
        "schema_version": 3,
        "environment": {
            "kind": "container",
            "image": "example.test/task@sha256:" + "a" * 64,
            "workdir": "/app",
            "readiness": {"argv": ["true"], "timeout_seconds": 5},
            "services": [
                {
                    "id": "loadgen",
                    "placement": placement,
                    **(
                        {"image": "example.test/loadgen@sha256:" + "c" * 64}
                        if placement == "companion"
                        else {}
                    ),
                    "argv": ["sleep", "infinity"],
                    "readiness": {"argv": ["true"], "timeout_seconds": 5},
                    "exports": [{"handle": "report", "path": "/result.json", "visibility": "task"}],
                }
            ],
        },
    }


def export():
    return {
        "id": "report",
        "source": "managed_service",
        "handle": "report",
        "content_type": "application/json",
        "required": True,
        "max_bytes": 65536,
    }


class ManagedWorkspace:
    def __init__(self, package):
        binding = {
            key: identity()[key]
            for key in ("run_id", "round_no", "slot", "task_id", "task_digest", "session_id")
        }
        binding.update(config_hash="d" * 64, recipe_hash=environment_identity(package), attempt=1)
        self.metadata = {
            "identity": binding,
            "environment_key": hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "recipe_hash": binding["recipe_hash"],
            "owner_session_id": binding["session_id"],
            "service": "loadgen",
            "service_id": "e" * 64,
            "handle": "report",
            "placement": package["environment"]["services"][0]["placement"],
            "visibility": "task",
            "sealed_at": "2026-10-31T12:00:00+00:00",
            "controller_owned": True,
            "isolated": package["environment"]["services"][0]["placement"] == "companion",
            "agent_stopped": True,
        }

    def quiesce(self):
        pass

    def finalize_task(self):
        pass

    def export_service_file(self, handle, max_bytes):
        assert handle == "report"
        return b'{"completed":true}'

    def service_export_provenance(self, handle):
        assert handle == "report"
        return copy.deepcopy(self.metadata)


def retained(tmp_path, placement):
    task = package(placement)
    workspace = ManagedWorkspace(task)
    receipt = collect_session_artifacts(
        workspace=workspace,
        sessions_root=tmp_path / "data/sessions",
        session_id=identity()["session_id"],
        provenance=identity(),
        declarations=[export()],
    )
    row = receipt["entries"][0]
    files = {"data/role_runs/trial/" + row["path"]: (tmp_path / "data" / row["path"]).read_bytes()}
    return task, receipt, files


@pytest.mark.parametrize("placement", ["task", "companion"])
def test_managed_output_retains_truthful_placement_for_grader(tmp_path, placement):
    task, receipt, files = retained(tmp_path, placement)
    outputs = archived_artifacts(
        receipt=receipt,
        provenance=identity(),
        declarations=[export()],
        files=files,
        task_package=task,
        expected_config_hash="d" * 64,
    )
    assert outputs["report"]["payload"] == b'{"completed":true}'
    assert outputs["report"]["metadata"]["isolated"] is (placement == "companion")


@pytest.mark.parametrize(
    "field,value",
    [
        ("handle", "private-results"),
        ("visibility", "management"),
        ("service", "other"),
        ("isolated", False),
        ("controller_owned", False),
        ("agent_stopped", False),
        ("owner_session_id", "different-session"),
        ("environment_key", "0" * 64),
    ],
)
def test_managed_output_cannot_change_ownership_or_visibility(tmp_path, field, value):
    task, receipt, files = retained(tmp_path, "companion")
    receipt["entries"][0]["metadata"][field] = value
    with pytest.raises(ConfigError, match="Managed artifact"):
        archived_artifacts(
            receipt=receipt,
            provenance=identity(),
            declarations=[export()],
            files=files,
            task_package=task,
            expected_config_hash="d" * 64,
        )


def test_managed_output_requires_original_recipe_and_config(tmp_path):
    task, receipt, files = retained(tmp_path, "companion")
    with pytest.raises(ConfigError, match="frozen environment"):
        archived_artifacts(
            receipt=receipt, provenance=identity(), declarations=[export()], files=files
        )
    with pytest.raises(ConfigError, match="ownership"):
        archived_artifacts(
            receipt=receipt,
            provenance=identity(),
            declarations=[export()],
            files=files,
            task_package=task,
            expected_config_hash="0" * 64,
        )
    task["environment"]["readiness"]["argv"] = ["false"]
    with pytest.raises(ConfigError, match="ownership"):
        archived_artifacts(
            receipt=receipt,
            provenance=identity(),
            declarations=[export()],
            files=files,
            task_package=task,
            expected_config_hash="d" * 64,
        )


def test_empty_exports_do_not_erase_finalize_failure_in_archive(tmp_path):
    class FailedFreeze:
        def quiesce(self):
            raise RuntimeError("lost environment")

    receipt = collect_session_artifacts(
        workspace=FailedFreeze(),
        sessions_root=tmp_path / "sessions",
        session_id=identity()["session_id"],
        provenance=identity(),
        declarations=[],
    )
    assert not receipt["complete"]
    assert (
        archived_artifacts(receipt=receipt, provenance=identity(), declarations=[], files={}) == {}
    )
