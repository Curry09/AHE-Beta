"""Spec-0069/T6: public examples describe the same runnable experiment."""

import json
import re
import shlex
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

from ahe_beta.experiment.config import load_config_v2, load_task_package
from ahe_beta.experiment.materials import check_materials

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path", sorted((ROOT / "examples/experiments").glob("*.json")), ids=lambda path: path.name
)
def test_public_example_has_complete_offline_materials(path):
    report = check_materials(path)
    assert report["ok"]
    if path.name.startswith("evolution-feedback-"):
        config = load_config_v2(path)
        assert config["evaluation"] == {"official_grading": False}
        assert config["rounds"] == {"count": 1, "sessions_per_round": 1, "max_parallel_users": 1}
        assert report["persona_ids"] == ["sr-15-swyx"]
        # The preparation script generates an enabled artifact task plus actual key/plan hashes.
        assert config["workload"]["task_packages"][0].endswith("/order-service/task.json")
        return
    study_examples = {
        "u8-mixed-e2b.json": (8, 5),
        "u8-direct-e2b.json": (8, 5),
        "u16-mixed-e2b.json": (16, 8),
        "u32-mixed-e2b.json": (32, 15),
    }
    if path.name in study_examples:
        n_sessions, n_personas = study_examples[path.name]
        config = load_config_v2(path)
        tasks = [load_task_package(value) for value in config["workload"]["task_packages"]]
        assert len(tasks) == len({task["id"] for task in tasks}) == n_sessions
        assert all(task["schema_version"] == 3 for task in tasks)
        assert len(report["persona_ids"]) == n_personas
        assert report["preview"] == {"frozen": False}
        assert config["rounds"] == {
            "count": 6,
            "sessions_per_round": n_sessions,
            "max_parallel_users": 4,
        }
        assert len(report["interaction_plan"]) == 6
        assert all(len(pairs) == n_sessions for pairs in report["interaction_plan"])
        # Exact source bindings, interaction contrasts and capture boundaries have
        # their own study contract in test_evolution32_examples.py.
        return
    n_users = 1 if path.name.startswith("u1-") else 4
    assert len(report["persona_ids"]) == n_users
    assert report["preview"] == {"frozen": False}
    config = load_config_v2(path)
    assert config["rounds"] == {
        "count": 5 if n_users == 1 else 2,
        "sessions_per_round": n_users,
        "max_parallel_users": 1 if n_users == 1 else 2,
    }
    tasks = [load_task_package(value) for value in config["workload"]["task_packages"]]
    assert tasks[0]["source"]["revision"] == "3f397ed44075b01f4ba535750356859195a51b2d"
    assert "not_in_benchmark" not in tasks[0]
    if n_users == 4:
        assert {task["kind"] for task in tasks} == {"swebench", "ordinary"}
        assert tasks[1]["id"] == "order-service" and tasks[1]["not_in_benchmark"]
        expected_pairs = {
            (persona, task["id"]) for persona in report["persona_ids"] for task in tasks
        }
        assert {
            tuple(pair) for picks in report["interaction_plan"] for pair in picks
        } == expected_pairs
    else:
        assert report["persona_ids"] == ["sr-15-swyx"]
        # The U1 example still exercises the original v1 workload fields.
        assert json.loads(path.read_text())["workload"]["task_package"]


@pytest.mark.parametrize("n_users", [1, 4])
def test_two_backends_keep_identical_experiment_semantics(n_users):
    configs = [
        load_config_v2(ROOT / f"examples/experiments/u{n_users}-{backend}.json")
        for backend in ("local", "e2b")
    ]
    normalized = []
    for original in configs:
        config = deepcopy(original)
        del config["runtime"]
        del config["name"]
        normalized.append(config)
    assert normalized[0] == normalized[1]


