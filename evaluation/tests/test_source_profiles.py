"""Source rules stay in profiles throughout public YAML preparation and jobs."""

import ast
import builtins
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from evaluation import benchmarks, preparation
from evaluation.configuration import ConfigurationError, load
from evaluation.harbor.job import job_config
from evaluation.harbor.tasks import local_task_digest, verify_case
from evaluation.tests.test_execution import payload, task


def write_config(tmp_path, **overrides):
    data = {
        "version": 1,
        "task_source": "harbor",
        "tasks": ["tasks/custom-task"],
        "harnesses": ["v0"],
        "paths": {"harnesses": "harnesses", "cache": "cache", "runs": "runs"},
        "actor": {"base_url": "https://actor.invalid/v1"},
        "user": {"enabled": False},
    }
    data.update(overrides)
    path = tmp_path / "evaluation.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def materials(tmp_path):
    root = tmp_path / "tasks/custom-task"
    root.mkdir(parents=True)
    task(root)
    harness = tmp_path / "harnesses/v0"
    harness.mkdir(parents=True)
    (harness / "entry.py").write_text("def main(): pass\n")
    return root


def test_standard_package_public_entry_never_imports_index_rules(tmp_path, monkeypatch):
    root = materials(tmp_path)
    path = write_config(tmp_path)
    original_import = builtins.__import__
    original_profile_import = benchmarks.import_module

    def guard(name):
        if "benchmarks.harbor_index" in name:
            raise AssertionError("Standard Harbor source must not load Index rules")

    def imported(name, *args, **kwargs):
        guard(name)
        return original_import(name, *args, **kwargs)

    def profile_import(name):
        guard(name)
        return original_profile_import(name)

    monkeypatch.setattr(builtins, "__import__", imported)
    monkeypatch.setattr(benchmarks, "import_module", profile_import)
    # Real configuration, task hashing, task.toml parsing, source archiving and
    # manifest/job generation; only the large external runtime bundle is a fixture.
    monkeypatch.setattr(preparation, "runtime_descriptor", lambda: {})
    from evaluation.cli import main

    assert main(["validate", "--config", str(path)]) == 0
    config = load(path)
    assert config.task_names() == ["custom-task"]
    assert config.data["judge"] == {"base_url": None, "api_key_env": "JUDGE_API_KEY"}
    manifest, _ = preparation.plan(config, download=False)
    case = manifest["cases"][0]
    assert case["benchmark"] == "Harbor" and case["root"] == str(root)
    assert manifest["dataset"]["source"] == "harbor"
    assert case["digest"] == local_task_digest(root)
    job = job_config(manifest, manifest["trials"][0], tmp_path / "jobs", "custom")
    assert "benchmark_options" not in job["environment"]["kwargs"]
    assert "JUDGE_MODELS" not in job["verifier"]["env"]
    assert job["agents"][0]["kwargs"]["request_timeout_sec"] == 90
    # Source files remain the frozen evidence even for a downloaded task package.
    (root / "instruction.md").write_text("changed after freeze")
    with pytest.raises(ValueError, match="changed"):
        verify_case(case)


def test_different_profile_controls_public_config_and_preparation(tmp_path, monkeypatch):
    from evaluation.benchmarks import harbor

    root = materials(tmp_path)
    observed = []

    def validate(data):
        data["judge"].setdefault("model", "different-official-model")
        if data["judge"]["model"] != "different-official-model":
            raise ValueError("Other source owns its judge contract")
        harbor.task_names(data["tasks"])

    def prepare(config, download=True):
        observed.append(download)
        dataset, cases = harbor.prepare_cases(config, download)
        return {**dataset, "source": "other"}, tuple(
            replace(case, benchmark="Other") for case in cases
        )

    profile = SimpleNamespace(
        validate_configuration=validate,
        task_names=harbor.task_names,
        prepare_cases=prepare,
        verify_case=lambda case: verify_case({**case, "benchmark": "Harbor"}),
        environment_options=lambda runtime: {"other_model": runtime["judge"]["model"]},
        verifier_env=lambda task_id, runtime, metadata: {"OTHER_MODEL": runtime["judge"]["model"]},
    )
    monkeypatch.setitem(benchmarks._SOURCES, "other", ("Other", "fixture_other"))
    original = benchmarks.import_module
    monkeypatch.setattr(
        benchmarks,
        "import_module",
        lambda name: profile if name == "fixture_other" else original(name),
    )
    monkeypatch.setattr(preparation, "runtime_descriptor", lambda: {})
    config = load(write_config(tmp_path, task_source="other"))
    manifest, _ = preparation.plan(config, download=False)
    assert observed == [False]
    assert (
        manifest["metadata"]["evaluation_runtime"]["judge"]["model"] == "different-official-model"
    )
    assert manifest["cases"][0]["digest"] == local_task_digest(root)
    job = job_config(manifest, manifest["trials"][0], tmp_path / "jobs", "other")
    assert job["verifier"]["env"]["OTHER_MODEL"] == "different-official-model"
    assert job["environment"]["kwargs"]["benchmark_options"] == {
        "other_model": "different-official-model"
    }


