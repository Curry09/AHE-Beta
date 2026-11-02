"""Spec-0075/T3: production sessions -> sealed archive -> official CLI boundary.

Models, forge and workspace providers use the existing mixed-run substitutes.
The real session runners export real Git diffs, the real Orchestrator seals two
rounds, and the real engine and collector produce the grading source. Official
Docker evaluation is substituted at its subprocess boundary; no benchmark score
from these fixtures is a real official result.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import test_experiment_multitask_e2e as mixed
from ahe_beta import invocation
from ahe_beta.experiment import collection, engine, materials, workload
from ahe_beta.experiment.manifest import run_lock, update_runtime
from test_experiment_materials import prepared_inputs as base_prepared_inputs
from test_experiment_workload import multiple_inputs as base_multiple_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def multiple_inputs(prepared_inputs, tmp_path):
    return base_multiple_inputs.__wrapped__(prepared_inputs, tmp_path)


def _completed_mixed_archive(multiple_inputs, tmp_path, monkeypatch, backend):
    original_send = mixed.BoundaryHarness.send

    def edit_tracked(self, message):
        response = original_send(self, message)
        # The original fixture creates an untracked file, outside git diff.
        # Modify a tracked file to exercise a genuine complete prediction.
        existing = self.workspace.read_text("pyproject.toml")
        self.workspace.write_text(
            "pyproject.toml", existing + "\n# session change\n" + "# x\n" * 4000
        )
        return response

    monkeypatch.setattr(mixed.BoundaryHarness, "send", edit_tracked)
    mixed.test_two_round_mixed_workload_stops_resumes_and_delivers_nonempty(
        multiple_inputs, tmp_path, monkeypatch, backend
    )
    roots = [path for path in (tmp_path / "runs").iterdir() if (path / "manifest.json").is_file()]
    assert len(roots) == 1
    root = roots[0]
    manifest = json.loads((root / "manifest.json").read_text())
    # The reused in-process fixture has no controller display callback. Project
    # its real seals through the production invocation recorder, as the unified
    # controller does, so the engine can verify the completed round set.
    recorder = invocation.InvocationStore(root=root / "data/role_runs" / root.name)
    recorder.write_manifest(data={"run_id": root.name, "roster": {"user": 4}, "rounds": []})
    recovery = json.loads((root / "checkpoints/recovery.json").read_text())
    for number, row in recovery["rounds"].items():
        recorder.append_round(
            round_no=int(number), user_sha=row["user_sha"], sealed_sha=row["sealed_sha"]
        )
    # The provider/model integration ran in-process. Generate an authentic
    # owned engine terminal receipt from the already sealed recovery state.
    engine.launch_controller(
        run_dir=root,
        command=[sys.executable, "-c", "import time; time.sleep(0.4)"],
        env={},
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        controller = engine.inspect_controller(root)
        if controller["state"] == "EXITED":
            break
        time.sleep(0.05)
    else:
        pytest.fail("owned fixture controller did not reach EXITED")
    assert controller["experiment_complete"] is True and controller["running"] is False
    receipt = collection.collect_archive(
        run_dir=root,
        manifest=manifest,
        snapshot={
            "snapshot_dir": str(root),
            "consistent": True,
            "terminal": True,
            "controller": controller,
        },
        credentials={},
    )
    assert receipt["collection_state"] == "COMPLETE"
    with run_lock(run_dir=root):
        update_runtime(
            run_dir=root,
            action="terminal-collected",
            changes={
                "experiment_state": "COMPLETED",
                "resource_state": "PROVISIONED",
                "collection_state": "COMPLETE",
                "observation": "KNOWN",
                "collection": receipt,
                "launch_receipt": controller,
                "provider": {"controller": controller},
            },
        )
    tasks = workload.read_task_catalog(root, manifest)["tasks"]
    task = next(task for task in tasks if task["kind"] == "swebench")
    dataset = tmp_path / "official-fixture.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "instance_id": task["id"],
                    "repo": task["package"]["source"]["repo"],
                    "base_commit": task["package"]["source"]["revision"],
                    "test_patch": "hidden evaluator-only test patch",
                    "patch": "hidden evaluator-only gold patch",
                    "version": "1",
                    "FAIL_TO_PASS": ["test_visible_behavior"],
                    "PASS_TO_PASS": [],
                }
            ]
        )
    )
    return root, manifest, dataset


def _original_hashes(root):
    paths = [
        root / "manifest.json",
        root / "checkpoints/recovery.json",
        root / "runtime.json",
        root / "journal.jsonl",
    ]
    paths.extend((root / "archive").glob("*"))
    paths.extend((root / "data/role_runs" / root.name).rglob("*.json"))
    paths.extend((root / "data/role_runs" / root.name / "predictions").glob("*.patch"))
    return {str(path): materials.sha256_file(path) for path in paths if path.is_file()}


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_sealed_production_sessions_grade_without_mutating_experiment(
    multiple_inputs, tmp_path, monkeypatch, backend
):
    from ahe_beta.evaluation.adapters import swebench as adapter
    from ahe_beta.evaluation.adapters.swebench import _SWEbenchRunner
    from ahe_beta.experiment import grading, workload

    monkeypatch.setattr(adapter, "resolve_image", lambda *args, **kwargs: "sha256:" + "f" * 64)
    monkeypatch.setattr(adapter, "run_docker", lambda *args, **kwargs: "")

    root, manifest, dataset = _completed_mixed_archive(
        multiple_inputs, tmp_path, monkeypatch, backend
    )
    original = _original_hashes(root)
    catalog = workload.read_task_catalog(root, manifest)
    plan = tmp_path / "grading-plan.json"
    plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "materials": {
                    "dataset": {"path": str(dataset), "sha256": materials.sha256_file(dataset)}
                },
                "graders": [
                    {
                        "adapter": "swebench",
                        "contract_version": 1,
                        "task_ids": [
                            task["id"] for task in catalog["tasks"] if task["kind"] == "swebench"
                        ],
                        "inputs": {"dataset": "dataset"},
                        "timeout_seconds": 1800,
                    }
                ],
            }
        )
    )
    common = {"run_id": manifest["run_id"], "root": root.parent, "plan": plan}
    offline = grading.grade_run(**common, offline=True)
    assert offline["ok"] is True
    assert _original_hashes(root) == original
    assert not (root / "evaluation").exists()

    commands = []
    original_run = subprocess.run

    def official_boundary(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps([{"Id": "sha256:" + "f" * 64}]), ""
            )
        if "swebench.harness.run_evaluation" not in command:
            return original_run(command, **kwargs)
        commands.append(command)
        prediction = Path(command[command.index("--predictions_path") + 1])
        record = json.loads(prediction.read_text())
        assert len(record["model_patch"]) > 12_000
        assert "hidden evaluator-only" not in record["model_patch"]
        run_id = command[command.index("--run_id") + 1]
        report_dir = Path(command[command.index("--report_dir") + 1])
        (report_dir / f"ahe-beta.{run_id}.json").write_text(
            json.dumps({"resolved_ids": [record["instance_id"]], "unresolved_ids": []})
        )
        return subprocess.CompletedProcess(command, 0, "scripted official boundary", "")

    # No actual official Docker run or dependency installation in this offline
    # fixture. The evaluator's prediction creation and report parsing stay real.
    monkeypatch.setattr(_SWEbenchRunner, "preflight", staticmethod(lambda: None))
    monkeypatch.setattr(subprocess, "run", official_boundary)
    first = grading.grade_run(**common)
    assert first["ok"] is True and len(commands) == 2
    assert _original_hashes(root) == original
    second = grading.grade_run(**common)
    assert second["ok"] is True and len(commands) == 4
    assert first["report_dir"] != second["report_dir"]
    assert _original_hashes(root) == original
    assert len(list((root / "evaluation").glob("*/intent.json"))) == 2
    # The source archive is immutable even when live observations later differ.
    session = next((root / "data/role_runs" / root.name / "sessions").glob("op-*.json"))
    saved = session.read_bytes()
    session.write_text("changed live observation, deliberately ignored by grade")
    try:
        assert grading.grade_run(**common, offline=True)["ok"] is True
    finally:
        session.write_bytes(saved)
    assert _original_hashes(root) == original
