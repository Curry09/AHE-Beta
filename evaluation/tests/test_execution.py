"""Contracts and recovery behavior, without claiming official benchmark success."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from evaluation.benchmarks.harbor_index.source import PIN
from evaluation.cli import _run_lock
from evaluation.config import HarborEvaluationPlan, PlanError
from evaluation.harbor.contracts import resolve_contract
from evaluation.harbor.grading import grade_issues
from evaluation.harbor.scheduler import Orchestrator
from evaluation.harbor.tasks import local_task_digest, verify_case
from evaluation.harness.materials import prepare_materials
from evaluation.report import summarize_run
from evaluation.results import OutcomeKind, TrialResult
from evaluation.state import RunStateStore


@pytest.mark.parametrize("reward", [0, 1])
@pytest.mark.parametrize("termination", ["HarnessExecutionError", "HarnessSelfTimeout"])
def test_archived_harness_error_reply_does_not_count_as_normal(tmp_path, reward, termination):
    from evaluation.harbor.executor import HarborExecutor

    executor = HarborExecutor.__new__(HarborExecutor)
    executor.manifest = {"harnesses": [{"id": "frozen"}]}
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "harness-reply.txt").write_text("[harness error] Unexpected OpenAI response type")
    (agent / "harness-driver-result.json").write_text(
        json.dumps({"normal_reply": False, "termination_reason": termination})
    )
    result = executor._result(
        {"trial_id": "one", "harness": "frozen"},
        1,
        {},
        {"reward": reward},
        tmp_path / "result.json",
    )
    assert result.terminal_reply and not result.normal_reply
    failed_outcome = (
        OutcomeKind.HARNESS_SELF_TIMEOUT
        if termination == "HarnessSelfTimeout"
        else OutcomeKind.HARNESS_CRASH
    )
    assert result.outcome is (OutcomeKind.TASK_SUCCESS if reward else failed_outcome)
    assert result.passed == bool(reward)


def task(root):
    root.mkdir(exist_ok=True)
    (root / "task.toml").write_text("""schema_version = "1.3"
