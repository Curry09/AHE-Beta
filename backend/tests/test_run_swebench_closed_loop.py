from __future__ import annotations

import importlib.util
import json
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
    assert [persona for persona, _instance in first] != [persona for persona, _instance in second]


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
    assert image.params["network"] == "bridge"

    monkeypatch.delenv("SWEBENCH_SEED_IMAGE", raising=False)
    git = module._to_scenario(meta).workspace
    assert git is not None and git.kind == "git"
    assert git.params["instance_id"] == meta["instance_id"]


def test_frozen_plan_loads_roster_and_rejects_drift(tmp_path) -> None:
    module = _module()
    roster = tmp_path / "roster.json"
    roster.write_text('{"personas":[{"id":"a"},{"id":"b"}]}', encoding="utf-8")
    persona_ids = module._load_persona_ids(path=roster, fallback=["fallback"])
    assert persona_ids == ["a", "b"]

    plan = tmp_path / "plan.json"
    plan.write_text(
        '[[["a","one"],["b","two"]],[["b","one"],["a","two"]]]',
        encoding="utf-8",
    )
    loaded = module._load_interaction_plan(
        path=plan,
        total_rounds=2,
        persona_ids=persona_ids,
        instance_ids=["one", "two"],
    )
    assert loaded == [
        [("a", "one"), ("b", "two")],
        [("b", "one"), ("a", "two")],
    ]

    plan.write_text('[[["a","outside"],["b","two"]]]', encoding="utf-8")
    with pytest.raises(SystemExit, match="题池外"):
        module._load_interaction_plan(
            path=plan,
            total_rounds=1,
            persona_ids=persona_ids,
            instance_ids=["one", "two"],
        )


def test_shared_recovery_loader_reuses_identity_and_rejects_missing_state(
    tmp_path: Path, monkeypatch
) -> None:
    module = _module()
    values = {
        "AUTO_DESIGNER_EXPERIMENT_ID": "exp",
        "AUTO_DESIGNER_RUN_ID": "run",
        "AUTO_DESIGNER_CONFIG_HASH": "config",
        "AUTO_DESIGNER_CONTROLLER_SHA": "controller",
        "AUTO_DESIGNER_PLAN_HASH": "plan",
        "AUTO_DESIGNER_RECOVERY_ROOT": str(tmp_path / "checkpoints"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    fresh = module.run_mod.load_recovery_store(mode="fresh")
    assert fresh is not None
    resumed = module.run_mod.load_recovery_store(mode="resume")
    assert resumed is not None and resumed.snapshot()["identity"]["run_id"] == "run"

    snapshot = tmp_path / "checkpoints" / "recovery.json"
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    document["identity"]["plan_hash"] = "drift"
    snapshot.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(Exception, match="identity changed"):
        module.run_mod.load_recovery_store(mode="resume")


def test_replay_resume_starts_from_frozen_or_current_round() -> None:
    module = _module()

    class Recovery:
        def __init__(self, round_no):
            self.round_no = round_no

        def snapshot(self):
            return {"round": self.round_no}

    assert module._start_round(run_mode="replay", replay_start=3, recovery=None) == 3
    assert module._start_round(run_mode="resume", replay_start=3, recovery=Recovery(3)) == 3
    assert module._start_round(run_mode="resume", replay_start=3, recovery=Recovery(4)) == 4
    assert module._start_round(run_mode="resume", replay_start=None, recovery=Recovery(3)) == 1


def test_replay_resume_reads_frozen_start_when_launcher_omits_it(tmp_path) -> None:
    module = _module()
    manifest = tmp_path / "mixed.json"
    manifest.write_text('{"replay":{"start_round":3}}', encoding="utf-8")
    assert module._replay_start(run_mode="resume", explicit="", manifest_path=str(manifest)) == 3
    assert module._replay_start(run_mode="resume", explicit="3", manifest_path=str(manifest)) == 3
    with pytest.raises(RuntimeError, match="conflicts"):
        module._replay_start(run_mode="resume", explicit="1", manifest_path=str(manifest))
