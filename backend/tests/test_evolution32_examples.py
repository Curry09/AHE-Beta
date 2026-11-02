"""Spec-0081/T5: public study inputs and comparison conditions, entirely offline."""

import hashlib
import json
import re
import shlex
from collections import Counter
from copy import deepcopy
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pytest

from ahe_beta.experiment.config import (
    config_hash,
    load_config_v2,
    load_task_package,
    load_task_packages,
    validate_schema,
)
from ahe_beta.experiment.materials import check_materials
from ahe_beta.experiment.workload import execution_declaration
from ahe_beta.loop.recovery import operation_key

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "examples/tasks/evolution32"
# The original study's ordered task/card bindings, not a Cartesian persona assignment.
# None means direct in the source study; its terminal feedback used sr-15-swyx.
ORIGINAL = (
    ("O03", "pvlib__pvlib-python-1478", "sr-15-swyx"),
    ("O09", "production-planning", None),
    ("O14", "010-pivot-product-revenue", "sr-20-kellan"),
    ("M03", "superset-goal-discovery", "sr-27-kenton-varda"),
    ("O01", "pylint-dev__astroid-2240", "sr-15-swyx"),
    ("kv-live-surgery", "kv-live-surgery", "sr-19-xe-iaso"),
    ("tinydb", "tinydb", None),
    ("M01", "sqlfluff-subagent-review", "sr-02-ronacher"),
    ("O05", "marshmallow-code__marshmallow-1229", "sr-02-ronacher"),
    ("O06", "sqlfluff__sqlfluff-2336", None),
    ("vf2-speedup-networkx", "vf2-speedup-networkx", "sr-27-kenton-varda"),
    ("pretrain-shard-corruption", "pretrain-shard-corruption", "gh-ml-03-5df6e44f943b"),
    ("091-add-receipts-bookkeeping", "091-add-receipts-bookkeeping", "sr-30-kent-beck"),
    ("flask-restful", "flask-restful", None),
    ("M05", "permission-schema-migration", "sr-01-willison"),
    ("M09", "plan-blocked-dependency", "sr-27-kenton-varda"),
    ("O02", "pydicom__pydicom-1334", "gh-sci-03-3a200275ad87"),
    ("O04", "pyvista__pyvista-3750", "gh-viz-03-4fd081054e66"),
    ("astroid-1030", "astroid-1030", "sr-08-nat-bennett"),
    ("sqlfluff-3608", "sqlfluff-3608", "gh-de-03-82e3b11d3c73"),
    ("marshmallow-2123", "marshmallow-2123", "sr-02-ronacher"),
    ("payments-pipeline-fix", "payments-pipeline-fix", None),
    ("wal-recovery-ordering", "wal-recovery-ordering", "gh-de-03-82e3b11d3c73"),
    ("vba-userform-port", "vba-userform-port", "sr-19-xe-iaso"),
    ("react-lead-form", "react-lead-form", "sr-16-theo-t3"),
    ("080-convert-novel-epub", "080-convert-novel-epub", "sr-20-kellan"),
    ("cookiecutter", "cookiecutter", None),
    ("tqdm", "tqdm", None),
    ("M02", "superset-ci-loop", "sr-26-ghuntley"),
    ("M04", "dbt-direction-negotiation", "sr-08-nat-bennett"),
    ("M07", "memory-project-constraints", "gh-db-01-db528f7b6a83"),
    ("M10", "review-verifier-catches-regression", "sr-30-kent-beck"),
)
GROUPS = (
    ("u8-mixed-e2b", 8, 6, 2, 4),
    ("u8-direct-e2b", 8, 0, 8, 4),
    ("u16-mixed-e2b", 16, 12, 4, 8),
    ("u32-mixed-e2b", 32, 25, 7, 16),
)


def document(path):
    return json.loads(path.read_text())


def package(key):
    path = TASKS / key / "task.json"
    assert path.is_file(), f"Public task definition missing: {path.relative_to(ROOT)}"
    return load_task_package(path)


def test_catalog_contains_exactly_the_original_thirty_two_inputs():
    manifest = document(TASKS / "manifest.json")
    assert manifest["task_order"] == [key for key, _, _ in ORIGINAL]
    assert {p.parent.name for p in TASKS.glob("*/task.json")} == set(manifest["task_order"])
    rows = {row["key"]: row for row in manifest["tasks"]}
    assert len(rows) == 32
    for key, task_id, persona in ORIGINAL:
        row = rows[key]
        assert row["id"] == task_id
        assert row["persona_id"] == persona
        assert row["default_interaction"] == ("simulated_user" if persona else "direct")
        instruction = (TASKS / row["instruction_file"]).resolve()
        assert instruction.is_relative_to(TASKS.resolve()) and instruction.is_file()
        assert hashlib.sha256(instruction.read_bytes()).hexdigest() == row["instruction_sha256"]


