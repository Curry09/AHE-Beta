"""Spec-0081/T1: container recipes are strict, pure and independent of providers."""

import copy
import json
from pathlib import Path

import pytest

from ahe_beta.experiment.config import (
    ConfigError,
    load_task_package,
    validate_task_package_document,
)
from ahe_beta.experiment.task_environments.contract import (
    EnvironmentContractError,
    container_environment,
    environment_identity,
    environment_materials,
    resolve_container_paths,
)
from ahe_beta.experiment.workload import (
    catalog_tasks,
    task_artifact_declarations,
    task_digest,
    validate_artifact_backend,
    verify_task_workspaces,
)

IMAGE = "registry.example/task@sha256:" + "a" * 64


def container_package():
    return {
        "schema_version": 3,
        "kind": "ordinary",
        "not_in_benchmark": True,
        "id": "spreadsheet",
        "instruction_file": "instruction.md",
        "interaction": "direct",
        "environment": {
            "kind": "container",
            "image": IMAGE,
            "workdir": "/app",
            "readiness": {"argv": ["test", "-d", "/app"], "timeout_seconds": 5},
            "inputs": [
                {
                    "id": "workbook",
                    "material": {"path": "book.xlsx", "sha256": "b" * 64, "format": "file"},
                    "target": "/app/book.xlsx",
                }
            ],
        },
    }


def service(identifier="meter", dependencies=None):
    return {
        "id": identifier,
        "placement": "companion",
        "image": IMAGE,
        "argv": ["python3", "measure.py"],
        "depends_on": dependencies or [],
        "readiness": {"argv": ["test", "-e", "/ready"], "timeout_seconds": 3},
        "exports": [{"handle": "measurement-" + identifier, "path": "/results/result.json"}],
    }


def artifact(handle):
    return {
        "version": 1,
        "exports": [
            {
                "id": "measurement",
                "source": "managed_service",
                "handle": handle,
                "content_type": "application/json",
                "required": True,
                "max_bytes": 1024,
            }
        ],
    }


def test_non_python_task_needs_neither_fake_source_nor_setup(tmp_path):
    package = container_package()
    path = tmp_path / "task.json"
    path.write_text(json.dumps(package))
    (tmp_path / "instruction.md").write_text("Update the workbook.")
    actual = load_task_package(path)
    assert "source" not in actual and "setup" not in actual
    assert actual["instruction_file"] == str(tmp_path / "instruction.md")
    assert actual["environment"]["inputs"][0]["material"]["path"] == str(tmp_path / "book.xlsx")
    assert not (tmp_path / "book.xlsx").exists()  # No preparation or download in the loader.


def test_normalization_does_not_change_raw_identity_or_invent_image_user():
    raw = container_package()
    original = copy.deepcopy(raw)
    result = container_environment(raw)
    assert raw == original
    assert result["patch"] == "not_applicable"
    assert result["inputs"][0]["placement"] == "task"
    assert result["services"] == []
    assert "user" not in result
    result["inputs"][0]["target"] = "/other"
    assert raw == original
    assert environment_identity(raw) == environment_identity(original)


@pytest.mark.parametrize("version", [1, 2])
def test_current_task_documents_are_not_mutated(version):
    path = Path(__file__).parents[2] / "examples/tasks/order-service/task.json"
    package = json.loads(path.read_text())
    package["schema_version"] = version
    original = copy.deepcopy(package)
    validate_task_package_document(package)
    assert package == original and "environment" not in package


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(unrecognized=True),
        lambda p: p["environment"].update(unrecognized=True),
        lambda p: p["environment"].update(image="registry.example/task:latest"),
        lambda p: p["environment"].update(workdir="/app/../root"),
        lambda p: p["environment"].update(workdir="/app//repo"),
        lambda p: p["environment"].update(kind="namespace"),
        lambda p: p["environment"].update(resources={"memory_mb": True}),
        lambda p: p["environment"].update(resources={"cpus": 0}),
        lambda p: p["environment"].update(capabilities=["privileged"]),
        lambda p: p["environment"]["readiness"].update(timeout_seconds=0),
        lambda p: p["environment"]["readiness"].update(argv="echo ready"),
        lambda p: p["environment"]["readiness"].update(argv=[]),
        lambda p: p["environment"]["inputs"][0]["material"].update(sha256="latest"),
        lambda p: p["environment"]["inputs"][0]["material"].update(url="https://example.com/data"),
        lambda p: p["environment"]["inputs"][0].update(target="/opt/evolution-run/credentials"),
        lambda p: p["environment"]["inputs"][0].update(placement="unknown-service"),
    ],
)
def test_unknown_or_unsafe_declarations_rejected(change):
    package = container_package()
    change(package)
    with pytest.raises(ConfigError):
        validate_task_package_document(package)


