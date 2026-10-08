"""Spec-0069: the public contract fails before any infrastructure creation."""

import copy
import json

import pytest

from auto_designer.experiment.config import ConfigError, load_config_v2, load_task_package


def definition():
    model = {
        "model": "available-model",
        "base_url_env": "MODEL_BASE_URL",
        "api_key_env": "MODEL_API_KEY",
    }
    return {
        "schema_version": 2,
        "name": "test",
        "runtime": {
            "backend": "local",
            "gitea": {"provider": "localhost", "repository_prefix": "test"},
        },
        "harness": {"source": "builtin"},
        "workload": {
            "kind": "ordinary",
            "task_package": "../task.json",
            "persona_library": "../personas.json",
            "persona_ids": ["sr-15-swyx"],
        },
        "rounds": {"count": 5, "sessions_per_round": 1, "max_parallel_users": 1},
        "roles": {
            "triager": 1,
            "synthesizer": 1,
            "divergent": 0,
            "owner_mode": "mechanical",
            "developer": 1,
        },
        "models": {
            "user": copy.deepcopy(model),
            "harness": copy.deepcopy(model),
            "demand": copy.deepcopy(model),
            "delivery": {**model, "backend": "claude-code"},
        },
        "evaluation": {"official_grading": False},
    }


def package():
    return {
        "schema_version": 1,
        "kind": "ordinary",
        "id": "simple-task",
        "instruction_file": "instruction.md",
        "source": {"kind": "local", "path": "repo"},
        "setup": {"script": "setup.sh", "requirements_lock": "requirements.lock"},
        "not_in_benchmark": True,
    }


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


def load_fixture_config(path):
    document = json.loads(path.read_text())
    workload = document.get("workload", {})
    if "task_package" in workload:
        target = (path.parent / workload["task_package"]).resolve()
        if not target.exists():
            write(target, package())
    return load_config_v2(path)


def test_paths_resolve_against_configuration_not_cwd(tmp_path, monkeypatch):
    path = write(tmp_path / "configs/example.json", definition())
    monkeypatch.chdir("/")
    config = load_fixture_config(path)
    assert config["workload"]["task_packages"] == [str(tmp_path / "task.json")]
    assert "kind" not in config["workload"]
    assert config["models"]["user"]["api_key_env"] == "MODEL_API_KEY"


@pytest.mark.parametrize(
    "location", [(), ("rounds",), ("runtime",), ("models", "demand"), ("workload",)]
)
def test_unknown_fields_fail_at_every_public_boundary(tmp_path, location):
    document = definition()
    parent = document
    for field in location:
        parent = parent[field]
    parent["pretend_option"] = "ignored-before"
    with pytest.raises(ConfigError, match="Additional properties"):
        load_fixture_config(write(tmp_path / "config.json", document))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["runtime"].update(
            e2b={"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600}
        ),
        lambda d: d["runtime"]["gitea"].update(provider="gitea.com"),
        lambda d: d["rounds"].update(max_parallel_users=2),
        lambda d: d["harness"].update(archive="seed.tar.gz"),
        lambda d: d["evaluation"].update(official_grading=True),
        lambda d: d["models"]["demand"].update(api_key="secret"),
    ],
)
def test_incompatible_settings_fail(tmp_path, mutation):
    document = definition()
    mutation(document)
    with pytest.raises(ConfigError):
        load_fixture_config(write(tmp_path / "config.json", document))


def test_legacy_schema_is_explicitly_identified(tmp_path):
    with pytest.raises(ConfigError, match="migration"):
        load_fixture_config(write(tmp_path / "config.json", {"schema_version": 1}))


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"termination_grace_seconds": 60},
        {"request_budget_seconds": 0},
        {"request_budget_seconds": True},
        {"request_budget_seconds": 86401},
        {"request_budget_seconds": 3600, "termination_grace_seconds": 0},
        {"request_budget_seconds": 3600, "termination_grace_seconds": 301},
        {"request_budget_seconds": 3600, "unknown": True},
    ],
)
def test_invalid_public_harness_limits_fail_before_provider(tmp_path, limits):
    document = definition()
    document["runtime"]["harness"] = limits
    with pytest.raises(ConfigError):
        load_fixture_config(write(tmp_path / "config.json", document))


def test_public_request_budget_is_preserved_without_adding_defaults(tmp_path):
    document = definition()
    document["runtime"]["harness"] = {"request_budget_seconds": 3600}
    config = load_fixture_config(write(tmp_path / "config.json", document))
    assert config["runtime"]["harness"] == {"request_budget_seconds": 3600}