@pytest.mark.parametrize("key,task_id,persona", ORIGINAL, ids=[row[0] for row in ORIGINAL])
def test_each_task_declares_pinned_public_image_and_release_inputs(key, task_id, persona):
    task = package(key)
    assert task["schema_version"] == 3 and task["id"] == task_id
    assert task["interaction"] == ("simulated_user" if persona else "direct")
    env = task["environment"]
    assert env["kind"] == "container"
    manifest = document(TASKS / "manifest.json")
    assert env["image"] == manifest["publication"]["images"][key]["image"]
    images = [
        env["image"],
        *[s["image"] for s in env.get("services", []) if s["placement"] == "companion"],
    ]
    assert all(re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image) for image in images)
    assert env["inputs"]
    for item in env["inputs"]:
        material = item["material"]
        # Public examples cannot accidentally depend on an operator's local archive.
        assert "url" in material and "path" not in material
        url = urlsplit(material["url"])
        assert url.scheme == "https" and url.hostname
        assert not (url.username or url.password or url.query or url.fragment)
        assert "/releases/" in url.path and "/latest/" not in url.path
        assert re.fullmatch(r"[0-9a-f]{64}", material["sha256"])
        for name, sha in material.get("files", {}).items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            assert re.fullmatch(r"[0-9a-f]{64}", sha)


def test_shared_release_url_never_changes_hash_between_tasks():
    urls = {}
    for key, _, _ in ORIGINAL:
        for item in package(key)["environment"]["inputs"]:
            material = item["material"]
            assert "url" in material
            assert urls.setdefault(material["url"], material["sha256"]) == material["sha256"]
    assert document(TASKS / "manifest.json")["publication"]["release"] is not None


@pytest.mark.parametrize("name,n,simulated,direct,triagers", GROUPS)
def test_six_round_examples_keep_original_pairing_and_declared_conditions(
    name, n, simulated, direct, triagers
):
    path = ROOT / "examples/experiments" / f"{name}.json"
    report = check_materials(path)
    assert report["ok"] and report["preview"] == {"frozen": False}
    config = load_config_v2(path)
    tasks = load_task_packages(config)
    assert [task["id"] for task in tasks] == [task_id for _, task_id, _ in ORIGINAL[:n]]
    assert Counter(task["interaction"] for task in tasks) == Counter(
        {"simulated_user": simulated, "direct": direct}
    )
    assert config["rounds"] == {"count": 6, "sessions_per_round": n, "max_parallel_users": 4}
    assert config["roles"] == {
        "triager": triagers,
        "architect": 1,
        "divergent": 1,
        "owner_mode": "mechanical",
        "developer": 4,
    }
    assert config["runtime"]["backend"] == "e2b"
    assert config["runtime"]["gitea"]["provider"] == "gitea.com"
    assert {k: config["runtime"]["e2b"][k] for k in ("cpu_count", "memory_mb")} == {
        "cpu_count": 4,
        "memory_mb": 8192,
    }
    assert config["harness"] == {"source": "builtin"}
    assert config["policies"]["architect_grouping"] is False
    assert config["evaluation"] == {"official_grading": False}
    pairs = [[persona or "sr-15-swyx", task_id] for _, task_id, persona in ORIGINAL[:n]]
    expected = [pairs[i:] + pairs[:i] for i in range(6)]
    assert report["interaction_plan"] == expected
    assert config["workload"]["persona_ids"] == list(dict.fromkeys(p[0] for p in pairs))
    assert (
        config["models"]["user"]["model"] == config["models"]["harness"]["model"] == "glm-5.3-flash"
    )
    assert config["models"]["demand"]["model"] == config["models"]["delivery"]["model"] == "glm-5.3"
    assert all("limits" not in model for model in config["models"].values())
    assert "harness" not in config["runtime"]  # No new run-level request/model budget.


def test_u8_comparison_changes_only_interaction_and_derived_identity():
    paths = [ROOT / f"examples/experiments/u8-{mode}-e2b.json" for mode in ("mixed", "direct")]
    raw = [document(path) for path in paths]
    overrides = raw[1]["workload"]["interaction_overrides"]
    assert overrides == {task_id: "direct" for _, task_id, persona in ORIGINAL[:8] if persona}
    left, right = deepcopy(raw[0]), deepcopy(raw[1])
    for config in (left, right):
        config.pop("name")
        config["runtime"]["gitea"].pop("repository_prefix")
        config["workload"].pop("interaction_overrides", None)
    assert left == right
    before = {p: p.read_bytes() for p in TASKS.glob("*/task.json")}
    selected = [load_task_packages(load_config_v2(path)) for path in paths]
    assert sum(t["interaction"] == "direct" for t in selected[0]) == 2
    assert all(t["interaction"] == "direct" for t in selected[1])
    assert before == {p: p.read_bytes() for p in before}


