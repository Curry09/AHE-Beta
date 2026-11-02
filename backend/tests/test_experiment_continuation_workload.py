"""Spec-0079/T4: inherited content identity produces fresh local session bindings."""

import copy
import json

import pytest

from ahe_beta.experiment import materials, workload
from ahe_beta.experiment.config import ConfigError
from ahe_beta.loop.recovery import operation_key
from test_experiment_config_v2 import write


def _catalog():
    tasks = []
    for task_id, interaction in [("code-task", "direct"), ("review-task", "simulated_user")]:
        task = {
            "id": task_id,
            "kind": "ordinary",
            "interaction": interaction,
            "package": {"id": task_id, "kind": "ordinary", "interaction": interaction},
            "source_snapshot": {"revision": None, "files": {}},
            "content_hashes": {},
            "materials": {"package": task_id + ":package", "source_archive": task_id + ":source"},
        }
        task["digest"] = workload.task_digest(task)
        tasks.append(task)
    return {"contract_version": 1, "tasks": tasks}


def _pairs(catalog):
    return [
        {
            "round_no": 5,
            "slot": index,
            "persona_id": persona,
            "task_id": task["id"],
            "task_digest": task["digest"],
            "interaction": task["interaction"],
        }
        for index, (persona, task) in enumerate(
            zip(["persona-b", "persona-a"], catalog["tasks"], strict=True)
        )
    ]


def _config(count=3):
    return {"workload": {"source": "parent"}, "rounds": {"count": count, "sessions_per_round": 2}}


def test_inherited_plan_repeats_exact_parent_pairs_with_new_round_and_session_identity():
    catalog = _catalog()
    parent_pairs = _pairs(catalog)
    original = copy.deepcopy(parent_pairs)
    plan = workload.compile_session_plan(_config(), catalog, "child-catalog", parent_pairs)
    assert plan["catalog_hash"] == "child-catalog"
    assert len(plan["rounds"]) == 3
    for local_round, picks in enumerate(plan["rounds"], 1):
        assert [pick["round_no"] for pick in picks] == [local_round] * 2
        assert [pick["slot"] for pick in picks] == [0, 1]
        assert [
            {key: value for key, value in pick.items() if key not in {"round_no", "slot"}}
            for pick in picks
        ] == [
            {key: value for key, value in pair.items() if key not in {"round_no", "slot"}}
            for pair in original
        ]
    assert parent_pairs == original
    parent_keys = {operation_key("parent-run", "users", pick) for pick in parent_pairs}
    child_keys = {
        operation_key("child-run", "users", pick) for picks in plan["rounds"] for pick in picks
    }
    assert len(child_keys) == 6
    assert parent_keys.isdisjoint(child_keys)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda pairs: pairs.pop(),
        lambda pairs: pairs[0].update(task_id="unknown"),
        lambda pairs: pairs[0].update(task_digest="changed"),
        lambda pairs: pairs[0].update(interaction="simulated_user"),
    ],
)
def test_inherited_plan_rejects_changed_content_identity(mutation):
    catalog = _catalog()
    pairs = _pairs(catalog)
    mutation(pairs)
    with pytest.raises(ConfigError):
        workload.compile_session_plan(_config(), catalog, "catalog", pairs)


def test_inherited_plan_requires_frozen_pairs():
    with pytest.raises(ConfigError, match="frozen parent pairs"):
        workload.compile_session_plan(_config(), _catalog(), "catalog")


def _frozen_plan(tmp_path):
    catalog = _catalog()
    registry = {}

    def material(key, relative, document):
        path = write(tmp_path / relative, document)
        registry[key] = {"path": relative, "sha256": materials.sha256_file(path)}
        return registry[key]["sha256"]

    for task in catalog["tasks"]:
        material(
            task["materials"]["package"], f"materials/{task['id']}-package.json", task["package"]
        )
        material(task["materials"]["source_archive"], f"materials/{task['id']}-source.json", {})
    catalog_hash = material("task_catalog", "materials/catalog.json", catalog)
    pairs = _pairs(catalog)
    material("continuation_input", "materials/continuation/input.json", {"pairs": pairs})
    plan = workload.compile_session_plan(_config(), catalog, catalog_hash, pairs)
    plan_hash = material("session_plan", "materials/session-plan.json", plan)
    return {
        "workload_contract_version": 1,
        "config": _config(),
        "catalog_hash": catalog_hash,
        "plan_hash": plan_hash,
        "materials": registry,
    }, plan


