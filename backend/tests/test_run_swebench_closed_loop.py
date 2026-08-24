from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_swebench_closed_loop.py"
    spec = importlib.util.spec_from_file_location("run_swebench_closed_loop_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_instance_selection_rejects_unknown_and_preserves_pool_order() -> None:
    module = _module()
    assert module._select_instance_ids(["one", "two"], "") == ["one", "two"]
    assert module._select_instance_ids(["one", "two"], "two") == ["two"]
    with pytest.raises(SystemExit, match="不在当前题池"):
        module._select_instance_ids(["one", "two"], "three")


def test_all_once_plan_covers_each_instance_and_rotates_personas(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ALL_ONCE", True)
    monkeypatch.setattr(module, "INSTANCE_IDS", ["one", "two", "three"])
    monkeypatch.setattr(module, "PERSONA_IDS", ["a", "b", "c"])

    first = module._session_picks(random.Random(7), round_index=0)
    repeated = module._session_picks(random.Random(7), round_index=0)
    second = module._session_picks(random.Random(7), round_index=1)

    assert first == repeated
    assert sorted(instance for _persona, instance in first) == ["one", "three", "two"]
    assert len({instance for _persona, instance in first}) == 3
    assert [persona for persona, _instance in first] != [
        persona for persona, _instance in second
    ]


def test_scenario_sources_all_preserve_instance_id(tmp_path, monkeypatch) -> None:
    module = _module()
    meta = {
        "instance_id": "repo__issue-1",
        "problem_statement": "problem",
        "repo": "owner/repo",
        "base_commit": "abc",
    }
    seed_root = tmp_path / "seed"
    prepared = seed_root / "workspace" / meta["instance_id"] / "repo"
    (prepared / ".venv/bin").mkdir(parents=True)
    (prepared / ".venv/bin/python").touch()

    monkeypatch.setenv("SWEBENCH_SEED_ROOT", str(seed_root))
    monkeypatch.delenv("SWEBENCH_SEED_IMAGE", raising=False)
    prebuilt = module._to_scenario(meta).workspace
    assert prebuilt is not None and prebuilt.kind == "prebuilt"
    assert prebuilt.params["instance_id"] == meta["instance_id"]

    monkeypatch.delenv("SWEBENCH_SEED_ROOT", raising=False)
    monkeypatch.setenv("SWEBENCH_SEED_IMAGE", "seed:test")
    image = module._to_scenario(meta).workspace
    assert image is not None and image.kind == "docker-seed"
    assert image.params["instance_id"] == meta["instance_id"]

    monkeypatch.delenv("SWEBENCH_SEED_IMAGE", raising=False)
    git = module._to_scenario(meta).workspace
    assert git is not None and git.kind == "git"
    assert git.params["instance_id"] == meta["instance_id"]