@pytest.mark.parametrize("name", [None, [], {}, "missing"])
def test_unknown_source_is_rejected_offline(tmp_path, name):
    with pytest.raises(ConfigurationError, match="Unknown task_source"):
        load(write_config(tmp_path, task_source=name))


@pytest.mark.parametrize("selection", [None, [], "published38", ["a/same", "b/same"], [42]])
def test_standard_packages_reject_ambiguous_or_catalog_only_selection(tmp_path, selection):
    with pytest.raises(ConfigurationError):
        load(write_config(tmp_path, tasks=selection))


@pytest.mark.parametrize("judge", [{"model": "claude-opus-5"}, {"normalize_usage": False}])
def test_index_options_are_not_silently_accepted_for_standard_packages(tmp_path, judge):
    with pytest.raises(ConfigurationError, match="task package owns"):
        load(write_config(tmp_path, judge=judge))


@pytest.mark.parametrize("download", [False, True])
def test_index_keeps_its_pinned_catalog_and_download_policy(tmp_path, monkeypatch, download):
    from evaluation.benchmarks.harbor_index import profile
    from evaluation.benchmarks.harbor_index.source import PIN

    config = load(write_config(tmp_path, task_source="harbor_index", tasks="published38"))
    assert len(config.task_names()) == 38
    seen = []
    monkeypatch.setattr(profile, "prepare_dataset", seen.append)
    dataset, cases = profile.prepare_cases(config, download)
    assert dataset["revision"] == PIN["revision"]
    assert len(cases) == 38
    assert len(seen) == int(download)


@pytest.mark.parametrize("benchmark", ["Harbor", "Harbor Index"])
def test_deferred_anticheat_policy_is_scoped_to_index(tmp_path, benchmark):
    from evaluation.config import HarborEvaluationPlan
    from evaluation.harbor.contracts import resolve_contract

    plan = HarborEvaluationPlan.from_mapping(payload(task(tmp_path)), tmp_path / "plan.json")
    case = {**asdict(plan.cases[0]), "benchmark": benchmark, "task_id": "gso-another-package"}
    manifest = {
        "cases": [case],
        "harnesses": [asdict(plan.harnesses[0])],
        "resolved_cases": {benchmark + "/" + case["task_id"]: resolve_contract(tmp_path)},
        "harness_model": plan.harness_model,
        "provider": asdict(plan.provider),
        "metadata": {"anti_cheat_review": "deferred_by_user"},
    }
    trial = {"benchmark": benchmark, "task_id": case["task_id"], "harness": "seed"}
    job = job_config(manifest, trial, tmp_path / "jobs", "fixture")
    assert job["verifier"]["env"]["ANTHROPIC_API_KEY"] == (
        "" if benchmark == "Harbor Index" else "${JUDGE_ANTHROPIC_API_KEY}"
    )


def test_generic_layers_have_no_index_imports_or_business_literals():
    package = Path(__file__).resolve().parents[1]
    files = [package / name for name in ("configuration.py", "preparation.py", "cli.py")]
    files.extend((package / "harbor").glob("*.py"))
    files.extend((package / "environments").glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "harbor_index" not in (node.module or ""), path
            if isinstance(node, ast.Import):
                assert not any("harbor_index" in alias.name for alias in node.names), path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in {
                    "claude-opus-5",
                    "published38",
                    "harbor_index",
                    "algotune-",
                    "gso-",
                }, path
