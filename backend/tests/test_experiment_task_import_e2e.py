"""Spec-0076/T4: converted inputs use the existing frozen workload contract."""

from __future__ import annotations

import json
import re
import shlex
import uuid
from pathlib import Path

import pytest

from ahe_beta.experiment import cli, materials, workload
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.task_import import import_seed_tasks, import_text_task
from test_experiment_materials import prepared_inputs as base_prepared_inputs

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


def test_actual_historical_cards_freeze_via_existing_workload(prepared_inputs, tmp_path):
    imported = import_seed_tasks(
        library=ROOT / "research/archives/legacy-materials/seeds.json",
        output=tmp_path / "converted",
    )
    config = json.loads(prepared_inputs.read_text())
    config["workload"].pop("kind")
    config["workload"].pop("task_package")
    config["workload"]["task_packages"] = imported["task_packages"]
    cards = json.loads((ROOT / "examples/personas/library.json").read_text())[:7]
    (tmp_path / "personas.json").write_text(json.dumps(cards))
    config["workload"]["persona_ids"] = [card["id"] for card in cards]
    config["rounds"] = {"count": 2, "sessions_per_round": 7, "max_parallel_users": 2}
    prepared_inputs.write_text(json.dumps(config))
    preview = materials.check_materials(prepared_inputs)
    assert len(preview["task_packages"]) == 7
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    run_dir = Path(manifest["run_dir"])
    catalog = workload.read_task_catalog(run_dir, manifest)
    original_packages = {Path(path).parent.name: Path(path) for path in imported["task_packages"]}
    plan = workload.read_session_plan(run_dir, manifest)
    assert len(catalog["tasks"]) == 7 and len(plan["rounds"][0]) == 7
    assert {binding["task_id"] for binding in plan["rounds"][0]} == {
        task["id"] for task in catalog["tasks"]
    }
    for task in catalog["tasks"]:
        assert task["kind"] == "ordinary" and task["source_snapshot"]["files"].keys() == {
            "README.md"
        }
        assert task["package"]["not_in_benchmark"] is True
        frozen_instruction = workload.task_material_path(run_dir, manifest, task, "instruction")
        original_instruction = original_packages[task["id"]].parent / "instruction.md"
        assert frozen_instruction.read_bytes() == original_instruction.read_bytes()
    # Imported inputs can change later; the prepared run keeps its original bytes.
    Path(imported["task_packages"][0]).write_text("changed after freezing")
    materials.verify_materials(manifest)
    changed = workload.task_material_path(run_dir, manifest, catalog["tasks"][0], "script")
    changed.write_text("tampered frozen setup")
    with pytest.raises(ConfigError):
        materials.verify_materials(manifest)


def test_hidden_seed_evidence_never_enters_frozen_run(prepared_inputs, tmp_path):
    sentinel = "heldout-" + uuid.uuid4().hex
    library = tmp_path / "seed-cards.json"
    library.write_text(
        json.dumps(
            [
                {
                    "id": "safe-task",
                    "source": {"not_in_benchmark": True},
                    "task": {"prompt": "Implement a small response formatter."},
                    "oracle": {"answer": sentinel},
                    "gates": [sentinel],
                    "env": {"test_cmd": sentinel},
                    "provenance": {"evidence": sentinel},
                }
            ]
        )
    )
    result = import_seed_tasks(library=library, output=tmp_path / "safe-converted")
    config = json.loads(prepared_inputs.read_text())
    config["workload"].pop("kind")
    config["workload"].pop("task_package")
    config["workload"]["task_packages"] = result["task_packages"]
    prepared_inputs.write_text(json.dumps(config))
    manifest = materials.prepare_materials(prepared_inputs, tmp_path / "runs")
    materials.verify_materials(manifest)
    run_dir = Path(manifest["run_dir"])
    assert sentinel.encode() in library.read_bytes()
    assert all(
        sentinel.encode() not in path.read_bytes() for path in run_dir.rglob("*") if path.is_file()
    )


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_imported_text_checks_with_both_existing_public_templates(tmp_path, backend):
    # Both backends consume the same package; this check provisions neither of them.
    result = import_text_task(
        instruction=ROOT / "examples/seed-inputs/instruction.md",
        task_id="current-text-example",
        output=tmp_path / "text-tasks",
        not_in_benchmark=True,
    )
    config = json.loads((ROOT / f"examples/experiments/u1-{backend}.json").read_text())
    config["workload"].pop("kind", None)
    config["workload"].pop("task_package", None)
    config["workload"].pop("interaction_plan", None)
    config["workload"]["task_packages"] = result["task_packages"]
    config["workload"]["persona_library"] = str(ROOT / "examples/personas/library.json")
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(config))
    report = materials.check_materials(path)
    assert report["ok"] is True and report["config"]["runtime"]["backend"] == backend
    assert report["task_packages"][0]["id"] == "current-text-example"


def test_current_seed_example_converts_and_only_declared_materials_are_emitted(tmp_path):
    result = import_seed_tasks(
        library=ROOT / "examples/seed-inputs/library.json", output=tmp_path / "current"
    )
    index = json.loads(Path(result["index_file"]).read_text())
    assert index["task_packages"]
    for relative in index["task_packages"]:
        package = json.loads((Path(result["output_dir"]) / relative).read_text())
        assert package["kind"] == "ordinary" and package["not_in_benchmark"] is True
    assert not list(Path(result["output_dir"]).rglob("*sidecar*"))


def _document_commands(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip().startswith("uv run ") and "backend/scripts/experiment.py" in line
    ]


def test_bilingual_tutorial_commands_parse_and_match():
    english = ROOT / "docs/tutorials/seed-task-import.md"
    chinese = ROOT / "docs/tutorials/seed-task-import.zh-CN.md"
    commands = _document_commands(english)
    assert commands and commands == _document_commands(chinese)
    parser = cli.build_parser()
    for command in commands:
        arguments = shlex.split(command.split("backend/scripts/experiment.py", 1)[1])
        if ">" in arguments:
            arguments = arguments[: arguments.index(">")]
        parser.parse_args(arguments)
    for document in (english, chinese):
        for reference in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            if reference.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = (document.parent / reference.split("#", 1)[0]).resolve()
            assert target.is_relative_to(ROOT) and target.exists(), reference
