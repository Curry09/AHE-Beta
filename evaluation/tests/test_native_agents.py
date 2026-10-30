"""Native agents use the same task, grading, and recovery contracts."""

import asyncio
import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.config import HarborEvaluationPlan, PlanError
from evaluation.harbor.contracts import resolve_contract
from evaluation.harbor.job import job_config
from evaluation.manifest import freeze_manifest
from evaluation.tests.test_execution import payload, task


def native_plan(root):
    raw = payload(task(root))
    raw["harnesses"] = [
        {
            "id": "claude-code",
            "kind": "harbor",
            "agent": "claude-code",
            "version": "2.1.119",
            "kwargs": {"reasoning_effort": "max"},
        }
    ]
    raw["models"] = {"harness": "glm-5.3-flash"}
    return raw


def test_native_manifest_and_job_need_no_archived_runtime(tmp_path, monkeypatch):
    from evaluation.harbor import processes

    runtime = {"python_archive": "python312.tar.gz", "python_sha256": "a" * 64}
    monkeypatch.setattr(processes, "prepare_process_runtime", lambda: runtime)
    plan = HarborEvaluationPlan.from_mapping(native_plan(tmp_path), tmp_path / "plan.json")
    manifest = freeze_manifest(
        plan, framework_commit="test", resolved_cases={"Harbor/smoke": resolve_contract(tmp_path)}
    )
    assert len(manifest["trials"]) == 1
    identity = manifest["harnesses"][0]
    assert identity["process_runtime"] == runtime
    assert {k: v for k, v in identity.items() if k != "process_runtime"} == asdict(
        plan.harnesses[0]
    )
    config = job_config(manifest, manifest["trials"][0], tmp_path / "jobs", "test")
    agent = config["agents"][0]
    assert agent["kwargs"] == {
        "version": "2.1.119",
        "reasoning_effort": "max",
        "process_runtime": identity["process_runtime"],
    }
    assert agent["model_name"] == "glm-5.3-flash"
    assert "override_timeout_sec" not in agent
    assert "override_setup_timeout_sec" not in agent
    assert "override_cpus" not in config["environment"]
    assert config["timeout_multiplier"] == 1
    assert config["retry"]["max_retries"] == 0
    assert config["verifier"]["env"]["ANTHROPIC_API_KEY"] == "${JUDGE_ANTHROPIC_API_KEY}"
    from evaluation.harbor.agents import ClaudeCodeAgent

    ClaudeCodeAgent.preflight(agent["kwargs"], agent["env"])


def test_native_preflight_keeps_strict_cli_options():
    from evaluation.harbor.agents import ClaudeCodeAgent

    with pytest.raises(ValueError, match="Unknown option"):
        ClaudeCodeAgent.preflight({"process_runtime": None, "unknown_cli_option": True})
    with pytest.raises(ValueError, match="runtime descriptor"):
        ClaudeCodeAgent.preflight({"process_runtime": {"python_archive": "missing checksum"}})


@pytest.mark.parametrize(
    "change",
    [
        {"version": "latest"},
        {"version": "stable"},
        {"kind": "unknown"},
        {"archive": "unused"},
        {"kwargs": {"override_timeout_sec": 99999}},
        {"kwargs": {"env": {"ANTHROPIC_API_KEY": "secret"}}},
    ],
)
def test_native_contract_cannot_float_or_override_task(tmp_path, change):
    raw = native_plan(tmp_path)
    raw["harnesses"][0].update(change)
    with pytest.raises(PlanError):
        HarborEvaluationPlan.from_mapping(raw, tmp_path / "plan.json")


def test_native_mcp_bridge_preserves_official_tool_response(monkeypatch):
    from evaluation.benchmarks.harbor_index.support import mcp_stdio_client as module

    calls = []

    def forward(tool, arguments):
        calls.append((tool, arguments))
        return {"isError": False, "content": [{"type": "text", "text": "official response"}]}

    monkeypatch.setattr(module, "forward", forward)
    requests = [
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"method": "notifications/initialized"},
        {"id": 2, "method": "tools/call", "params": {"name": "public_tool", "arguments": {"x": 1}}},
    ]
    monkeypatch.setattr(module.sys, "stdin", io.StringIO("\n".join(map(json.dumps, requests))))
    output = io.StringIO()
    monkeypatch.setattr(module.sys, "stdout", output)
    module.main()
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(replies) == 2
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert replies[1]["result"]["content"][0]["text"] == "official response"
    assert calls == [("public_tool", {"x": 1})]


def test_native_agent_collects_are_before_verifier_even_when_cancelled(tmp_path, monkeypatch):
    from evaluation.harbor.agents import ClaudeCodeAgent

    agent = ClaudeCodeAgent(logs_dir=tmp_path, model_name="glm-5.3-flash", version="2.1.119")
    agent.mcp_servers = ["original"]
    support = SimpleNamespace(mcp_ready=True, native_mcp_servers=AsyncMock(return_value=["mapped"]))
    environment = SimpleNamespace(support=support, finish_mcp=AsyncMock())
    run = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr("harbor.agents.installed.claude_code.ClaudeCode.run", run)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run("unchanged official prompt", environment, None))
    assert agent.mcp_servers == ["mapped"]
    run.assert_awaited_once_with("unchanged official prompt", environment, None)
    environment.finish_mcp.assert_awaited_once()


def test_native_runtime_does_not_suppress_harbor_trajectory_backfill(tmp_path, monkeypatch):
    from harbor.models.agent.context import AgentContext

    from evaluation.harbor.agents import ClaudeCodeAgent

    agent = ClaudeCodeAgent(logs_dir=tmp_path, model_name="glm-5.3-flash", version="2.1.119")
    agent._process_owner = SimpleNamespace(sha="pinned-runtime")
    context = AgentContext()
    run = AsyncMock()
    monkeypatch.setattr("harbor.agents.installed.claude_code.ClaudeCode.run", run)
    environment = SimpleNamespace(support=None)
    asyncio.run(agent.run("original instruction", environment, context))
    # Harbor only calls populate_context_post_run for an empty context.
    assert context.is_empty()
    run.assert_awaited_once_with("original instruction", environment, context)


def test_native_terminal_reply_is_read_from_official_trajectory(tmp_path):
    from evaluation.harbor.executor import HarborExecutor

    executor = HarborExecutor.__new__(HarborExecutor)
    executor.manifest = {"harnesses": [{"id": "claude", "kind": "harbor"}]}
    agent = tmp_path / "agent"
    agent.mkdir()
    trajectory = agent / "trajectory.json"
    trajectory.write_text(json.dumps({"steps": [{"source": "agent", "message": "Done."}]}))
    result = executor._result(
        {"trial_id": "one", "harness": "claude"}, 1, {}, {"reward": 1}, tmp_path / "result.json"
    )
    assert result.normal_reply and result.terminal_reply and result.passed
    trajectory.write_text(
        json.dumps({"steps": [{"source": "agent", "message": "Working", "tool_calls": [{}]}]})
    )
    result = executor._result(
        {"trial_id": "one", "harness": "claude"}, 1, {}, {"reward": 0}, tmp_path / "result.json"
    )
    assert not result.terminal_reply
