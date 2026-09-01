from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_swebench_seed_workspaces.py"
    spec = importlib.util.spec_from_file_location("swebench_seed_builder_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Table:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict]:
        return self._rows


def test_load_pool_requires_unique_instances_and_matching_difficulty(tmp_path, monkeypatch) -> None:
    module = _module()
    manifest = tmp_path / "pool.json"
    parquet = tmp_path / "verified.parquet"
    parquet.touch()
    manifest.write_text(
        json.dumps(
            {
                "name": "pool",
                "instances": [
                    {"instance_id": "repo__issue-1", "difficulty": "hard", "theme": "api"}
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "instance_id": "repo__issue-1",
            "repo": "owner/repo",
            "base_commit": "abc",
            "problem_statement": "problem",
            "difficulty": "hard",
        }
    ]
    monkeypatch.setattr(module.pq, "read_table", lambda *_args, **_kwargs: _Table(rows))

    document, enriched = module._load_pool(manifest, parquet)
    assert document["name"] == "pool"
    assert enriched[0]["theme"] == "api"
    assert enriched[0]["base_commit"] == "abc"

    manifest.write_text(
        json.dumps(
            {
                "instances": [
                    {"instance_id": "repo__issue-1", "difficulty": "medium"}
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="difficulty mismatch"):
        module._load_pool(manifest, parquet)


def test_state_write_replaces_document_without_leaving_temporary_file(tmp_path) -> None:
    module = _module()
    path = tmp_path / "build-state.json"
    module._write_state(path, {"instances": {"one": {"stage": "source"}}})
    module._write_state(path, {"instances": {"two": {"stage": "dependencies"}}})

    assert module._read_state(path) == {
        "instances": {"two": {"stage": "dependencies"}}
    }
    assert not path.with_suffix(".tmp").exists()


def test_cli_requires_explicit_parquet_path(monkeypatch) -> None:
    module = _module()
    monkeypatch.delenv("SWEBENCH_PARQUET", raising=False)
    monkeypatch.setattr(sys, "argv", ["builder"])
    with pytest.raises(SystemExit, match="2"):
        module._args()


def test_setup_uses_the_running_python_interpreter() -> None:
    module = _module()

    commands = module._setup_commands({"repo": "owner/repo"})

    assert commands[0] == f"{module.shlex.quote(sys.executable)} -m venv .venv"
