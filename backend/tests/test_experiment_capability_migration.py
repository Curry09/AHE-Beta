"""Spec-0072/T5: public config → frozen inputs → both environments → real consumers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ahe_beta.experiment.context import build_controller_environment
from ahe_beta.experiment.materials import prepare_materials, verify_materials
from test_experiment_materials import prepared_inputs as material_fixture  # noqa: F401


@pytest.fixture(params=["local", "e2b"])
def frozen_policy_environment(request, tmp_path, monkeypatch):
    prepared_inputs = request.getfixturevalue("material_fixture")
    config = json.loads(prepared_inputs.read_text())
    backend = request.param
    if backend == "e2b":
        config["runtime"] = {
            "backend": "e2b",
            "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
            "e2b": {"cpu_count": 2, "memory_mb": 2048, "timeout_seconds": 3600},
        }
    config["policies"] = {
        "architect_grouping": True,
        "timing": {"latency_isolated": True, "wall_guard_seconds": 120},
        "delivery": {
            "coordination": "dependencies",
            "timeout_seconds": 2,
            "poll_seconds": 0.25,
            "idle_timeout_seconds": 0,
        },
        "alarms": {"proposal_depth": 7, "ready_depth": 8},
    }
    config["models"]["user"]["reasoning_effort"] = "high"
    config["models"]["demand"]["reasoning_effort"] = "medium"
    config["roles"]["owner_mode"] = "llm"
    config["models"]["delivery"].update(auth_type="api-key", api_key_env="CUSTOM_AUTH")
    prepared_inputs.write_text(json.dumps(config))
    manifest = prepare_materials(prepared_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    from ahe_beta.experiment.workload import read_task_catalog
    from test_experiment_workload import task_resources

    resources = {
        "gitea": {"url": "https://gitea.example", "owner": "fixture", "repo": "owned"},
        "task_workspaces": task_resources(read_task_catalog(root, manifest)),
    }
    if backend == "e2b":
        resources["sandbox_id"] = "owned-sandbox"
        for workspace in resources["task_workspaces"].values():
            workspace["kind"] = "prebuilt"
    env = build_controller_environment(
        run_dir=root,
        manifest=manifest,
        credentials={
            "GITEA_TOKEN": "fixture-forge",
            "MODEL_BASE_URL": "https://fixture.example",
            "MODEL_API_KEY": "fixture-model",
            "CUSTOM_AUTH": "fixture-delivery",
        },
        resources=resources,
    )
    # Changing host/original files cannot redefine this prepared experiment.
    prepared_inputs.write_text("{}")
    monkeypatch.setenv("ARCHITECT_GROUPING", "0")
    verify_materials(manifest)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return root, manifest, env


def test_grouping_and_round_gate_use_frozen_public_options(frozen_policy_environment):
    from ahe_beta.demand.grouped_architect import GroupedArchitect, group_architect_stage
    from ahe_beta.loop.round_gate import RoundDeliveryBlocked, wait_round_delivery

    root, manifest, env = frozen_policy_environment
    tracker = object()
    workers = [
        SimpleNamespace(_tracker=tracker, _round_provider=None, _on_event=None) for _ in range(2)
    ]
    stage = group_architect_stage(workers, artifact_root=root / "grouping")
    assert len(stage) == 1 and isinstance(stage[0], GroupedArchitect)
    assert stage[0].architects == workers
    now, sleeps, reads = [0.0], [], []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def issue(number):
        reads.append(number)
        return {"state": "open", "labels": []}

    with pytest.raises(RoundDeliveryBlocked):
        wait_round_delivery(numbers=[3], fetch_issue=issue, sleep=sleep, monotonic=lambda: now[0])
    assert sleeps and set(sleeps) == {0.25}
    assert now[0] == 2
    assert len(reads) < 20
    assert manifest["config"]["policies"]["architect_grouping"] is True
    assert env["N_OWNERS"] == "1"


def test_user_reasoning_reaches_actual_chat_request(frozen_policy_environment, monkeypatch):
    import openai

    from ahe_beta.user.sim.persona_client import ApiPersonaClient

    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(usage=None, id="fixture-request")

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **_: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    client = ApiPersonaClient()
    client._create([{"role": "user", "content": "Use the configured effort."}], max_tokens=8)
    assert requests[0]["reasoning_effort"] == "high"
    assert "extra_body" not in requests[0]


def test_demand_reasoning_and_timing_reach_agent_runtime(
    frozen_policy_environment, tmp_path, monkeypatch
):
    import nexau

    from ahe_beta.demand import agent_runtime
    from ahe_beta.user.session_store import SessionStore

    observed = {}
    cfg = SimpleNamespace(
        max_iterations=1, resolved_tracer=None, llm_config=SimpleNamespace(extra_params={})
    )
    monkeypatch.setattr(nexau.AgentConfig, "from_yaml", lambda **_: cfg)

    class Agent:
        def __init__(self, *, config):
            observed["effort"] = config.llm_config.extra_params["reasoning_effort"]

        def run(self, *, message):
            return {"decisions": []}

    monkeypatch.setattr(nexau, "Agent", Agent)

    def timeout(fn, seconds, **kwargs):
        observed.update(kwargs)
        return fn()

    monkeypatch.setattr(agent_runtime, "run_with_timeout", timeout)
    agent_dir = tmp_path / "owner-def"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("fixture")
    result = agent_runtime.run_agent_def(
        agent_dir,
        "Review the proposal.",
        store=SessionStore(tmp_path / "sessions"),
        repo=tmp_path,
        role="owner",
        timeout=5,
    )
    assert json.loads(result) == {"decisions": []}
    assert observed["effort"] == "medium"
    assert observed["latency_isolated"] is True
    assert observed["wall_guard"] == 120


def test_coordination_reaches_delivery_configuration(frozen_policy_environment, tmp_path):
    from ahe_beta.experiment.controllers.runtime import write_openagents_config

    root, manifest, env = frozen_policy_environment
    target = write_openagents_config(
        repo=tmp_path,
        gitea={
            "GITEA_URL": "https://fixture.example",
            "OWNER": "fixture",
            "REPO": "owned",
            "TOKEN": "not-written",
        },
    )
    text = target.read_text()
    assert "coordination: dependencies" in text
    assert "not-written" not in text


@pytest.mark.parametrize("configured, expected_grace", [(0, 600), (120, 120)])
def test_latency_wall_guard_retains_existing_budget_plus_grace(
    configured, expected_grace, monkeypatch
):
    """Spec-0072/T5: zero is legacy automatic grace, never a disabled wall cap."""
    from ahe_beta.demand import agent_runtime
    from ahe_beta.experiment.config import runtime_policies

    cancelled = []
    budget = 5
    policy = runtime_policies({"policies": {"timing": {"wall_guard_seconds": configured}}})

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return True

    class Accounting:
        def snapshot(self):
            return {
                "active_elapsed_ms": 0,
                "wall_elapsed_ms": (budget + expected_grace) * 1000,
                "provider_active": True,
            }

    monkeypatch.setattr(agent_runtime.threading, "Thread", Thread)
    monkeypatch.setattr(agent_runtime, "current_time_accounting", lambda: Accounting())
    with pytest.raises(agent_runtime.AgentTimeout) as error:
        agent_runtime.run_with_timeout(
            lambda: None,
            budget,
            wall_guard=policy["timing"]["wall_guard_seconds"] or None,
            latency_isolated=True,
            cancel=lambda: cancelled.append(True),
        )
    assert error.value.timeout_class == "infrastructure_timeout"
    assert f">{budget + expected_grace}.0s" in str(
        error.value
    ) or f">{budget + expected_grace}s" in str(error.value)
    assert cancelled == [True]