[agent]
timeout_sec = 90
[environment]
cpus = 1
memory_mb = 1024
build_timeout_sec = 180
[verifier]
timeout_sec = 20
environment_mode = "separate"
[verifier.environment]
cpus = 2
memory_mb = 2048
build_timeout_sec = 120
""")
    (root / "instruction.md").write_text("Do the task.")
    (root / "tests").mkdir()
    (root / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    return root


def payload(root):
    return {
        "schema_version": 2,
        "suite": "smoke",
        "cases": [
            {
                "benchmark": "Harbor",
                "task_id": "smoke",
                "revision": "operator-v1",
                "root": str(root),
                "digest": local_task_digest(root),
            }
        ],
        "harnesses": [
            {
                "id": "seed",
                "archive": "harness.tar.gz",
                "sha256": "unused",
                "revision": "frozen",
                "runtime": {
                    "runtime_wheel": "nexau.whl",
                    "runtime_sha256": "unused",
                    "runtime_lock": "runtime.lock",
                    "runtime_lock_sha256": "unused",
                    "python_archive": "python.tar.gz",
                    "python_sha256": "unused",
                },
            }
        ],
        "models": {"harness": "openai/example"},
        "provider": {"type": "e2b"},
    }


def test_task_owned_roles_and_grace(tmp_path):
    contract = resolve_contract(task(tmp_path))
    assert contract["agent_timeout_seconds"] == 90
    assert contract["outer_agent_timeout_seconds"] == 690
    assert contract["environment_build_timeout_seconds"] == 180
    assert contract["resources"]["agent"]["cpus"] == 1
    assert contract["resources"]["verifier"]["cpus"] == 2
    assert contract["resources"]["verifier"]["build_timeout_sec"] == 120


@pytest.mark.parametrize("override", ["cpu", "cpus", "memory_mb", "image", "image_digest"])
def test_global_resource_overrides_rejected(tmp_path, override):
    raw = payload(task(tmp_path))
    raw["provider"][override] = 8
    with pytest.raises(PlanError, match="task.toml"):
        HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")


def test_explicit_plan_paths_and_material_descriptor(tmp_path):
    root = task(tmp_path / "task")
    raw = payload(root)
    material = raw["harnesses"][0].copy()
    material.pop("id")
    kits = tmp_path / "kits"
    kits.mkdir()
    (kits / "materials.json").write_text(json.dumps(material))
    raw["harnesses"] = [{"id": "seed", "materials": "kits/materials.json"}]
    plan = HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")
    assert plan.harnesses[0].archive == str(kits / "harness.tar.gz")
    assert plan.harnesses[0].runtime["python_archive"] == str(kits / "python.tar.gz")


@pytest.mark.parametrize("names", [[], [{}], ["unknown"], [PIN["tasks"][0]] * 2])
def test_invalid_index_selections_raise_plan_error(tmp_path, names):
    raw = payload(task(tmp_path))
    raw.pop("cases")
    raw["dataset"] = {"revision": PIN["revision"], "task_names": names}
    with pytest.raises(PlanError):
        HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")


def test_undeclared_resources_stay_undeclared(tmp_path):
    task(tmp_path)
    (tmp_path / "task.toml").write_text("[environment]\n[verifier]\n")
    contract = resolve_contract(tmp_path)
    assert contract["resources"] == {"agent": {}, "verifier": {}}
    assert contract["agent_timeout_seconds"] == 1800
    assert contract["outer_agent_timeout_seconds"] == 2400


def test_complete_task_inventory_frozen(tmp_path):
    raw = payload(task(tmp_path))["cases"][0]
    verify_case(raw)
    (tmp_path / "extra.txt").write_text("new")
    with pytest.raises(ValueError, match="changed"):
        verify_case(raw)


def test_material_failure_does_not_publish_partial_kit(tmp_path, monkeypatch):
    from evaluation.harness import materials

    def fail(source, output):
        (output / "partial").write_text("partial")
        raise RuntimeError("compile failed")

    monkeypatch.setattr(materials, "build_materials", fail)
    destination = tmp_path / "kit"
    with pytest.raises(RuntimeError):
        prepare_materials(tmp_path, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".materials-*"))


def test_run_lock_excludes_other_controller(tmp_path):
    with _run_lock(tmp_path), pytest.raises(PlanError, match="Another controller"):
        with _run_lock(tmp_path):
            pytest.fail("second controller obtained lock")


def test_resumed_running_trial_uses_same_attempt(tmp_path):
    manifest = {"manifest_digest": "digest", "trials": [{"trial_id": "one"}]}
    RunStateStore(tmp_path, manifest).transition("one", "running", attempts=1)

    class Executor:
        reconnect_running = True

        def __call__(self, trial, attempt, root):
            assert attempt == 1
            return TrialResult("one", attempt, OutcomeKind.TASK_FAILURE, False, True, True, True, 3)

    result = Orchestrator(manifest, tmp_path, Executor(), max_invalid_attempts=1).run()
    assert result["valid_trials"] == 1


def test_regrade_replaces_score_once_in_summary(tmp_path):
    manifest = {"manifest_digest": "digest", "trials": [{"trial_id": "one"}]}
    original = tmp_path / "trials/one/attempt-1/result.json"
    original.parent.mkdir(parents=True)
    original.write_text(
        json.dumps(
            TrialResult("one", 1, OutcomeKind.GRADER_FAILURE, False, True, True, False, 3).to_dict()
        )
    )
    recovered = tmp_path / "trials/one/grading/grade/result.json"
    recovered.parent.mkdir(parents=True)
    recovered.write_text(
        json.dumps(
            TrialResult("one", 1, OutcomeKind.TASK_SUCCESS, True, True, True, True, 3).to_dict()
        )
    )
    RunStateStore(tmp_path, manifest).transition(
        "one", "terminal", attempts=1, result=str(recovered), grading_attempt=str(recovered.parent)
    )
    summary = summarize_run(tmp_path)
    assert summary["attempts"] == summary["passed"] == summary["valid_trials"] == 1
    assert original.exists()


@pytest.mark.parametrize("bundled", [False, True])
@pytest.mark.parametrize("verifier_build_timeout", [120, 240])
def test_regrade_preserves_official_verifier_image_and_test_delivery(
    tmp_path, monkeypatch, bundled, verifier_build_timeout
):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import Mock

    from evaluation.harbor import regrade as module

    root = task(tmp_path / "task")
    (root / "environment").mkdir()
    image = "example/agent@sha256:" + "0" * 64
    content = (
        (root / "task.toml")
        .read_text()
        .replace("[environment]\n", f'[environment]\ndocker_image = "{image}"\n')
    )
    if bundled:
        image = "example/verifier@sha256:" + "1" * 64
        content = content.replace(
            "[verifier.environment]\n", f'[verifier.environment]\ndocker_image = "{image}"\n'
        )
    content = content.replace(
        "build_timeout_sec = 120", f"build_timeout_sec = {verifier_build_timeout}"
    )
    (root / "task.toml").write_text(content)
    original = tmp_path / "original"
    (original / "artifacts").mkdir(parents=True)
    (original / "artifacts/answer.txt").write_text("immutable output")
    env = AsyncMock()
    env.with_default_user = Mock(return_value=nullcontext())
    factory = Mock(return_value=env)
    monkeypatch.setattr(module.EnvironmentFactory, "create_environment_from_config", factory)
    handler = AsyncMock()
    monkeypatch.setattr(module, "ArtifactHandler", Mock(return_value=handler))
    verifier = AsyncMock()
    verifier.verify.return_value = SimpleNamespace(rewards={"reward": 1})
    verifier_factory = Mock(return_value=verifier)
    monkeypatch.setattr(module.VerifierFactory, "create_verifier_from_config", verifier_factory)
    timeouts = []
    wait_for = asyncio.wait_for

    async def record_budget(awaitable, **kwargs):
        timeouts.append(kwargs["timeout"])
        return await wait_for(awaitable, **kwargs)

    monkeypatch.setattr(module.asyncio, "wait_for", record_budget)
    result = asyncio.run(
        module.regrade(
            root,
            original,
            tmp_path / "regrade",
            {"environment": {"type": "docker"}, "agents": [{}], "verifier": {"env": {}}},
        )
    )
    assert timeouts == [verifier_build_timeout, 20]
    assert result["rewards"] == {"reward": 1}
    assert result["artifacts_unchanged"]
    assert result["actor_model_requests"] == 0
    kwargs = factory.call_args.kwargs
    assert kwargs["environment_dir"] == root / ("tests" if bundled else "environment")
    assert kwargs["task_env_config"].docker_image == image
    assert kwargs["task_env_config"].cpus == 2
    assert verifier_factory.call_args.kwargs["skip_tests_upload"] is bundled
    handler.upload_artifacts.assert_awaited_once()
    env.stop.assert_awaited_once_with(True)


def test_fail_safe_judge_zero_is_invalid(tmp_path):
    (tmp_path / "reward.txt").write_text("0")
    (tmp_path / "test-stdout.txt").write_text("judge crashed")
    assert grade_issues(
        {"benchmark": "Harbor Index", "task_id": "widesearch-list-bri-projects-2025"},
        {"reward": 0},
        tmp_path,
    )
    assert not grade_issues({"benchmark": "Harbor", "task_id": "custom"}, {"reward": 0}, tmp_path)


def test_builtin_job_preserves_official_request_budget(tmp_path):
    pytest.importorskip("harbor")
    from evaluation.harbor.job import job_config

    raw = payload(task(tmp_path))
    plan = HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")
    contract = resolve_contract(tmp_path)
    manifest = {
        "cases": [asdict(plan.cases[0])],
        "harnesses": [asdict(plan.harnesses[0])],
        "resolved_cases": {"Harbor/smoke": contract},
        "harness_model": plan.harness_model,
        "provider": asdict(plan.provider),
    }
    config = job_config(
        manifest,
        {"benchmark": "Harbor", "task_id": "smoke", "harness": "seed"},
        tmp_path / "jobs",
        "job",
    )
    assert config["agents"][0]["kwargs"]["request_timeout_sec"] == 90
    assert config["agents"][0]["override_timeout_sec"] == 690
    assert "override_cpus" not in config["environment"]
    assert config["retry"]["max_retries"] == 0
    assert "LLM_API_KEY" not in config["verifier"]["env"]


def test_native_service_proxy_uses_official_service_interface():
    pytest.importorskip("harbor")
    from harbor.environments.docker.docker import DockerEnvironment

    from evaluation.benchmarks.harbor_index.support.are_sidecar import ServiceEnvironment

    parent = AsyncMock(spec=DockerEnvironment)
    service = ServiceEnvironment(parent, "are-sidecar")
    asyncio.run(service.exec("probe", user="root"))
    parent.service_exec.assert_awaited_once_with("probe", service="are-sidecar", user="root")
    asyncio.run(service.download_file("/logs/event.json", "/tmp/event.json"))
    parent.service_download_file.assert_awaited_once_with(
        "/logs/event.json", "/tmp/event.json", service="are-sidecar"
    )
    asyncio.run(service.download_dir("/logs", "/tmp/logs"))
    parent.service_download_dir.assert_awaited_once_with(
        "/logs", "/tmp/logs", service="are-sidecar"
    )


def executor_fixture(root):
    pytest.importorskip("harbor")
    import threading

    from evaluation.harbor.executor import HarborExecutor

    case = payload(task(root))["cases"][0]
    case["task_id"] = "smoke"
    trial = {"trial_id": "one", "benchmark": "Harbor", "task_id": "smoke", "harness": "seed"}
    executor = HarborExecutor.__new__(HarborExecutor)
    executor.root = root
    executor.manifest = {
        "cases": [case],
        "trials": [trial],
        "harnesses": [{"id": "seed"}],
        "manifest_digest": "digest",
    }
    executor.env_file = None
    executor.detached = threading.Event()
    executor.processes = {}
    return executor, trial


def test_uncertain_launch_never_repeats_agent(tmp_path, monkeypatch):
    executor, trial = executor_fixture(tmp_path)
    execution = tmp_path / "trials/one/execution"
    execution.mkdir(parents=True)
    # Freeze the task before creating execution evidence outside its tree.
    executor.manifest["cases"][0]["digest"] = local_task_digest(tmp_path)
    (execution / "claimed.json").write_text("{}")
    from evaluation.harbor import executor as harbor

    monkeypatch.setattr(harbor, "verify_case", lambda case: None)

    def forbidden(*args, **kwargs):
        pytest.fail("uncertain launch must not spawn another worker")

    monkeypatch.setattr(harbor.subprocess, "Popen", forbidden)
    result = executor(trial, 1, tmp_path)
    assert result.outcome is OutcomeKind.INFRASTRUCTURE_FAILURE
    assert not result.valid_trial


def test_resume_adopts_worker_receipt_and_retained_result(tmp_path, monkeypatch):
    executor, trial = executor_fixture(tmp_path)
    execution = tmp_path / "trials/one/execution"
    execution.mkdir(parents=True)
    (execution / "worker.json").write_text(
        json.dumps({"pid": 123, "config": "config", "actor_launches": 1})
    )
    original = execution / "jobs/job/trial"
    (original / "verifier").mkdir(parents=True)
    (original / "verifier/reward.txt").write_text("1")
    (original / "verifier/test-stdout.txt").write_text("verified")
    (original / "result.json").write_text(
        json.dumps(
            {
                "agent_execution": {
                    "started_at": "2026-10-09T00:00:00+00:00",
                    "finished_at": "2026-10-09T00:00:03+00:00",
                },
                "verifier_result": {"rewards": {"reward": 1}},
            }
        )
    )
    from evaluation.harbor import executor as harbor

    monkeypatch.setattr(harbor, "verify_case", lambda case: None)
    monkeypatch.setattr(executor, "_wait", lambda launch: None)

    def forbidden(*args, **kwargs):
        pytest.fail("resume must not spawn another worker")

    monkeypatch.setattr(harbor.subprocess, "Popen", forbidden)
    result = executor(trial, 1, tmp_path)
    assert result.passed
    assert result.elapsed_seconds == 3
    assert (execution / "launch.json").exists()
    assert result.metrics["actor_launches"] == 1


def test_regrade_rejects_valid_score_before_any_provider_call(tmp_path):
    executor, _ = executor_fixture(tmp_path)
    RunStateStore(tmp_path, executor.manifest).transition(
        "one", "terminal", attempts=1, outcome="task_success"
    )
    with pytest.raises(ValueError, match="valid scores"):
        executor.regrade("one")


def test_regrade_rejects_trial_without_agent_execution(tmp_path):
    executor, _ = executor_fixture(tmp_path)
    RunStateStore(tmp_path, executor.manifest).transition(
        "one", "terminal_invalid", attempts=1, outcome="grader_failure"
    )
    original = tmp_path / "trials/one/execution/jobs/job/trial/result.json"
    original.parent.mkdir(parents=True)
    original.write_text('{"agent_execution": null}')
    with pytest.raises(ValueError, match="never executed"):
        executor.regrade("one")


def test_e2b_role_resources_and_image_identity_do_not_share_templates(tmp_path):
    pytest.importorskip("harbor")
    pytest.importorskip("e2b")
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from evaluation.environments.e2b import HarnessE2BEnvironment

    context = tmp_path / "environment"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\nWORKDIR /app\n")
    image = "example/image@sha256:" + "0" * 64
    paths = TrialPaths(tmp_path / "trial")
    paths.mkdir()
    first = HarnessE2BEnvironment(
        environment_dir=context,
        environment_name="smoke",
        session_id="a",
        trial_paths=paths,
        task_env_config=EnvironmentConfig(docker_image=image, cpus=1, memory_mb=2048),
    )
    second = HarnessE2BEnvironment(
        environment_dir=context,
        environment_name="smoke",
        session_id="b",
        trial_paths=paths,
        task_env_config=EnvironmentConfig(docker_image=image, cpus=2, memory_mb=4096),
    )
    assert first._template_name != second._template_name
    third = HarnessE2BEnvironment(
        environment_dir=context,
        environment_name="smoke",
        session_id="c",
        trial_paths=paths,
        task_env_config=EnvironmentConfig(
            docker_image="example/other@sha256:" + "1" * 64, cpus=1, memory_mb=2048
        ),
    )
    assert first._template_name != third._template_name
    (context / "fixture.txt").write_text("changed environment input")
    fourth = HarnessE2BEnvironment(
        environment_dir=context,
        environment_name="smoke",
        session_id="d",
        trial_paths=paths,
        task_env_config=EnvironmentConfig(docker_image=image, cpus=1, memory_mb=2048),
    )
    assert first._template_name != fourth._template_name


def test_container_limits_use_cgroup_quotas_instead_of_host_cpu_count():
    from types import SimpleNamespace

    from evaluation.environments.base import container_allocation

    config = SimpleNamespace(cpus=1, memory_mb=2048)
    assert container_allocation(
        "48\nMemTotal: 395738444 kB\n100000 100000\n2147483648\n", config
    ) == {
        "allocated_cpus": 1,
        "allocated_memory_mb": 2048,
    }
    with pytest.raises(RuntimeError, match="CPU limit"):
        container_allocation("48\nMemTotal: 395738444 kB\n200000 100000\n2147483648\n", config)
    with pytest.raises(RuntimeError, match="memory limit"):
        container_allocation("48\nMemTotal: 395738444 kB\n100000 100000\n1073741824\n", config)


def test_e2b_creation_preserves_native_startup_environment_and_network(tmp_path, monkeypatch):
    pytest.importorskip("e2b")
    from e2b import AsyncSandbox
    from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
    from harbor.models.trial.paths import TrialPaths

    from evaluation.environments.e2b import HarnessE2BEnvironment

    create = AsyncMock()
    monkeypatch.setattr(AsyncSandbox, "create", create)
    context = tmp_path / "environment"
    context.mkdir()
    env = HarnessE2BEnvironment(
        environment_dir=context,
        environment_name="smoke",
        session_id="smoke",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=EnvironmentConfig(
            docker_image="example/image@sha256:" + "0" * 64,
            env={"TASK_SETTING": "required-at-startup"},
        ),
        network_policy=NetworkPolicy(network_mode=NetworkMode.NO_NETWORK),
        sandbox_timeout_sec=300,
    )
    asyncio.run(env._create_sandbox())
    assert create.call_args.kwargs["envs"]["TASK_SETTING"] == "required-at-startup"
    assert create.call_args.kwargs["timeout"] == 300
    assert create.call_args.kwargs["allow_internet_access"] is False


def test_frozen_material_changed_before_upload_is_rejected(tmp_path):
    pytest.importorskip("harbor")
    import hashlib
    from types import SimpleNamespace

    from evaluation.harness.agent import FrozenHarnessAgent

    archive = tmp_path / "harness.tar.gz"
    wheel = tmp_path / "nexau.whl"
    lock = tmp_path / "runtime.lock"
    python = tmp_path / "python.tar.gz"
    for path in [archive, wheel, lock, python]:
        path.write_bytes(b"frozen")
    digest = hashlib.sha256(b"frozen").hexdigest()
    agent = FrozenHarnessAgent(
        archive=str(archive),
        archive_sha256=digest,
        revision="smoke",
        runtime_wheel=str(wheel),
        runtime_sha256=digest,
        runtime_lock=str(lock),
        runtime_lock_sha256=digest,
        python_archive=str(python),
        python_sha256=digest,
        workdir="auto",
        request_timeout_sec=90,
        logs_dir=tmp_path,
        model_name="openai/test",
    )
    archive.write_bytes(b"changed")
    environment = AsyncMock()
    environment.exec.return_value = SimpleNamespace(return_code=0)
    with pytest.raises(ValueError, match="changed before upload"):
        asyncio.run(agent.setup(environment))
    environment.upload_file.assert_not_awaited()


@pytest.mark.parametrize(
    "failure,expected,graded",
    [
        (None, OutcomeKind.GRADER_FAILURE, True),
        ("VerifierTimeoutError", OutcomeKind.GRADER_FAILURE, True),
        ("ApiResponseStalledError", OutcomeKind.INFRASTRUCTURE_FAILURE, False),
    ],
)
def test_invalid_grades_preserve_agent_receipt_without_relaunch(
    tmp_path, monkeypatch, failure, expected, graded
):
    from evaluation.harbor import executor as module

    executor, trial = executor_fixture(tmp_path)
    execution = tmp_path / "trials/one/execution"
    original = execution / "jobs/job/trial/result.json"
    (original.parent / "agent").mkdir(parents=True)
    (execution / "launch.json").write_text(json.dumps({"pid": 1, "config": "retained"}))
    agent = original.parent / "agent"
    (agent / "harness-reply.txt").write_text("Completed the task.")
    (agent / "harness-driver-result.json").write_text(
        json.dumps({"normal_reply": True, "elapsed_seconds": 1193, "termination_reason": None})
    )
    raw = {
        "agent_execution": {
            "started_at": "2026-10-09T00:00:00+00:00",
            "finished_at": "2026-10-09T00:20:00+00:00",
        },
        "verifier_execution": {"started_at": "2026-10-09T00:20:01+00:00" if graded else None},
        "verifier_result": {"rewards": {"reward": 1} if graded else None},
        "exception_info": {"exception_type": failure} if failure else None,
    }
    original.write_text(json.dumps(raw))
    before = original.read_bytes()
    monkeypatch.setattr(module, "verify_case", lambda case: None)
    monkeypatch.setattr(executor, "_wait", lambda launch: None)
    monkeypatch.setattr(module, "grade_issues", lambda *args: ["Official judge quorum not met"])

    def forbidden(*args, **kwargs):
        pytest.fail("receipt recovery must not launch an Agent")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    result = executor(trial, 1, tmp_path)
    assert result.outcome is expected
    assert not result.passed and not result.valid_trial
    assert result.metrics["valid_grade"] is False
    assert "official_rewards" not in result.metrics
    assert result.terminal_reply
    assert result.normal_reply is (failure != "ApiResponseStalledError")
    assert result.grader_reached is graded
    assert result.elapsed_seconds == 1200
    assert result.artifacts["source_result"] == str(original)
    assert original.read_bytes() == before
    if graded:
        assert result.metrics["unvalidated_rewards"] == {"reward": 1}
        assert result.metrics["agent_exception"] is None


def test_pre_agent_failure_keeps_raw_path_without_claiming_execution(tmp_path, monkeypatch):
    from evaluation.harbor import executor as module

    executor, trial = executor_fixture(tmp_path)
    execution = tmp_path / "trials/one/execution"
    original = execution / "jobs/job/trial/result.json"
    original.parent.mkdir(parents=True)
    (execution / "launch.json").write_text(json.dumps({"pid": 1, "config": "retained"}))
    original.write_text(json.dumps({"exception_info": {"exception_type": "ConnectError"}}))
    monkeypatch.setattr(module, "verify_case", lambda case: None)
    monkeypatch.setattr(executor, "_wait", lambda launch: None)
    result = executor(trial, 1, tmp_path)
    assert result.outcome is OutcomeKind.INFRASTRUCTURE_FAILURE
    assert not result.terminal_reply and not result.normal_reply and not result.grader_reached
    assert result.elapsed_seconds == 0
    assert result.artifacts["source_result"] == str(original)


@pytest.mark.parametrize("tool_calls", [[], [{"name": "run_shell"}]])
def test_invalid_native_grade_preserves_only_actual_terminal_reply(tmp_path, tool_calls):
    from evaluation.harbor.executor import HarborExecutor

    executor = HarborExecutor.__new__(HarborExecutor)
    executor.manifest = {"harnesses": [{"id": "claude", "kind": "harbor"}]}
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "trajectory.json").write_text(
        json.dumps({"steps": [{"source": "agent", "message": "Done", "tool_calls": tool_calls}]})
    )
    result = executor._invalid(
        {"trial_id": "one", "harness": "claude"},
        1,
        "Judge unavailable",
        tmp_path,
        outcome=OutcomeKind.GRADER_FAILURE,
        raw={"verifier_result": {"rewards": {"reward": 1}}},
        source_result=tmp_path / "result.json",
        rewards={"reward": 1},
    )
    assert result.terminal_reply is (not tool_calls)
    assert result.normal_reply is (not tool_calls)
    assert result.grader_reached and not result.valid_trial