def test_task_paths_and_provenance(tmp_path):
    task = load_task_package(write(tmp_path / "task.json", package()))
    assert task["source"]["path"] == str(tmp_path / "repo")
    assert task["setup"]["script"] == str(tmp_path / "setup.sh")
    document = package()
    del document["not_in_benchmark"]
    with pytest.raises(ConfigError, match="not_in_benchmark"):
        load_task_package(write(tmp_path / "task.json", document))


@pytest.mark.parametrize(
    "extra", ["patch", "gold_patch", "FAIL_TO_PASS", "hidden_tests", "expected_answer"]
)
def test_oracle_fields_have_no_training_contract(tmp_path, extra):
    document = package()
    document[extra] = "oracle"
    with pytest.raises(ConfigError, match="Additional properties"):
        load_task_package(write(tmp_path / "task.json", document))


def test_git_task_rejects_credential_url(tmp_path):
    document = package()
    document["source"] = {
        "kind": "git",
        "url": "https://token@example.com/a/b",
        "revision": "a" * 40,
        "repo": "a/b",
    }
    with pytest.raises(ConfigError, match="credential-free"):
        load_task_package(write(tmp_path / "task.json", document))


# Spec-0072/T1: accepted policies must survive normalization and become hashable inputs.
def test_policy_defaults_and_explicit_auth_protocol_are_frozen(tmp_path):
    from auto_designer.experiment.config import config_hash

    document = definition()
    document["models"]["delivery"].update(auth_type="api-key", api_key_env="MY_PRIVATE_KEY")
    document["policies"] = {"synthesizer_grouping": True, "delivery": {"poll_seconds": 0.25}}
    document["roles"]["owner_mode"] = "llm"
    loaded = load_fixture_config(write(tmp_path / "config.json", document))
    assert loaded["policies"]["synthesizer_grouping"] is True
    assert loaded["policies"]["delivery"]["poll_seconds"] == 0.25
    assert loaded["policies"]["delivery"]["timeout_seconds"] == 86400
    assert loaded["policies"]["timing"]["latency_isolated"] is False
    assert loaded["models"]["delivery"]["auth_type"] == "api-key"
    changed = copy.deepcopy(loaded)
    changed["policies"]["timing"]["latency_isolated"] = True
    assert config_hash(data=changed) != config_hash(data=loaded)


@pytest.mark.parametrize(
    "policies",
    [
        {"synthesizer_grouping": "1"},
        {"timing": {"wall_guard_seconds": -1}},
        {"delivery": {"timeout_seconds": 0}},
        {"delivery": {"poll_seconds": 0}},
        {"delivery": {"idle_timeout_seconds": -1}},
        {"delivery": {"permission_mode": "invented"}},
        {"delivery": {"coordination": "invented"}},
        {"alarms": {"ready_depth": -1}},
        {"alarms": {"proposal_depth": 0}},
        {"delivery": {"unknown_override": True}},
    ],
)
def test_policy_errors_fail_before_any_provider(tmp_path, policies):
    document = definition()
    document["policies"] = policies
    with pytest.raises(ConfigError):
        load_fixture_config(write(tmp_path / "config.json", document))


@pytest.mark.parametrize("role", ["user", "demand"])
def test_reasoning_effort_is_validated_and_preserved(tmp_path, role):
    document = definition()
    document["models"][role]["reasoning_effort"] = "high"
    assert (
        load_fixture_config(write(tmp_path / "config.json", document))["models"][role][
            "reasoning_effort"
        ]
        == "high"
    )
    document["models"][role]["reasoning_effort"] = "high\nwrong"
    with pytest.raises(ConfigError):
        load_fixture_config(write(tmp_path / "config.json", document))


# Spec-0080/T1: selected cards remain unique, but sessions can reuse them.
def test_sessions_can_exceed_selected_personas(tmp_path):
    document = definition()
    document["rounds"].update(sessions_per_round=3, max_parallel_users=2)
    loaded = load_fixture_config(write(tmp_path / "config.json", document))
    assert loaded["rounds"]["sessions_per_round"] == 3
    assert loaded["workload"]["persona_ids"] == ["sr-15-swyx"]


def test_selected_persona_ids_still_must_be_unique(tmp_path):
    document = definition()
    document["workload"]["persona_ids"] *= 2
    with pytest.raises(ConfigError, match="non-unique"):
        load_fixture_config(write(tmp_path / "config.json", document))
