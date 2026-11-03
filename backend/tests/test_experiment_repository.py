"""Spec-0071/T6: prevent public-directory and frozen-archive regressions."""

import hashlib
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


def inventory(root, content=b"historical source\n"):
    target = root / "research/archives/old/README.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    row = {
        "original_path": "evaluation/old/README.md",
        "disposition": "archived",
        "destination": target.relative_to(root).as_posix(),
        "reason": "Frozen historical research",
        "source_commit": "a" * 40,
        "source_sha256": hashlib.sha256(content).hexdigest(),
    }
    (root / "research/inventory.json").write_text(json.dumps({"files": [row]}))
    return target


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


def test_archive_content_cannot_be_silently_rewritten(tmp_path):
    archived = inventory(tmp_path)
    assert checker.inventory_errors(tmp_path) == []
    archived.write_text("updated result without the original evidence\n")
    assert any("Frozen archive content changed" in e for e in checker.inventory_errors(tmp_path))


def test_declared_english_translation_retains_source_and_locks_translated_bytes(tmp_path):
    archived = inventory(tmp_path)
    manifest_path = tmp_path / "research/inventory.json"
    manifest = json.loads(manifest_path.read_text())
    row = manifest["files"][0]
    original_sha = row["source_sha256"]
    archived.write_text("English translation of the original research notes\n")
    row["translation"] = {"language": "en", "source_sha256": original_sha}
    row["destination_sha256"] = hashlib.sha256(archived.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    assert checker.inventory_errors(tmp_path) == []
    assert row["source_sha256"] == original_sha
    archived.write_text("Unrecorded changes to the English translation\n")
    assert any("Frozen archive content changed" in e for e in checker.inventory_errors(tmp_path))


@pytest.mark.parametrize("invalid", [None, "0" * 64, "not-a-digest"])
def test_archive_translation_requires_valid_destination_digest(tmp_path, invalid):
    inventory(tmp_path)
    path = tmp_path / "research/inventory.json"
    manifest = json.loads(path.read_text())
    row = manifest["files"][0]
    row["translation"] = {"language": "en", "source_sha256": row["source_sha256"]}
    row["destination_sha256"] = invalid
    path.write_text(json.dumps(manifest))
    # An arbitrary digest is rejected either by provenance or by the byte check.
    assert checker.inventory_errors(tmp_path)


def test_archive_translation_cannot_reassign_the_original_source(tmp_path):
    inventory(tmp_path)
    path = tmp_path / "research/inventory.json"
    manifest = json.loads(path.read_text())
    row = manifest["files"][0]
    row["translation"] = {"language": "en", "source_sha256": "0" * 64}
    row["destination_sha256"] = row["source_sha256"]
    path.write_text(json.dumps(manifest))
    assert any(
        "Invalid archive translation provenance" in e for e in checker.inventory_errors(tmp_path)
    )


def test_historical_readme_also_requires_provenance(tmp_path):
    inventory(tmp_path)
    unlisted = tmp_path / "research/archives/another/README.md"
    unlisted.parent.mkdir()
    unlisted.write_text("Unrecorded historical result\n")
    assert any("Archive missing provenance" in e for e in checker.inventory_errors(tmp_path))


def test_moved_source_cannot_remain_as_a_second_entry(tmp_path):
    inventory(tmp_path)
    original = tmp_path / "evaluation/old/README.md"
    original.parent.mkdir(parents=True)
    original.write_text("old duplicate")
    assert any("Obsolete duplicate remains" in e for e in checker.inventory_errors(tmp_path))


def test_archive_destination_cannot_escape_via_symlink(tmp_path):
    archived = inventory(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_bytes(archived.read_bytes())
    archived.unlink()
    archived.symlink_to(outside)
    try:
        assert any("unsafe destination" in e for e in checker.inventory_errors(tmp_path))
    finally:
        outside.unlink()


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
    inventory(tmp_path)
    path = tmp_path / "examples/experiments/unexpected-legacy.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1}))
    result = checker.check_repository(tmp_path)
    assert not result["ok"]
    assert any("examples/experiments/unexpected-legacy.json:" in e for e in result["errors"])


def test_new_batch_json_cannot_bypass_public_contract_validation(tmp_path):
    # Spec-0074/T3: every public list is validated, not only the maintained filenames.
    inventory(tmp_path)
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