def test_nan_command_budget_is_not_a_readiness_contract():
    package = container_package()
    package["environment"]["readiness"]["timeout_seconds"] = float("nan")
    with pytest.raises(ConfigError, match="finite"):
        validate_task_package_document(package)


def test_file_inventory_digests_are_not_treated_as_plaintext_credentials():
    package = container_package()
    package["environment"]["inputs"][0]["material"]["files"] = {"tokenizer.py": "a" * 64}
    validate_task_package_document(package)
    package["environment"]["services"] = [service()]
    package["environment"]["services"][0]["environment"] = {"API_TOKEN": "literal-secret"}
    with pytest.raises(ConfigError, match="Plaintext credential"):
        validate_task_package_document(package)


def test_material_paths_resolve_without_modifying_command_argv(tmp_path):
    raw = container_package()
    raw["environment"]["initialize"] = {
        "argv": ["python3", "relative-in-container.py"],
        "timeout_seconds": 10,
    }
    resolved = resolve_container_paths(raw, tmp_path)
    assert raw["instruction_file"] == "instruction.md"
    assert resolved["environment"]["initialize"]["argv"][1] == "relative-in-container.py"
    assert environment_materials(resolved)[0]["material"]["path"] == str(tmp_path / "book.xlsx")
    assert environment_identity(resolved) == environment_identity(raw)


def test_same_verified_input_from_a_mirror_has_same_recipe_identity():
    package = container_package()
    mirrored = copy.deepcopy(package)
    material = mirrored["environment"]["inputs"][0]["material"]
    material.pop("path")
    material["url"] = "https://mirror.example/book.xlsx"
    assert environment_identity(mirrored) == environment_identity(package)
    material["sha256"] = "d" * 64
    assert environment_identity(mirrored) != environment_identity(package)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/data",
        "https://example.com/data?token=x",
        "file:///tmp/data",
    ],
)
def test_download_urls_cannot_embed_credentials_or_bypass_transport(url):
    raw = container_package()
    material = raw["environment"]["inputs"][0]["material"]
    material.pop("path")
    material["url"] = url
    with pytest.raises(ConfigError):
        validate_task_package_document(raw)


def test_same_input_target_in_independent_containers_is_valid():
    package = container_package()
    package["environment"]["services"] = [service()]
    other = copy.deepcopy(package["environment"]["inputs"][0])
    other.update(id="meter-workbook", placement="meter")
    package["environment"]["inputs"].append(other)
    validate_task_package_document(package)
    other.pop("placement")
    with pytest.raises(ConfigError, match="overlap"):
        validate_task_package_document(package)


@pytest.mark.parametrize("dependencies", [["missing"], ["meter"], ["other", "other"]])
def test_unknown_cyclic_and_duplicate_service_dependencies_fail(dependencies):
    package = container_package()
    package["environment"]["services"] = [service(dependencies=dependencies)]
    with pytest.raises(ConfigError):
        validate_task_package_document(package)


def test_dependency_graph_can_be_declared_in_any_list_order():
    package = container_package()
    package["environment"]["services"] = [service("second", ["first"]), service("first")]
    validate_task_package_document(package)
    package["environment"]["services"][1]["depends_on"] = ["second"]
    with pytest.raises(ConfigError, match="cycle"):
        validate_task_package_document(package)


def test_main_container_variables_and_ordered_oneshot_service():
    package = container_package()
    package["environment"]["variables"] = {"KAFKA_BROKERS": "broker:9092"}
    seeder = service("seed", ["broker"])
    seeder.pop("readiness")
    seeder.update(mode="oneshot", timeout_seconds=30)
    package["environment"]["services"] = [seeder, service("broker")]
    validate_task_package_document(package)
    normalized = container_environment(package)
    assert normalized["variables"]["KAFKA_BROKERS"] == "broker:9092"
    assert normalized["services"][0]["mode"] == "oneshot"
    assert normalized["services"][1]["mode"] == "daemon"
    package["environment"]["variables"]["API_KEY"] = "secret-value"
    with pytest.raises(ConfigError, match="Plaintext credential"):
        validate_task_package_document(package)