def test_reused_personas_still_have_independent_round_and_slot_identities():
    report = check_materials(ROOT / "examples/experiments/u32-mixed-e2b.json")
    tasks = {t["id"]: t for t in report["task_packages"]}
    ids, bindings = [], []
    # Only identity allocation is under test: content/source validation is separate above.
    for round_no, pairs in enumerate(report["interaction_plan"], 1):
        for slot, (persona, task_id) in enumerate(pairs):
            binding = {
                "round_no": round_no,
                "slot": slot,
                "persona_id": persona,
                "task_id": task_id,
                "task_digest": config_hash(data=tasks[task_id]),
                "interaction": tasks[task_id]["interaction"],
            }
            bindings.append(binding)
            ids.append(operation_key("study-preview", "users", binding))
    assert len(ids) == len(set(ids)) == 192
    assert len({b["persona_id"] for b in bindings}) == 15
    same = deepcopy(bindings[0])
    other_slot = {**same, "slot": same["slot"] + 1}
    other_round = {**same, "round_no": same["round_no"] + 1}
    assert (
        len({operation_key("study-preview", "users", b) for b in (same, other_slot, other_round)})
        == 3
    )


@pytest.mark.parametrize("key", ["M01", "M03"])
def test_prepared_source_is_not_misrepresented_as_an_upstream_checkout(key):
    task = package(key)
    assert task["kind"] == "benchmark" and "source" not in task
    assert task["environment"]["patch"] == "git"
    row = next(t for t in document(TASKS / "manifest.json")["tasks"] if t["key"] == key)
    baseline = row["git_baseline"]
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["revision"])
    assert baseline["revision"] in task["environment"]["initialize"]["argv"]
    assert any(
        i["material"]["sha256"] == baseline["bundle_sha256"] and i["material"]["format"] == "file"
        for i in task["environment"]["inputs"]
    )


def test_kv_capture_code_and_raw_measurements_stay_outside_actor_inputs():
    task = package("kv-live-surgery")
    env = task["environment"]
    services = {service["id"]: service for service in env["services"]}
    assert services["capture"]["placement"] == services["loadgen"]["placement"] == "companion"
    capture = [row for row in env["inputs"] if row["id"] == "capture-code"]
    assert len(capture) == 1 and capture[0]["placement"] == "capture"
    for row in env["inputs"]:
        if row.get("placement", "task") != "task":
            continue
        names = {PurePosixPath(name).name for name in row["material"].get("files", {})}
        assert not names & {"finalize.py", "kv_server.c"}
        assert not any("loadgen-rs" in name for name in row["material"].get("files", {}))
    assert services["loadgen"]["argv"] == ["/app/loadgen"]
    assert services["loadgen"]["environment"]["MAX_WAIT"] == "28800"
    exports = {e["handle"]: e for service in services.values() for e in service.get("exports", [])}
    assert {
        handle for handle, e in exports.items() if e.get("visibility", "management") == "task"
    } == {"kv-summary"}
    assert {
        e["handle"] for e in task["artifacts"]["exports"] if e["source"] == "managed_service"
    } == {"kv-summary"}


def test_m02_keeps_the_operator_confirmed_incomplete_original_input():
    task = package("M02")
    assert "source" not in task
    assert task["environment"]["patch"] == "not_applicable"
    inputs = {row["id"]: row for row in task["environment"]["inputs"]}
    assert set(inputs) == {"recipes", "original-public"}
    assert set(inputs["original-public"]["material"]["files"]) == {
        "public/TASK.md",
        "public/ci.py",
    }
    row = next(t for t in document(TASKS / "manifest.json")["tasks"] if t["key"] == "M02")
    assert row["availability"]["operator_decision"]["confirmed"] is True
    # No replacement Superset candidate, answer or fabricated regression suite
    # may turn this declared robustness case into a different source task.
    assert set(row["availability"]["verified_original_members"]) == {
        "M02/public/TASK.md",
        "M02/public/ci.py",
    }


def test_original_absence_of_total_budget_is_not_replaced_by_wrapper_1800():
    for key, _, _ in ORIGINAL:
        task = package(key)
        assert "execution" not in task
        declaration = execution_declaration(task, fallback_seconds=None)
        assert declaration["task_budget_seconds"] is None
        assert declaration["budget_source"] == "undeclared"


def test_four_group_batch_reuses_complete_run_configs():
    path = ROOT / "examples/batches/evolution-four-e2b.json"
    batch = document(path)
    validate_schema(document=batch, schema_name="batch-v1.json")
    assert batch["max_parallel_runs"] == 1
    assert [(path.parent / row["config"]).resolve() for row in batch["entries"]] == [
        ROOT / f"examples/experiments/{name}.json" for name, *_ in GROUPS
    ]


def test_bilingual_study_tutorial_commands_match_current_entry():
    from ahe_beta.experiment.cli import build_parser

    def commands(name):
        return [
            line.strip()
            for line in (ROOT / "docs/tutorials" / name).read_text().splitlines()
            if line.startswith("uv run ") and "backend/scripts/experiment.py" in line
        ]

    english = commands("evolution32.md")
    assert english and english == commands("evolution32.zh-CN.md")
    for command in english:
        build_parser().parse_args(shlex.split(command.split("backend/scripts/experiment.py", 1)[1]))