def test_task_requirements_include_hashes_for_every_pinned_dependency():
    text = (ROOT / "examples/tasks/pvlib-1478/requirements.lock").read_text()
    requirements = re.split(r"(?m)(?=^[A-Za-z0-9][A-Za-z0-9_.-]*==)", text)[1:]
    assert len(requirements) >= 19
    for requirement in requirements:
        assert re.match(r"[A-Za-z0-9_.-]+==[^\s]+", requirement)
        assert re.search(r"--hash=sha256:[a-f0-9]{64}", requirement)
    assert "pytest==8.4.2" in text
    assert "pytest-mock==3.15.1" in text
    assert "-e " not in text
    assert "/home/" not in text
    assert "/tmp/" not in text


def test_public_examples_only_reference_listed_env_variables():
    template = (ROOT / "examples/experiment.env.example").read_text()
    variables = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=", template))
    for path in (ROOT / "examples/experiments").glob("*.json"):
        config = load_config_v2(path)
        for model in config["models"].values():
            assert model["base_url_env"] in variables
            assert model["api_key_env"] in variables
    assert {"E2B_API_KEY", "GITEA_TOKEN"} <= variables


def test_compatibility_and_experiment_extras_are_pinned():
    compatibility = json.loads((ROOT / "release/compatibility.json").read_text())
    for contract in ("observation_transport", "execution_evidence"):
        reader_config = compatibility[contract]
        reader = (
            reader_config.get("reader_release_commit") or reader_config["reader_candidate_commit"]
        )
        assert re.fullmatch(r"[a-f0-9]{40}", reader)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]["experiments"]
    for package in ("e2b", "pyarrow"):
        assert f"{package}=={compatibility['experiment_runtime'][package]}" in extras


@pytest.mark.parametrize(
    "english,chinese",
    [
        ("docs/QUICKSTART.md", "docs/QUICKSTART.zh-CN.md"),
        ("docs/tutorials/u1-experiment.md", "docs/tutorials/u1-experiment.zh-CN.md"),
        ("README.md", "README.zh-CN.md"),
        (
            "docs/tutorials/multi-user-experiment.md",
            "docs/tutorials/multi-user-experiment.zh-CN.md",
        ),
    ],
)
def test_bilingual_cli_commands_match_and_parse(english, chinese):
    from ahe_beta.experiment.cli import build_parser

    def commands(path):
        return [
            line.strip()
            for line in (ROOT / path).read_text().splitlines()
            if line.strip().startswith("uv run ") and "backend/scripts/experiment.py" in line
        ]

    english_commands = commands(english)
    assert english_commands == commands(chinese)
    assert english_commands
    for command in english_commands:
        args = shlex.split(command.split("backend/scripts/experiment.py", 1)[1])
        build_parser().parse_args(args)


def test_order_service_dependency_lock_matches_frozen_controller_lock():
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = {package["name"]: package for package in lock["package"]}
    text = (ROOT / "examples/tasks/order-service/requirements.lock").read_text()
    requirements = re.split(r"(?m)(?=^[A-Za-z0-9][A-Za-z0-9_.-]*==)", text)[1:]
    assert len(requirements) == 5
    for requirement in requirements:
        name, version = re.match(r"([A-Za-z0-9_.-]+)==([^\s]+)", requirement).groups()
        package = packages[name]
        assert package["version"] == version
        artifacts = [package.get("sdist", {}), *package.get("wheels", [])]
        allowed = {artifact["hash"] for artifact in artifacts if artifact.get("hash")}
        hashes = {
            "sha256:" + value for value in re.findall(r"--hash=sha256:([a-f0-9]{64})", requirement)
        }
        assert hashes and hashes <= allowed
    assert "UV_LINK_MODE=copy" in (ROOT / "examples/tasks/order-service/setup.sh").read_text()
    assert (ROOT / "examples/tasks/order-service/source/LICENSE").read_text() == (
        ROOT / "LICENSE"
    ).read_text()


def test_feedback_templates_differ_only_in_backend_and_name():
    configs = []
    for backend in ("local", "e2b"):
        config = load_config_v2(ROOT / f"examples/experiments/evolution-feedback-{backend}.json")
        config.pop("runtime")
        config.pop("name")
        configs.append(config)
    assert configs[0] == configs[1]