@pytest.mark.parametrize("change", ["missing_budget", "readiness", "finalize", "unknown_mode"])
def test_oneshot_services_have_explicit_finite_execution_contract(change):
    package = container_package()
    seeder = service("seed")
    seeder.pop("readiness")
    seeder.update(mode="oneshot", timeout_seconds=30)
    package["environment"]["services"] = [seeder]
    if change == "missing_budget":
        seeder.pop("timeout_seconds")
    elif change in {"readiness", "finalize"}:
        seeder[change] = {"argv": ["true"], "timeout_seconds": 5}
    else:
        seeder["mode"] = "workflow"
    with pytest.raises(ConfigError):
        validate_task_package_document(package)


def test_in_task_daemon_can_declare_listener_handoff():
    package = container_package()
    daemon = service("server")
    daemon.update(placement="task", handoff_ports=[9000, 9001])
    daemon.pop("image")
    package["environment"]["services"] = [daemon]
    validate_task_package_document(package)
    assert container_environment(package)["services"][0]["handoff_ports"] == [9000, 9001]


@pytest.mark.parametrize("ports", [[0], [65536], [True], [9000, 9000]])
def test_listener_handoff_requires_real_unique_tcp_ports(ports):
    package = container_package()
    daemon = service("server")
    daemon.update(placement="task", handoff_ports=ports)
    daemon.pop("image")
    package["environment"]["services"] = [daemon]
    with pytest.raises(ConfigError):
        validate_task_package_document(package)


def test_companion_cannot_claim_actor_listener_handoff():
    package = container_package()
    daemon = service("meter")
    daemon["handoff_ports"] = [9000]
    package["environment"]["services"] = [daemon]
    with pytest.raises(ConfigError):
        validate_task_package_document(package)


def test_management_measurements_cannot_enter_public_artifact_projection():
    package = container_package()
    package["environment"]["services"] = [service()]
    package["artifacts"] = artifact("measurement-meter")
    with pytest.raises(ConfigError, match="task-visible"):
        validate_task_package_document(package)
    package["environment"]["services"][0]["exports"][0]["visibility"] = "task"
    validate_task_package_document(package)
    assert task_artifact_declarations(package) == package["artifacts"]["exports"]
    for backend in ("local", "e2b"):
        validate_artifact_backend(package, backend)
    package["artifacts"]["exports"][0]["handle"] = "not-registered"
    with pytest.raises(ConfigError, match="task-visible"):
        validate_task_package_document(package)


def test_management_visibility_is_the_default_in_normalized_environment():
    package = container_package()
    package["environment"]["services"] = [service()]
    env = container_environment(package)
    assert env["services"][0]["exports"][0]["visibility"] == "management"
    assert "visibility" not in package["environment"]["services"][0]["exports"][0]


def test_duplicate_service_export_handles_and_input_ids_fail():
    package = container_package()
    package["environment"]["services"] = [service()]
    package["environment"]["services"][0]["exports"].append(
        {"handle": "measurement-meter", "path": "/results/other.json"}
    )
    with pytest.raises(ConfigError, match="handles"):
        validate_task_package_document(package)
    package = container_package()
    package["environment"]["inputs"].append(copy.deepcopy(package["environment"]["inputs"][0]))
    with pytest.raises(ConfigError, match="Input IDs"):
        validate_task_package_document(package)


def test_swe_container_requires_real_git_metadata_and_patch():
    package = container_package()
    package.update(kind="swebench")
    package.pop("not_in_benchmark")
    with pytest.raises(ConfigError, match="source"):
        validate_task_package_document(package)
    package["source"] = {
        "kind": "git",
        "url": "https://github.com/example/repo.git",
        "repo": "example/repo",
        "revision": "f" * 40,
    }
    validate_task_package_document(package)
    assert container_environment(package)["patch"] == "git"
    package["environment"]["patch"] = "not_applicable"
    with pytest.raises(ConfigError, match="Git patch"):
        validate_task_package_document(package)


