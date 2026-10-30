"""Transport and isolation invariants for the reply-only simulated-user track."""

import json
import os
import subprocess
import sys
import time

import pytest

from evaluation.config import InteractionSpec, PlanError
from evaluation.harness.agent import PACKAGE
from evaluation.tests.test_stdio import FAKE_HARNESS


def wait_json(path, proc, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        if proc.poll() is not None:
            raise AssertionError(proc.stderr.read().decode())
        time.sleep(0.02)
    raise AssertionError(f"No relay record {path}")


def start_relay(tmp_path, budget):
    fake = tmp_path / "entry.py"
    fake.write_text(FAKE_HARNESS)
    root = tmp_path / "relay"
    env = {
        **os.environ,
        "SIM_ENTRY": str(fake),
        "SIM_SOURCE": str(tmp_path),
        "SIM_RELAY_ROOT": str(root),
        "SIM_LOG_ROOT": str(tmp_path),
        "HARNESS_REQUEST_TIMEOUT_SEC": str(budget),
        "SANDBOX_WORK_DIR": str(tmp_path),
        "LLM_MODEL": "fake",
        "LLM_BASE_URL": "https://example.invalid",
        "LLM_API_KEY": "fake",
    }
    from evaluation.harness.budget_protocol import TaskBudget

    env.update(TaskBudget(budget, "relay-test").environment())
    proc = subprocess.Popen(
        [sys.executable, str(PACKAGE / "sim_driver.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wait_json(root / "ready.json", proc)
    return root, proc


def test_relay_keeps_conversation_and_closes_before_collection(tmp_path):
    root, proc = start_relay(tmp_path, 10)
    try:
        for n, text in enumerate(("original", "follow up")):
            (root / f"request-{n}.json").write_text(json.dumps({"text": text}))
            assert wait_json(root / f"reply-{n}.json", proc)["text"] == f"reply:{text}:{n + 1}"
        (root / "stop.json").write_text("{}")
        record = wait_json(root / "closed.json", proc)
        assert record["request_count"] == 2
        assert record["normal_reply"]
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_user_deliberation_consumes_shared_deadline(tmp_path):
    root, proc = start_relay(tmp_path, 0.8)
    try:
        (root / "request-0.json").write_text(json.dumps({"text": "one"}))
        wait_json(root / "reply-0.json", proc)
        # No further request: time spent by the external user must still expire the actor.
        record = wait_json(root / "closed.json", proc)
        assert record["termination_reason"] == "TimeoutError"
        assert record["request_count"] == 1
        assert record["elapsed_seconds"] < 3
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_only_explicit_versioned_policy_is_accepted():
    spec = InteractionSpec.from_mapping(
        {
            "mode": "simulated_user",
            "policy": "reply_then_followup_v1",
            "user_model": "glm-5.3-flash",
            "persona": "python-competent-feedback-v1",
        },
        0,
    )
    assert spec.mode.value == "simulated_user"
    with pytest.raises(PlanError):
        InteractionSpec.from_mapping({"mode": "simulated_user"}, 0)


def test_reply_only_space_excludes_inflight_actions():
    from auto_designer.user.sim.actions import Phase
    from evaluation.harness.sim_worker import _reply_only_space

    assert _reply_only_space(Phase.ACTIVE, None, None) == [
        "accept",
        "accept_with_reservations",
        "file_issue",
        "give_up",
        "send_message",
    ]


def test_host_accepts_large_audit_frames_and_keeps_credentials_private(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    from types import SimpleNamespace

    from e2b.exceptions import NotFoundException
    from harbor.environments.base import ExecResult

    from evaluation.harness import sim_agent

    (tmp_path / "sim_worker.py").write_text("""
import json, os, sys
assert 'USER_LLM_API_KEY' in os.environ
assert os.environ.get('ALL_PROXY') == 'socks5://127.0.0.1:9'
assert 'E2B_API_KEY' not in os.environ
assert 'LLM_API_KEY' not in os.environ
def emit(obj): print(json.dumps(obj),flush=True)
config=json.loads(sys.stdin.readline())
emit({'type':'progress','result':{'audit':'x'*100000}})
emit({'type':'request','text':config['task']})
reply=json.loads(sys.stdin.readline())
assert 'Public workspace inspection' in reply['text']
emit({'type':'freeze'})
assert json.loads(sys.stdin.readline())['frozen']
emit({'type':'result','result':{'evaluation_status':'valid','end_reason':'accept','experience':{'score':3}}})
""")
    monkeypatch.setattr(sim_agent, "PACKAGE", tmp_path)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("USER_LLM_API_KEY", "private-user-key")
    monkeypatch.setenv("USER_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("E2B_API_KEY", "must-not-enter-user-process")
    material = tmp_path / "material"
    material.write_bytes(b"material")
    digest = hashlib.sha256(b"material").hexdigest()
    agent = sim_agent.SimulatedUserHarnessAgent(
        archive=str(material),
        archive_sha256=digest,
        revision="pinned",
        runtime_wheel=str(material),
        runtime_sha256=digest,
        runtime_lock=str(material),
        runtime_lock_sha256=digest,
        python_archive=str(material),
        python_sha256=digest,
        workdir="/public",
        request_timeout_sec=5,
        logs_dir=tmp_path,
        interaction={"user_model": "fake", "policy": "reply_then_followup_v1"},
    )
    from evaluation.harness.budget_protocol import TaskBudget

    agent._task_budget = TaskBudget(5, "audit-frame-test")
    (tmp_path / "public-instruction.md").write_text("public task")

    async def exercise():
        data = {sim_agent.RELAY + "/ready.json": json.dumps({"ready": True})}
        ended = asyncio.Event()

        class Files:
            async def read(self, path, **kwargs):
                if path not in data:
                    raise NotFoundException("missing")
                return data[path]

            async def write(self, path, text, **kwargs):
                data[path] = text

        class Commands:
            async def run(self, command, **kwargs):
                assert "USER_LLM_API_KEY" not in kwargs["envs"]

                async def wait():
                    await ended.wait()
                    return SimpleNamespace(exit_code=0)

                return SimpleNamespace(wait=wait, pid=123)

        async def execute(command, **kwargs):
            if "then mv -- " in command:
                import shlex

                move = command.split("then mv -- ", 1)[1].split("; else", 1)[0]
                _, _, source, target = shlex.split("mv -- " + move)
                data[target] = data.pop(source)
                if target.endswith("request-0.json"):
                    assert json.loads(data[target])["text"] == "public task"
                    data[sim_agent.RELAY + "/reply-0.json"] = json.dumps(
                        {"text": "done", "failed": False}
                    )
                if target.endswith("stop.json"):
                    data[sim_agent.RELAY + "/closed.json"] = "{}"
                    ended.set()
            return ExecResult(return_code=0, stdout="public candidate diff")

        environment = SimpleNamespace(
            _sandbox=SimpleNamespace(files=Files(), commands=Commands()),
            _merge_env=lambda env: env,
            _resolve_user=lambda user: "root",
            exec=execute,
            support=None,
        )
        return await agent.execute_driver(
            environment, "owned-driver", env={"LLM_API_KEY": "actor-key"}, cwd="/public"
        )

    assert asyncio.run(exercise()).return_code == 0
    result = json.loads((tmp_path / "user-session-result.json").read_text())
    assert result["workspace_frozen"]
    assert result["result"]["evaluation_status"] == "valid"
    assert result["harness_requests"] == 1


def test_blocking_wait_is_counted_once_in_user_history(monkeypatch):
    import importlib.util
    import sys

    from auto_designer.user.sim.dimensions import (
        D1Eval,
        D2Domain,
        D5Autonomy,
        D41Grain,
        D42Supervise,
        D43Correct,
        Persona,
        finalize_persona,
    )
    from auto_designer.user.sim.persona_client import ScriptedPersonaClient
    from evaluation.harness import agent

    module_name = "auto_designer.user.sim._frozen_evaluation_loop"
    path = agent.PACKAGE / "user_engine/auto_designer/user/sim/loop.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    sim_loop = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, sim_loop)
    spec.loader.exec_module(sim_loop)

    elapsed = [0.0]
    monkeypatch.setattr(sim_loop.time, "monotonic", lambda: elapsed[0])
    histories = []

    def decide(**kwargs):
        histories.append(list(kwargs["history"]))
        first = len(histories) == 1
        return (
            {
                "action": "send_message" if first else "accept",
                "message": "fix public task" if first else "",
                "verdict": "unsure" if first else "satisfied",
            },
            [],
            "proceed",
            False,
        )

    monkeypatch.setattr(sim_loop, "_main_decide", decide)
    monkeypatch.setattr(sim_loop, "_narrate_terminal", lambda **kwargs: None)

    class Harness:
        def send(self, text):
            elapsed[0] += 600
            return "completed"

    persona = finalize_persona(
        Persona(
            "test",
            D1Eval.COMPETENT,
            D2Domain(),
            D41Grain.SPEC_LEVEL,
            D42Supervise.PHASE_CHECK,
            D43Correct.FEEDBACK,
            D5Autonomy.COLLABORATIVE,
        )
    )
    result = sim_loop.run_session(
        persona, ScriptedPersonaClient(), Harness(), "fix public task", deadline_seconds=1200
    )
    assert result.end_reason == "accepted"
    assert any(line.startswith("[+600s] harness -> you:") for line in histories[1])
    assert not any("[+1200s]" in line for line in histories[1])
