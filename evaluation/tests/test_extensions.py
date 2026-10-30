"""Standard task packages and Index-specific extensions keep distinct contracts."""

import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.benchmarks import get_profile
from evaluation.benchmarks.harbor_index.profile import EnvironmentSupport
from evaluation.benchmarks.harbor_index.source import PIN
from evaluation.config import HarborEvaluationPlan
from evaluation.harbor.contracts import resolve_contract, runtime_source_files
from evaluation.harbor.grading import grade_issues
from evaluation.harbor.job import job_config
from evaluation.harbor.tasks import resolve_case
from evaluation.tests.test_execution import payload, task


def test_standard_task_contract_does_not_require_a_benchmark_plugin(tmp_path):
    case = payload(task(tmp_path))["cases"][0]
    assert get_profile("Harbor") is None
    assert resolve_case(case) == resolve_contract(tmp_path)


def test_index_dataset_explicit_source_keeps_default_selection(tmp_path):
    raw = payload(task(tmp_path))
    raw.pop("cases")
    raw["dataset"] = {"source": "harbor_index", "revision": PIN["revision"]}
    explicit = HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")
    raw["dataset"].pop("source")
    implicit = HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")
    assert explicit == implicit
    assert len(explicit.cases) == 43


def test_standard_package_has_no_index_specific_judge_or_thread_settings(tmp_path):
    raw = payload(task(tmp_path))
    raw["cases"][0]["task_id"] = "usaco-assign-cows-to-barns"
    plan = HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")
    case = asdict(plan.cases[0])
    manifest = {
        "cases": [case],
        "harnesses": [asdict(plan.harnesses[0])],
        "resolved_cases": {"Harbor/" + case["task_id"]: resolve_contract(tmp_path)},
        "harness_model": plan.harness_model,
        "provider": asdict(plan.provider),
    }
    trial = {"benchmark": "Harbor", "task_id": case["task_id"], "harness": "seed"}
    ordinary = job_config(manifest, trial, tmp_path / "jobs", "job")
    assert "OMP_NUM_THREADS" not in ordinary["verifier"]["env"]
    assert not set(PIN["judge"]) & set(ordinary["verifier"]["env"])
    case["benchmark"] = trial["benchmark"] = "Harbor Index"
    manifest["resolved_cases"] = {"Harbor Index/" + case["task_id"]: resolve_contract(tmp_path)}
    index = job_config(manifest, trial, tmp_path / "jobs", "job")
    assert index["verifier"]["env"]["OMP_NUM_THREADS"] == "1"
    assert index["environment"]["kwargs"]["benchmark"] == "Harbor Index"


def test_generic_grading_accepts_verifiers_without_index_stdout_format(tmp_path):
    case = {"benchmark": "Harbor", "task_id": "gaia2-unrelated"}
    (tmp_path / "reward.json").write_text(json.dumps({"reward": 0.25}))
    assert not grade_issues(case, {"reward": 0.25}, tmp_path)
    assert grade_issues(case, {"reward": 0}, tmp_path)
    case["benchmark"] = "Harbor Index"
    assert grade_issues(case, {"reward": 0.25}, tmp_path)


def test_index_affinity_is_applied_only_to_the_verifier(tmp_path, monkeypatch):
    from evaluation.benchmarks.harbor_index.support import gso_affinity

    configure = AsyncMock(return_value="/affinity/bin:/usr/bin")
    monkeypatch.setattr(gso_affinity, "configure", configure)
    env = SimpleNamespace(
        environment_name="gso-speedup-example",
        environment_dir=tmp_path,
        _verifier_environment=True,
        are=None,
    )
    support = EnvironmentSupport(env)
    asyncio.run(support.start(tmp_path))
    configure.assert_awaited_once_with(env, tmp_path)
    assert support.command_env({"OTHER": "kept"}) == {
        "OTHER": "kept",
        "PATH": "/affinity/bin:/usr/bin",
    }
    env._verifier_environment = False
    other = EnvironmentSupport(env)
    asyncio.run(other.start(tmp_path))
    assert other.command_env({"PATH": "original"}) == {"PATH": "original"}
    assert configure.await_count == 1


