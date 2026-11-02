"""Reject unsupported/private-plan contracts before starting Actors (Spec-0084/T5)."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ahe_beta.evaluation.adapters import container, profiles
from ahe_beta.evaluation.adapters.custom import CustomAdapter
from ahe_beta.evaluation.contracts import InputValidationError
from ahe_beta.evaluation.service import build_request
from ahe_beta.experiment.assessment_worker import registration
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.grading_inputs import load_grading_plan

REVISION = "a" * 40


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    def no_docker(*args, **kwargs):
        raise AssertionError("static registration must not use Docker")

    monkeypatch.setattr(container, "run_docker", no_docker)
    key = Ed25519PrivateKey.generate().public_key()
    public = tmp_path / "worker.pub"
    public.write_bytes(
        key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    key_digest = sha(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    script = tmp_path / "verifier.py"
    script.write_bytes(b"private fixed script")
    task = {
        "id": "task",
        "kind": "ordinary",
        "source": {"kind": "local", "path": "source"},
        "artifacts": {"exports": [{"id": "answer", "source": "workspace", "required": True}]},
    }
    selection = {
        "adapter": "custom",
        "contract_version": 1,
        "task_ids": ["task"],
        "inputs": {"script": "script"},
        "timeout_seconds": 30,
        "config": {
            "image": "sha256:" + "b" * 64,
            "argv": ["python", "/grader/script.py"],
            "artifact_map": {"answer": "/inputs/answer.json"},
        },
    }
    document = {
        "schema_version": 1,
        "materials": {"script": {"path": str(script), "sha256": sha(script.read_bytes())}},
        "graders": [selection],
    }
    path = tmp_path / "plan.json"

    def register():
        path.write_text(json.dumps(document))
        config = {
            "evaluation": {
                "session_grading": {
                    "runner": "external",
                    "plan_sha256": sha(path.read_bytes()),
                    "worker_key_sha256": key_digest,
                }
            }
        }
        return registration(config=config, tasks=[task], plan_path=path, public_key_path=public)

    return task, selection, document, path, register


def test_valid_metadata_does_not_construct_or_validate_fake_outputs(case, monkeypatch):
    task, selection, _, path, register = case
    original = CustomAdapter.validate_plan
    calls = []

    def validate_plan(self, request):
        assert not request.artifacts and not request.session and not request.session_id
        calls.append(request)
        return original(self, request)

    def forbid_runtime_validation(*args):
        raise AssertionError("runtime artifact validation must not run before an Actor")

    monkeypatch.setattr(CustomAdapter, "validate_plan", validate_plan)
    monkeypatch.setattr(CustomAdapter, "validate_inputs", forbid_runtime_validation)
    public = register()
    assert len(calls) == 1
    assert set(public["selections"]["task"]) == {"adapter", "contract_version", "timeout_seconds"}
    assert "private fixed script" not in str(public) and str(path) not in str(public)
    # Runtime still refuses absent real outputs after static validation succeeds.
    with pytest.raises(InputValidationError, match="missing_required_outputs"):
        build_request(
            task={"id": "task", "kind": "ordinary", "package": task, "digest": "d"},
            session={"session_id": "session"},
            outputs={},
            plan=load_grading_plan(path),
            selection=selection,
        )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"image": "python:latest"}, "image must"),
        ({"argv": ["python", "/tmp/unfrozen.py"]}, "frozen"),
        ({"artifact_map": {"answer": "/tests/test.py"}}, "below /inputs"),
        ({"artifact_map": {"undeclared": "/inputs/answer.json"}}, "public artifact export"),
        ({"execution_contract": "agent_stopped_task_environment"}, "unknown custom"),
    ],
)
def test_invalid_custom_plan_is_rejected_before_registration(case, change, match):
    _, selection, _, _, register = case
    selection["config"].update(change)
    with pytest.raises(ConfigError, match=match):
        register()


def test_missing_script_binding_is_rejected(case):
    _, selection, _, _, register = case
    selection["inputs"] = {}
    with pytest.raises(ConfigError, match="script"):
        register()


def test_managed_exports_rejected_even_when_grader_does_not_read_them(case):
    task, selection, _, _, register = case
    selection["config"]["artifact_map"] = {}
    task["artifacts"]["exports"][0]["source"] = "managed_service"
    with pytest.raises(ConfigError, match="managed service"):
        register()


def configure_swe(case, tmp_path):
    task, selection, document, _, _ = case
    task.update(kind="swebench", source={"kind": "git", "repo": "org/repo", "revision": REVISION})
    task.pop("artifacts")
    row = {
        "instance_id": "task",
        "repo": "org/repo",
        "base_commit": REVISION,
        "patch": "private",
        "test_patch": "private",
        "version": "1",
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
    }
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([row]))
    document["materials"] = {"dataset": {"path": str(dataset), "sha256": sha(dataset.read_bytes())}}
    selection.update(adapter="swebench", inputs={"dataset": "dataset"}, config={})
    return dataset, row


def test_swe_metadata_validates_dataset_against_declared_source_before_freezing(case, tmp_path):
    configure_swe(case, tmp_path)
    assert case[4]()["selections"]["task"]["adapter"] == "swebench"
    case[0]["source"]["revision"] = "c" * 40
    with pytest.raises(ConfigError, match="repo/base_commit"):
        case[4]()


def test_swe_missing_private_official_fields_rejected(case, tmp_path):
    dataset, row = configure_swe(case, tmp_path)
    row.pop("FAIL_TO_PASS")
    dataset.write_text(json.dumps([row]))
    case[2]["materials"]["dataset"]["sha256"] = sha(dataset.read_bytes())
    with pytest.raises(ConfigError, match="FAIL_TO_PASS"):
        case[4]()


def test_adapter_cannot_be_applied_to_an_unrelated_benchmark(case):
    case[1]["adapter"] = "nl2repo"
    with pytest.raises(ConfigError, match="differs from frozen benchmark"):
        case[4]()


def terminal_fixture(case, tmp_path, monkeypatch, *, mode="separate", managed=False):
    task, selection, document, _, _ = case
    artifact = (
        "{source='/app/out',target='/app/out',service='database'}" if managed else "'/app/out'"
    )
    files = {
        "task.toml": (f"artifacts=[{artifact}]\n[verifier]\nenvironment_mode='{mode}'\n").encode(),
        "tests/test.sh": b"echo fixed",
        "environment/Dockerfile": b"FROM fixed",
    }
    modes = dict.fromkeys(files, 0o644)
    monkeypatch.setitem(
        profiles.PROFILES,
        "fixture",
        {
            "adapter": "terminal-bench",
            "revision": REVISION,
            "task_blob": profiles.git_object("blob", files["task.toml"]).hex(),
            "tests_tree": profiles.git_tree(files, modes, "tests/").hex(),
            "environment_tree": profiles.git_tree(files, modes, "environment/").hex(),
        },
    )
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.mode = modes[name]
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    bundle = tmp_path / "task.tar"
    bundle.write_bytes(buffer.getvalue())
    task.update(
        kind="benchmark",
        benchmark={"suite": "terminal-bench", "instance_id": "fixture", "revision": REVISION},
    )
    document["materials"] = {"bundle": {"path": str(bundle), "sha256": sha(bundle.read_bytes())}}
    selection.update(
        adapter="terminal-bench",
        inputs={"task_bundle": "bundle"},
        config={
            "revision": REVISION,
            "build_official_environment": True,
            "artifact_map": {"answer": "/app/out"},
        },
    )


def test_pinned_profile_validation_runs_before_outputs_exist(case, tmp_path, monkeypatch):
    terminal_fixture(case, tmp_path, monkeypatch)
    assert case[4]()["selections"]["task"]["adapter"] == "terminal-bench"
    case[0]["benchmark"]["instance_id"] = "unknown-profile"
    with pytest.raises(ConfigError, match="profile not supported"):
        case[4]()


@pytest.mark.parametrize(
    "mode,managed,match",
    [
        ("same", False, "separate verifier"),
        ("separate", True, "managed service"),
    ],
)
def test_unsupported_environment_cannot_claim_workspace_reproducibility(
    case, tmp_path, monkeypatch, mode, managed, match
):
    terminal_fixture(case, tmp_path, monkeypatch, mode=mode, managed=managed)
    with pytest.raises(ConfigError, match=match):
        case[4]()


def test_wrong_official_artifact_destination_rejected_before_actor(case, tmp_path, monkeypatch):
    terminal_fixture(case, tmp_path, monkeypatch)
    case[1]["config"]["artifact_map"]["answer"] = "/app/other"
    with pytest.raises(ConfigError, match="exactly match"):
        case[4]()
