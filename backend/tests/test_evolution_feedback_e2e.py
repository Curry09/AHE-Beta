"""Spec-0084/T6: public preparation, real hashes and private material separation.

These offline checks never claim a Docker, E2B or model-driven experiment passed.
The optional script --grader-controls executes the same fixed verifier in Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from auto_designer.experiment.assessment_worker import public_key_bytes, registration
from auto_designer.experiment.config import ConfigError, load_config_v2, load_task_package
from auto_designer.experiment.grading_inputs import load_grading_plan
from auto_designer.experiment.runtime import check_v2

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend/scripts/e2e-spec-0084-evolution-feedback.sh"
# Deliberately synthetic format-only image identity: offline tests never pull/run it.
OFFLINE_IMAGE = "sha256:" + "a" * 64


def generate(path, backend="local", image=OFFLINE_IMAGE):
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--prepare-example",
            str(path),
            "--backend",
            backend,
            "--grader-image",
            image,
        ],
        env={**os.environ, "EVOLUTION_PYTHON": sys.executable},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_generated_enabled_example_uses_real_plan_key_hashes_and_seals_only_public_task(
    tmp_path, backend
):
    root = tmp_path / backend
    generated = generate(root, backend)
    assert generated.returncode == 0, generated.stderr
    receipt = json.loads(generated.stdout)
    assert receipt["backend_started"] is False
    config = load_config_v2(root / "experiment.json")
    options = config["evaluation"]["session_grading"]
    plan = load_grading_plan(root / "private/grading-plan.json")
    assert options["plan_sha256"] == plan.digest
    raw_key = public_key_bytes(root / "private/worker.pub")
    assert options["worker_key_sha256"] == hashlib.sha256(raw_key).hexdigest()
    assert stat.S_IMODE((root / "private/worker.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "private").stat().st_mode) == 0o700
    key = serialization.load_pem_private_key(
        (root / "private/worker.key").read_bytes(), password=None
    )
    assert (
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        == raw_key
    )
    task = load_task_package(root / "public/task/task.json")
    assert task["interaction"] == "direct" and task["not_in_benchmark"]
    assert task["artifacts"]["exports"][0]["path"] == "answer.json"
    assert not (Path(task["source"]["path"]) / "answer.json").exists()
    public_bytes = b"\n".join(
        path.read_bytes() for path in (root / "public").rglob("*") if path.is_file()
    )
    assert b"PRIVATE KEY" not in public_bytes
    assert b"verifier.py" not in public_bytes
    assert b"expected_passed" not in public_bytes
    bound = registration(
        config=config,
        tasks=[task],
        plan_path=root / "private/grading-plan.json",
        public_key_path=root / "private/worker.pub",
    )
    assert set(bound["selections"]) == {task["id"]}
    report = check_v2(
        config_path=root / "experiment.json",
        offline=True,
        grading_plan=root / "private/grading-plan.json",
        grading_worker_public_key=root / "private/worker.pub",
    )
    assert report["ok"]
    assert "PRIVATE KEY" not in json.dumps(report, default=str)


def test_preparation_never_reuses_keys_or_overwrites_existing_materials(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    assert generate(first).returncode == generate(second).returncode == 0
    assert (first / "private/worker.pub").read_bytes() != (
        second / "private/worker.pub"
    ).read_bytes()
    original = (first / "private/worker.key").read_bytes()
    assert generate(first).returncode != 0
    assert (first / "private/worker.key").read_bytes() == original


def test_prepare_rejects_floating_image_without_starting_anything(tmp_path):
    target = tmp_path / "never-created"
    result = generate(target, image="python:latest")
    assert result.returncode != 0 and "immutable image digest" in result.stderr
    assert not target.exists()


def test_private_material_tampering_invalidates_registration(tmp_path):
    root = tmp_path / "sample"
    assert generate(root).returncode == 0
    config = load_config_v2(root / "experiment.json")
    task = load_task_package(root / "public/task/task.json")
    (root / "private/verifier.py").write_text("print('replacement')\n")
    with pytest.raises(ConfigError, match="SHA-256 mismatch"):
        registration(
            config=config,
            tasks=[task],
            plan_path=root / "private/grading-plan.json",
            public_key_path=root / "private/worker.pub",
        )


def test_fixed_verifier_rule_has_positive_and_negative_controls_without_executing_task_code(
    tmp_path,
):
    root = tmp_path / "sample"
    assert generate(root).returncode == 0
    controls = json.loads((root / "private/controls.json").read_text())
    assert {row["expected_passed"] for row in controls} == {True, False}
    for row in controls:
        # Only our fixed trusted verifier reads inert JSON here; no task program runs.
        output = tmp_path / (row["name"] + "-result.json")
        subprocess.run(
            [
                sys.executable,
                str(root / "private/verifier.py"),
                str(root / "private" / row["path"]),
                str(output),
            ],
            check=True,
        )
        assert json.loads(output.read_text())["passed"] is row["expected_passed"]
