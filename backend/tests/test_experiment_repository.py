"""Spec-0071/T6: prevent public-directory and retired-entry regressions."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "experiment_repository_check", ROOT / "backend/scripts/check_experiment_repository.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_current_repository_has_only_supported_public_materials():
    result = checker.check_repository(ROOT)
    assert result["ok"], result["errors"]
    assert set(result["examples"]) == {
        f"examples/experiments/{name}-{backend}.json"
        for name in ("u1", "u4", "evolution-feedback")
        for backend in ("local", "e2b")
    } | {
        f"examples/experiments/{name}-e2b.json"
        for name in ("u8-mixed", "u8-direct", "u16-mixed", "u32-mixed")
    }
    assert set(result["batches"]) == {
        "examples/batches/u1-u4-local.json",
        "examples/batches/u1-u4-e2b.json",
        "examples/batches/evolution-four-e2b.json",
    }


def test_unpublished_task_subcommand_is_rejected(monkeypatch):
    # Spec-0076/T2: adapters cannot quietly turn into another experiment launcher.
    from ahe_beta.experiment import cli

    build_parser = cli.build_parser

    def parser_with_extra_task():
        parser = build_parser()
        commands = next(
            action
            for action in parser._actions
            if isinstance(action, checker.argparse._SubParsersAction)
        )
        tasks = next(
            action
            for action in commands.choices["task"]._actions
            if isinstance(action, checker.argparse._SubParsersAction)
        )
        tasks.add_parser("legacy-run")
        return parser

    monkeypatch.setattr(cli, "build_parser", parser_with_extra_task)
    result = checker.check_repository(ROOT)
    assert not result["ok"]
    assert "Unexpected public task commands" in result["errors"]


@pytest.mark.parametrize(
    "code",
    [
        "import run",
        "from ahe_beta.experiment.controllers import ordinary",
        "import ahe_beta.experiment.controllers.swebench",
        "from research.archives import old",
        "import importlib\nimportlib.import_module('run')",
    ],
)
def test_live_code_cannot_depend_on_retired_or_archived_implementations(tmp_path, code):
    path = tmp_path / "tools/dev/replay/test.py"
    path.parent.mkdir(parents=True)
    path.write_text(code)
    assert any("import" in e for e in checker.maintained_import_errors(tmp_path))


def test_personal_path_is_rejected_but_guard_policy_is_allowed(tmp_path):
    path = tmp_path / "backend/scripts/probe.py"
    path.parent.mkdir(parents=True)
    path.write_text("policy = '/home/wydlinux/'\n")
    assert checker.maintained_import_errors(tmp_path) == []
    path.write_text("credential_file = '/home/wydlinux/private.env'\n")
    assert any("Personal source path" in e for e in checker.maintained_import_errors(tmp_path))


def test_new_public_json_is_validated_without_an_allowlist(tmp_path):
    path = tmp_path / "examples/experiments/unexpected-legacy.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1}))
    result = checker.check_repository(tmp_path)
    assert not result["ok"]
    assert any("examples/experiments/unexpected-legacy.json:" in e for e in result["errors"])


def test_new_batch_json_cannot_bypass_public_contract_validation(tmp_path):
    # Spec-0074/T3: every public list is validated, not only the maintained filenames.
    path = tmp_path / "examples/batches/extra.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "extra",
                "entries": [{"id": "u1", "config": "missing.json"}],
                "executor": "old-launcher",
            }
        )
    )
    result = checker.check_repository(tmp_path)
    assert not result["ok"]
    assert any("examples/batches/extra.json:" in e for e in result["errors"])