def test_read_session_plan_uses_frozen_parent_pairs_not_derived_parent_plan_hash(tmp_path):
    manifest, expected = _frozen_plan(tmp_path)
    assert workload.read_session_plan(tmp_path, manifest) == expected
    path = tmp_path / manifest["materials"]["session_plan"]["path"]
    tampered = json.loads(path.read_text())
    tampered["rounds"][0][0]["round_no"] = 5
    write(path, tampered)
    manifest["plan_hash"] = materials.sha256_file(path)
    with pytest.raises(ConfigError, match="logical task/persona bindings"):
        workload.read_session_plan(tmp_path, manifest)


def test_ordinary_compiler_retains_global_rotation_and_explicit_pairs():
    catalog = _catalog()
    config = {
        "workload": {"persona_ids": ["a", "b", "c"]},
        "rounds": {"count": 2, "sessions_per_round": 2},
    }
    plan = workload.compile_session_plan(config, catalog, "catalog")
    assert [[pick["persona_id"] for pick in picks] for picks in plan["rounds"]] == [
        ["a", "b"],
        ["c", "a"],
    ]
    config["workload"]["interaction_plan"] = [[["b", "review-task"], ["a", "code-task"]]] * 2
    explicit = workload.compile_session_plan(config, catalog, "catalog")
    assert all([pick["persona_id"] for pick in picks] == ["b", "a"] for picks in explicit["rounds"])


# Spec-0080/T3: repeated personas and complete pairs survive inherited compilation.
def test_inherited_plan_preserves_repeated_pairs_and_distinct_slot_keys():
    catalog = _catalog()
    pairs = _pairs(catalog)
    pairs[1] = {**pairs[0], "slot": 1}
    plan = workload.compile_session_plan(_config(), catalog, "catalog", pairs)
    keys = set()
    for bindings in plan["rounds"]:
        assert [b["persona_id"] for b in bindings] == ["persona-b", "persona-b"]
        assert [b["task_id"] for b in bindings] == ["code-task", "code-task"]
        keys.update(operation_key("child-run", "users", b) for b in bindings)
    assert len(keys) == 6


# Spec-0080/T1: golden identities captured from the pre-change compiler (684dd9b).
@pytest.mark.parametrize(
    "count,expected_config,expected_plan",
    [
        (
            1,
            "bdfaebf09a3d8e7481bae67ecca0cbd7f87e294c0b27a69bab207c5f0f28976a",
            "49ca2be1c6e41360161a9efddb1c87b31f49cf8214be824cf3956d9112cea3de",
        ),
        (
            4,
            "37d50f464dd4e659b3698680c85e30feb858bac018eb128ca6af3e5d30744fcc",
            "0147cf10f214d4251f5b8626bd84ec96da8dc03b8bb1b821ddca9a61c5cd4e2f",
        ),
    ],
)
def test_existing_n1_n4_plan_hashes_and_session_keys_unchanged(
    count, expected_config, expected_plan
):
    from ahe_beta.experiment.config import config_hash

    config = {
        "workload": {"persona_ids": [f"p-{i}" for i in range(count)]},
        "rounds": {"count": 2, "sessions_per_round": count},
    }
    plan = workload.compile_session_plan(config, _catalog(), "unchanged-catalog")
    assert config_hash(data=config) == expected_config
    assert config_hash(data=plan) == expected_plan
    assert operation_key("run", "users", plan["rounds"][0][0]) == (
        "op-673c0f5328a01d1cce1f6fd967c9adc3"
    )