def test_container_workspace_identity_is_bound_to_recipe_and_task():
    package = container_package()
    record = {
        "id": package["id"],
        "kind": package["kind"],
        "interaction": package["interaction"],
        "package": package,
        "source_snapshot": {"image": IMAGE},
        "content_hashes": {"instruction": "c" * 64},
    }
    record["digest"] = task_digest(record)
    catalog = {"contract_version": 1, "tasks": [record]}
    assert catalog_tasks(catalog) == [record]
    workspace = {
        "kind": "container",
        "status": "prepared",
        "task_digest": record["digest"],
        "recipe_hash": environment_identity(package),
        "params": {
            "task_id": record["id"],
            "task_digest": record["digest"],
            "environment": container_environment(package),
        },
    }
    verify_task_workspaces(catalog, {record["id"]: workspace})
    workspace["params"]["environment"]["inputs"][0]["material"]["path"] = "/installed/book.xlsx"
    verify_task_workspaces(catalog, {record["id"]: workspace})
    workspace["params"]["environment"]["readiness"]["argv"] = ["true"]
    with pytest.raises(ConfigError, match="identity/content"):
        verify_task_workspaces(catalog, {record["id"]: workspace})
    workspace["params"]["environment"]["readiness"]["argv"] = ["test", "-d", "/app"]
    workspace["params"]["environment"]["image"] = IMAGE.replace("a" * 64, "b" * 64)
    with pytest.raises(ConfigError, match="identity/content"):
        verify_task_workspaces(catalog, {record["id"]: workspace})


def test_pure_contract_rejects_unknown_driver_without_a_config_import():
    package = container_package()
    package["environment"]["kind"] = "unavailable"
    with pytest.raises(EnvironmentContractError, match="container"):
        container_environment(package)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_interaction_override_reuses_materials_without_rewriting_source_package(tmp_path, version):
    from ahe_beta.experiment.config import load_config_v2, load_task_packages
    from test_experiment_config_v2 import definition, write
    from test_experiment_config_v2 import package as python_package

    task_path = tmp_path / "task.json"
    package = container_package() if version == 3 else python_package()
    package["schema_version"] = version
    package["interaction"] = "simulated_user"
    write(task_path, package)
    before = task_path.read_bytes()
    definition_ = definition()
    definition_["workload"]["interaction_overrides"] = {package["id"]: "direct"}
    config = load_config_v2(write(tmp_path / "configs/config.json", definition_))
    actual = load_task_packages(config)[0]
    assert actual["interaction"] == "direct"
    expected = load_task_package(task_path)
    expected["interaction"] = "direct"
    assert actual == expected
    assert task_path.read_bytes() == before
    assert config["workload"]["interaction_overrides"] == {package["id"]: "direct"}


def test_absent_interaction_override_preserves_old_loaded_document(tmp_path):
    from ahe_beta.experiment.config import load_config_v2, load_task_packages
    from test_experiment_config_v2 import definition, package, write

    path = write(tmp_path / "task.json", package())
    config = load_config_v2(write(tmp_path / "configs/config.json", definition()))
    assert load_task_packages(config) == [load_task_package(path)]
    assert "interaction_overrides" not in config["workload"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown": "direct"},
        {"simple-task": "automatic"},
        {"simple-task": False},
        {"simple-task": {"mode": "direct"}},
    ],
)
def test_invalid_interaction_overrides_fail_before_material_preparation(tmp_path, overrides):
    from ahe_beta.experiment.config import load_config_v2
    from test_experiment_config_v2 import definition, package, write

    write(tmp_path / "task.json", package())
    config = definition()
    config["workload"]["interaction_overrides"] = overrides
    with pytest.raises(ConfigError):
        load_config_v2(write(tmp_path / "configs/config.json", config))
    assert not (tmp_path / "runs").exists()


def test_parent_continuation_cannot_override_inherited_interaction(tmp_path):
    from ahe_beta.experiment.config import load_config_v2
    from test_experiment_config_v2 import definition, write

    config = definition()
    config["harness"] = {"source": "continuation"}
    config["workload"] = {"source": "parent", "interaction_overrides": {"task": "direct"}}
    config["continuation"] = {"archive": "parent.tar.gz", "sha256": "a" * 64}
    with pytest.raises(ConfigError):
        load_config_v2(write(tmp_path / "config.json", config))


def test_task_named_tokenizer_can_have_an_interaction_choice(tmp_path):
    from ahe_beta.experiment.config import load_config_v2, load_task_packages
    from test_experiment_config_v2 import definition, package, write

    task = package()
    task["id"] = "fix-tokenizer"
    write(tmp_path / "task.json", task)
    config = definition()
    config["workload"]["interaction_overrides"] = {"fix-tokenizer": "direct"}
    config = load_config_v2(write(tmp_path / "configs/config.json", config))
    assert load_task_packages(config)[0]["interaction"] == "direct"
