"""Spec-0069/T6: public examples describe the same runnable experiment."""

import json
import re
import shlex
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

from auto_designer.experiment.config import load_config_v2, load_task_package
from auto_designer.experiment.materials import check_materials

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_public_example_has_complete_offline_materials(backend):
    path = ROOT / f"examples/experiments/synthesizer-n1-{backend}.json"
    report = check_materials(path)
    assert report["ok"]
    assert report["persona_ids"] == ["sr-15-swyx"]
    config = load_config_v2(path)
    assert config["rounds"] == {"count": 5, "sessions_per_round": 1, "max_parallel_users": 1}
    task = load_task_package(config["workload"]["task_package"])
    assert task["source"]["revision"] == "3f397ed44075b01f4ba535750356859195a51b2d"
    assert "not_in_benchmark" not in task


def test_two_backends_keep_identical_experiment_semantics():
    configs = [
        load_config_v2(ROOT / f"examples/experiments/synthesizer-n1-{backend}.json")
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
    for backend in ("local", "e2b"):
        config = load_config_v2(ROOT / f"examples/experiments/synthesizer-n1-{backend}.json")
        for model in config["models"].values():
            assert model["base_url_env"] in variables
            assert model["api_key_env"] in variables
    assert {"E2B_API_KEY", "GITEA_TOKEN"} <= variables


def test_compatibility_and_experiment_extras_are_pinned():
    compatibility = json.loads((ROOT / "release/compatibility.json").read_text())
    transport = compatibility["observation_transport"]
    reader = transport.get("reader_release_commit") or transport["reader_candidate_commit"]
    assert re.fullmatch(r"[a-f0-9]{40}", reader)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]["experiments"]
    assert "e2b==2.51.0" in extras
    assert "pyarrow==21.0.0" in extras


@pytest.mark.parametrize(
    "english,chinese",
    [
        ("docs/QUICKSTART.md", "docs/QUICKSTART.zh-CN.md"),
        ("docs/tutorials/n1-experiment.md", "docs/tutorials/n1-experiment.zh-CN.md"),
        ("README.md", "README.zh-CN.md"),
    ],
)
def test_bilingual_cli_commands_match_and_parse(english, chinese):
    from auto_designer.experiment.cli import build_parser

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
