"""Spec-0073/T1: freeze real per-task materials and logical session bindings offline."""

import copy
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from auto_designer.experiment import context, materials, workload
from auto_designer.experiment.config import ConfigError, config_hash
from test_experiment_config_v2 import package, write
from test_experiment_materials import prepared_inputs as base_prepared_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def multiple_inputs(prepared_inputs, tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    (second / "repo").mkdir()
    (second / "repo/second.py").write_text("TASK = 'second'\n")
    (second / "instruction.md").write_text("Implement the second task.")
    (second / "setup.sh").write_text("#!/bin/sh\nprintf second\n")
    (second / "requirements.lock").write_text("second-only==1.0\n")
    task = package()
    task.update(id="second-task", interaction="direct")
    write(second / "task.json", task)
    config = json.loads(prepared_inputs.read_text())
    config["workload"].pop("kind")
    config["workload"].pop("task_package")
    config["workload"]["task_packages"] = ["../task.json", "../second/task.json"]
    cards = json.loads(
        (Path(__file__).resolve().parents[2] / "examples/personas/library.json").read_text()
    )[:4]
    write(tmp_path / "personas.json", cards)
    config["workload"]["persona_ids"] = [card["id"] for card in cards]
    config["rounds"] = {"count": 2, "sessions_per_round": 4, "max_parallel_users": 2}
    write(prepared_inputs, config)
    return prepared_inputs


def task_resources(catalog):
    return {
        task["id"]: {
            "kind": "docker-seed",
            "params": {"image": f"image-{task['id']}"},
            "setup": [],
            "task_digest": task["digest"],
            "recipe_hash": "recipe-proof",
            "status": "prepared",
            "source_revision": task["source_snapshot"]["revision"],
            "source_hash": config_hash(data=task["source_snapshot"]["files"]),
        }
        for task in catalog["tasks"]
    }


def test_preview_cycles_slots_without_final_content_claims(multiple_inputs, monkeypatch):
    monkeypatch.setattr(
        materials, "_checkout_git", lambda **kwargs: pytest.fail("offline Git fetch")
    )
    report = materials.check_materials(multiple_inputs)
    assert report["preview"] == {"frozen": False}
    assert "catalog_hash" not in report and "plan_hash" not in report
    personas = report["persona_ids"]
    assert (
        report["interaction_plan"]
        == [
            [
                [personas[0], "simple-task"],
                [personas[1], "second-task"],
                [personas[2], "simple-task"],
                [personas[3], "second-task"],
            ]
        ]
        * 2
    )
    assert all("digest" not in task for task in report["task_packages"])


@pytest.mark.parametrize("n_users", [4, 8])
def test_single_task_accepts_many_distinct_personas(prepared_inputs, tmp_path, n_users):
    cards = json.loads(
        (Path(__file__).resolve().parents[2] / "examples/personas/library.json").read_text()
    )[:n_users]
    write(tmp_path / "personas.json", cards)
    config = json.loads(prepared_inputs.read_text())
    config["workload"]["persona_ids"] = [card["id"] for card in cards]
    config["rounds"].update(sessions_per_round=n_users, max_parallel_users=2)
    write(prepared_inputs, config)
    preview = materials.check_materials(prepared_inputs)["interaction_plan"]
    assert len(preview[0]) == n_users
    assert {pair[1] for pair in preview[0]} == {"simple-task"}
    assert len({pair[0] for pair in preview[0]}) == n_users


def test_default_uses_global_slot_number_not_per_round_restart(multiple_inputs):
    config = materials.check_materials(multiple_inputs)["config"]
    config["rounds"].update(sessions_per_round=3)
    tasks = [{"id": "one"}, {"id": "two"}]
    plan = workload.interaction_plan(config, tasks)
    personas = config["workload"]["persona_ids"]
    assert plan[1][0] == [personas[3], "two"]
    assert plan[1][1] == [personas[0], "one"]


def test_freeze_two_tasks_captures_separate_source_setup_and_interaction(multiple_inputs, tmp_path):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    catalog = workload.read_task_catalog(root, manifest)
    tasks = workload.catalog_tasks(catalog)
    assert [task["id"] for task in tasks] == ["simple-task", "second-task"]
    assert tasks[0]["digest"] != tasks[1]["digest"]
    for task, filename, instruction in zip(
        tasks,
        ["main.py", "second.py"],
        ["Improve visible behavior.", "Implement the second task."],
        strict=True,
    ):
        assert (
            workload.task_material_path(root, manifest, task, "instruction").read_text()
            == instruction
        )
        with tarfile.open(
            workload.task_material_path(root, manifest, task, "source_archive")
        ) as archive:
            assert archive.getnames() == [filename]
    assert (
        workload.task_material_path(root, manifest, tasks[1], "requirements_lock").read_text()
        == "second-only==1.0\n"
    )
    plan = workload.read_session_plan(root, manifest)
    assert plan["rounds"][0][0]["interaction"] == "simulated_user"
    assert plan["rounds"][0][1]["interaction"] == "direct"
    assert plan["rounds"][0][1]["task_digest"] == tasks[1]["digest"]
    assert plan["rounds"][1][3]["round_no"] == 2 and plan["rounds"][1][3]["slot"] == 3
    assert "session_id" not in plan["rounds"][0][0]
    assert manifest["workload_contract_version"] == 1
    assert manifest["catalog_hash"] == manifest["materials"]["task_catalog"]["sha256"]
    assert manifest["source_snapshot"]["entrypoint"]["module"].endswith(".unified")
    materials.verify_materials(manifest)


def test_mixed_kind_git_preview_then_verified_source_freeze(multiple_inputs, tmp_path, monkeypatch):
    second_path = tmp_path / "second/task.json"
    second = json.loads(second_path.read_text())
    config = json.loads(multiple_inputs.read_text())
    revision = config["source"]["openagents"]["revision"]
    second.update(
        kind="swebench",
        source={
            "kind": "git",
            "url": "https://example.com/task.git",
            "repo": "org/repo",
            "revision": revision,
        },
    )
    second.pop("not_in_benchmark")
    write(second_path, second)
    monkeypatch.setattr(
        materials, "_checkout_git", lambda **kwargs: pytest.fail("preview must not fetch")
    )
    report = materials.check_materials(multiple_inputs)
    assert [task["kind"] for task in report["task_packages"]] == ["ordinary", "swebench"]
    assert "digest" not in report["task_packages"][1]

    def checkout(*, url, revision, destination):
        shutil.copytree(tmp_path / "oa", destination)

    monkeypatch.setattr(materials, "_checkout_git", checkout)
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    task = workload.read_task_catalog(Path(manifest["run_dir"]), manifest)["tasks"][1]
    assert task["source_snapshot"]["revision"] == revision
    assert "openagents/__init__.py" in task["source_snapshot"]["files"]


@pytest.mark.parametrize(
    "mutation,message",
    [
        (
            lambda config: config["workload"].update(task_package="../task.json", kind="ordinary"),
            "not valid",
        ),
        (lambda config: config["runtime"].update(local={"seed_image": "seed:v1"}), "single task"),
    ],
)
def test_input_branches_and_multi_seed_override_fail_offline(multiple_inputs, mutation, message):
    config = json.loads(multiple_inputs.read_text())
    mutation(config)
    write(multiple_inputs, config)
    with pytest.raises(ConfigError, match=message):
        materials.check_materials(multiple_inputs)


def test_duplicate_task_ids_and_duplicate_personas_fail(multiple_inputs, tmp_path):
    second_path = tmp_path / "second/task.json"
    second = json.loads(second_path.read_text())
    second["id"] = "simple-task"
    write(second_path, second)
    with pytest.raises(ConfigError, match="duplicate task IDs"):
        materials.check_materials(multiple_inputs)
    second["id"] = "second-task"
    write(second_path, second)
    config = json.loads(multiple_inputs.read_text())
    p = config["workload"]["persona_ids"][0]
    config["workload"]["interaction_plan"] = [[[p, "simple-task"]] * 4] * 2
    write(multiple_inputs, config)
    with pytest.raises(ConfigError, match="duplicate persona"):
        materials.check_materials(multiple_inputs)


def test_second_task_freeze_failure_is_atomic_and_names_task(
    multiple_inputs, tmp_path, monkeypatch
):
    original = materials._archive_snapshot

    def archive(*, root, files, destination):
        if "second-task" in str(destination):
            raise ConfigError("second task archive failed")
        original(root=root, files=files, destination=destination)

    monkeypatch.setattr(materials, "_archive_snapshot", archive)
    with pytest.raises(ConfigError, match="second task archive failed"):
        materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    assert not list((tmp_path / "runs").glob("20*"))
    assert not list((tmp_path / "runs").glob(".preparing-*"))


def test_context_selects_each_frozen_task_and_rejects_stale_resources(
    multiple_inputs, tmp_path, monkeypatch
):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    catalog = workload.read_task_catalog(root, manifest)
    workspaces = task_resources(catalog)
    resources = {
        "gitea": {"url": "http://localhost:3000", "owner": "owner", "repo": "repo"},
        "task_workspaces": workspaces,
    }
    env = context.build_controller_environment(
        run_dir=root,
        manifest=manifest,
        credentials={
            "GITEA_TOKEN": "secret",
            "MODEL_BASE_URL": "https://model.test",
            "MODEL_API_KEY": "model-secret",
        },
        resources=resources,
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    context.require_controller_context()
    first = context.frozen_scenario("simple-task")
    second = context.frozen_scenario("second-task")
    assert first.description != second.description
    assert first.workspace.params["task_id"] == "simple-task"
    assert second.workspace.params["task_kind"] == "ordinary"
    assert second.workspace.params["task_digest"] == catalog["tasks"][1]["digest"]
    assert second.workspace.params["interaction"] == "direct"
    with pytest.raises(ConfigError, match="explicit task_id"):
        context.frozen_scenario()
    wrong = copy.deepcopy(workspaces)
    wrong["second-task"]["task_digest"] = "stale"
    with pytest.raises(ConfigError, match="second-task"):
        workload.verify_task_workspaces(catalog, wrong)
    wrong.pop("second-task")
    with pytest.raises(ConfigError, match="match the frozen catalog"):
        workload.verify_task_workspaces(catalog, wrong)
    assert "secret" not in (root / "runtime/controller-context.json").read_text()


def test_legacy_frozen_manifest_is_verified_without_mutation(tmp_path):
    legacy_config = {
        "schema_version": 2,
        "workload": {"kind": "ordinary", "task_package": "/missing/original.json"},
    }
    old = {
        "run_dir": str(tmp_path),
        "config": legacy_config,
        "config_hash": config_hash(data=legacy_config),
        "materials": {},
        "plan_hash": "old-plan",
    }
    frozen = copy.deepcopy(old)
    materials.verify_materials(old)
    assert old == frozen
    old["workload_contract_version"] = 17
    with pytest.raises(ConfigError, match="Unknown workload_contract_version"):
        materials.verify_materials(old)


def test_unknown_catalog_version_and_tampered_plan_fail_before_use(multiple_inputs, tmp_path):
    with pytest.raises(ConfigError, match="contract_version"):
        workload.catalog_tasks({"contract_version": 8, "tasks": []})
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    path = Path(manifest["run_dir"]) / manifest["materials"]["session_plan"]["path"]
    plan = json.loads(path.read_text())
    plan["rounds"][0][0]["task_id"] = "second-task"
    write(path, plan)
    manifest["plan_hash"] = materials.sha256_file(path)
    manifest["materials"]["session_plan"]["sha256"] = manifest["plan_hash"]
    with pytest.raises(ConfigError, match="logical task/persona"):
        materials.verify_materials(manifest)


def test_archive_inventory_mismatch_rejected_even_when_outer_sha_is_updated(
    multiple_inputs, tmp_path
):
    import io

    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    record = manifest["materials"]["task:simple-task:source_archive"]
    path = Path(manifest["run_dir"]) / record["path"]
    payload = b"different source content"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("main.py")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    record["sha256"] = materials.sha256_file(path)
    with pytest.raises(ConfigError, match="source inventory mismatch: simple-task"):
        materials.verify_materials(manifest)


@pytest.mark.parametrize("version", [True, False, "1", 1.0, None])
def test_workload_contract_requires_integer_one_at_all_boundaries(
    multiple_inputs, tmp_path, version
):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    manifest["workload_contract_version"] = version
    with pytest.raises(ConfigError, match="workload_contract_version"):
        workload.read_task_catalog(root, manifest)
    with pytest.raises(ConfigError, match="workload_contract_version"):
        materials.verify_materials(manifest)
    with pytest.raises(ConfigError, match="workload_contract_version"):
        context.write_controller_context(
            run_dir=root, manifest=manifest, credentials={}, resources={}
        )


@pytest.mark.parametrize("version", [True, False, "1", 1.0, None])
@pytest.mark.parametrize("key", ["task_catalog", "session_plan"])
def test_frozen_material_contract_requires_integer_one(multiple_inputs, tmp_path, version, key):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    record = manifest["materials"][key]
    path = Path(manifest["run_dir"]) / record["path"]
    document = json.loads(path.read_text())
    document["contract_version"] = version
    write(path, document)
    record["sha256"] = materials.sha256_file(path)
    manifest["catalog_hash" if key == "task_catalog" else "plan_hash"] = record["sha256"]
    with pytest.raises(ConfigError, match="contract_version"):
        materials.verify_materials(manifest)


@pytest.mark.parametrize(
    "field,value", [("round_no", True), ("round_no", 1.0), ("slot", False), ("slot", 0.0)]
)
def test_plan_scalar_types_cannot_masquerade_as_compiled_bindings(
    multiple_inputs, tmp_path, field, value
):
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    record = manifest["materials"]["session_plan"]
    path = Path(manifest["run_dir"]) / record["path"]
    document = json.loads(path.read_text())
    document["rounds"][0][0][field] = value
    write(path, document)
    record["sha256"] = materials.sha256_file(path)
    manifest["plan_hash"] = record["sha256"]
    with pytest.raises(ConfigError, match="logical task/persona"):
        materials.verify_materials(manifest)
