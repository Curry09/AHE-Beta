"""Spec-0074/T4: public batches reference real independent single-run definitions."""

from __future__ import annotations

import re
import shlex
from copy import deepcopy
from pathlib import Path

import pytest

from auto_designer.experiment.batch_config import load_batch_config

ROOT = Path(__file__).resolve().parents[2]
PAIRS = [
    ("README.md", "README.zh-CN.md"),
    ("docs/QUICKSTART.md", "docs/QUICKSTART.zh-CN.md"),
    ("docs/CONFIGURATION.md", "docs/CONFIGURATION.zh-CN.md"),
    ("docs/tutorials/batch-experiment.md", "docs/tutorials/batch-experiment.zh-CN.md"),
]


def _commands(path: str) -> list[str]:
    return [
        line.strip()
        for line in (ROOT / path).read_text().splitlines()
        if line.strip().startswith("uv run ") and "backend/scripts/experiment.py" in line
    ]


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_public_batch_references_complete_offline_members_and_keeps_their_rounds(backend):
    batch = load_batch_config(ROOT / f"examples/batches/n1-n4-{backend}.json")
    assert batch["backend"] == backend
    assert batch["max_parallel_runs"] == 1
    assert [entry["id"] for entry in batch["entries"]] == ["n1", "n4"]
    for entry, users, rounds in zip(batch["entries"], [1, 4], [5, 2], strict=True):
        assert (
            Path(entry["config_path"])
            == ROOT / f"examples/experiments/synthesizer-n{users}-{backend}.json"
        )
        assert entry["config"]["runtime"]["backend"] == backend
        assert entry["config"]["rounds"] == {
            "count": rounds,
            "sessions_per_round": users,
            "max_parallel_users": 1 if users == 1 else 2,
        }
        assert re.fullmatch("[a-f0-9]{64}", entry["input_hash"])
        assert entry["input_identity"]["controller_files"]
        assert len(entry["input_identity"]["tasks"]) == (1 if users == 1 else 2)


def test_two_batch_examples_keep_member_semantics_identical_across_backends():
    members = []
    for backend in ("local", "e2b"):
        batch = load_batch_config(ROOT / f"examples/batches/n1-n4-{backend}.json")
        normalized = []
        for entry in batch["entries"]:
            config = deepcopy(entry["config"])
            del config["runtime"], config["name"]
            normalized.append((entry["id"], config))
        members.append(normalized)
    assert members[0] == members[1]


@pytest.mark.parametrize("english,chinese", PAIRS)
def test_batch_bilingual_cli_commands_are_identical(english, chinese):
    assert _commands(english) == _commands(chinese)


def test_documented_batch_and_child_commands_parse_through_the_unified_cli():
    from auto_designer.experiment.cli import build_parser

    commands = _commands("docs/tutorials/batch-experiment.md")
    assert commands
    parser = build_parser()
    batch_verbs = set()
    for command in commands:
        arguments = shlex.split(command.split("backend/scripts/experiment.py", 1)[1])
        parser.parse_args(arguments)
        if "batch" in arguments:
            batch_verbs.add(arguments[arguments.index("batch") + 1])
            assert "--runs-dir" in arguments
        else:
            # A child run ID lives at its entry-specific root, not the outer root.
            assert arguments[:2] == ["--runs-dir", "$CHILD_RUNS_DIR"]
    assert batch_verbs == {"check", "prepare", "run", "status", "stop", "resume", "collect"}


@pytest.mark.parametrize("path", [path for pair in PAIRS for path in pair])
def test_batch_documentation_local_links_resolve(path):
    document = ROOT / path
    for reference in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", document.read_text()):
        if reference.startswith(("http://", "https://", "mailto:", "#")):
            continue
        relative = reference.split("#", 1)[0]
        if not relative:
            continue
        target = (document.parent / relative).resolve()
        assert target.is_relative_to(ROOT), (path, reference)
        assert target.exists(), (path, reference)