def test_e2b_index_compose_support_is_selected_before_native_validation(tmp_path):
    pytest.importorskip("e2b")
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from evaluation.environments.e2b import HarnessE2BEnvironment

    directory = tmp_path / "environment"
    directory.mkdir()
    (directory / "Dockerfile").write_text("FROM scratch\nWORKDIR /app\n")
    (directory / "docker-compose.yaml").write_text("services:\n  main: {}\n  are-sidecar: {}\n")
    kwargs = dict(
        environment_dir=directory,
        environment_name="gaia2-example",
        session_id="agent",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=EnvironmentConfig(docker_image="example/image@sha256:" + "0" * 64),
    )
    env = HarnessE2BEnvironment(**kwargs, benchmark="Harbor Index")
    assert env.support is not None
    with pytest.raises(ValueError, match="generic Compose"):
        HarnessE2BEnvironment(**kwargs)


def test_source_fingerprint_covers_nested_support_without_tests_or_runs():
    sources = runtime_source_files()
    assert "benchmarks/harbor_index/support/are_sidecar.py" in sources
    assert "benchmarks/harbor_index/release.json" in sources
    assert "environments/e2b.py" in sources
    assert not any(p.startswith(("tests/", "runs/")) for p in sources)


@pytest.mark.parametrize("snapshot_result", [None, RuntimeError("snapshot unavailable")])
@pytest.mark.parametrize(
    "driver_error", [None, ConnectionError("stream lost"), asyncio.CancelledError()]
)
def test_harness_mcp_transport_comes_from_selected_support(tmp_path, snapshot_result, driver_error):
    import hashlib

    from harbor.models.agent.context import AgentContext

    from evaluation.harness.agent import FrozenHarnessAgent

    paths = [
        tmp_path / name for name in ["harness.tar.gz", "nexau.whl", "runtime.lock", "python.tar.gz"]
    ]
    for path in paths:
        path.write_bytes(b"frozen")
    digest = hashlib.sha256(b"frozen").hexdigest()
    agent = FrozenHarnessAgent(
        archive=str(paths[0]),
        archive_sha256=digest,
        revision="test",
        runtime_wheel=str(paths[1]),
        runtime_sha256=digest,
        runtime_lock=str(paths[2]),
        runtime_lock_sha256=digest,
        python_archive=str(paths[3]),
        python_sha256=digest,
        workdir="auto",
        request_timeout_sec=30,
        logs_dir=tmp_path,
        model_name="openai/example",
        mcp_servers=[object()],
        skills_dir="/skills",
        extra_env={
            "HARNESS_LLM_API_KEY": "example-key",
            "HARNESS_LLM_BASE_URL": "https://example.com",
        },
    )
    environment = AsyncMock()
    environment.exec.side_effect = [
        SimpleNamespace(stdout="/app\n", return_code=0),
        SimpleNamespace(stdout="", return_code=0),
        driver_error or SimpleNamespace(stdout="", return_code=0),
        snapshot_result or SimpleNamespace(stdout="", return_code=0),
    ]
    environment.support = SimpleNamespace(
        mcp_ready=True,
        mcp_transport="example-transport",
        prepare_mcp=AsyncMock(),
        mcp_instructions=lambda: "\nGENERIC_MCP_HELP",
    )
    cleanup = AsyncMock()
    agent._process_owner.cancel_shielded = cleanup
    environment.attach_mock(cleanup, "cleanup")
    context = AgentContext()
    if driver_error is None:
        asyncio.run(agent.run("Task instruction", environment, context))
        cleanup.assert_not_awaited()
    else:
        with pytest.raises(type(driver_error)) as raised:
            asyncio.run(agent.run("Task instruction", environment, context))
        assert raised.value is driver_error
        cleanup.assert_awaited_once()
        calls = [call[0] for call in environment.mock_calls]
        assert calls.index("cleanup") < max(i for i, name in enumerate(calls) if name == "exec")
    instruction = (tmp_path / "public-instruction.md").read_text()
    assert instruction.startswith("Task instruction\nGENERIC_MCP_HELP")
    assert "Task-provided skills are available at /skills" in instruction
    assert agent.capabilities.mcp_servers and agent.capabilities.skills
    assert context.metadata["mcp_transport"] == "example-transport"
    environment.support.prepare_mcp.assert_awaited_once_with("/app")
    environment.finish_mcp.assert_awaited_once()
