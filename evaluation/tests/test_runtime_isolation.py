"""Independent Python interpreters and public MCP clients respect task boundaries."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.benchmarks.harbor_index.profile import EnvironmentSupport


def test_driver_and_frozen_child_ignore_task_imports_but_shell_keeps_them(tmp_path):
    from evaluation.harness import stdio

    source = tmp_path / "source"
    source.mkdir()
    task_packages = tmp_path / "task-python-packages"
    task_packages.mkdir()
    (task_packages / "json.py").write_text("raise RuntimeError('foreign task package imported')")
    # The task's shell process must still see its original Python settings.
    (source / "entry.py").write_text(
        "import json, os, subprocess, sys\n"
        "for line in sys.stdin:\n"
        " request = json.loads(line)\n"
        " value = subprocess.check_output(['sh', '-c', 'printf %s \"$PYTHONPATH\"'], text=True)\n"
        " print(json.dumps({'type': 'reply', 'text': value}), flush=True)\n"
    )
    (tmp_path / "stdio.py").write_text(Path(stdio.__file__).read_text())
    (tmp_path / "process_runner.py").write_text(
        Path(stdio.__file__).with_name("process_runner.py").read_text()
    )
    text = (
        Path(stdio.__file__)
        .with_name("driver.py")
        .read_text()
        .replace("/opt/frozen-harness", str(tmp_path))
    )
    text = text.replace("/logs/agent", str(tmp_path / "logs"))
    (tmp_path / "driver.py").write_text(text)
    (tmp_path / "budget_protocol.py").write_text(
        Path(stdio.__file__).with_name("budget_protocol.py").read_text()
    )
    (tmp_path / "instruction.md").write_text("Do the task.")
    (tmp_path / "logs").mkdir()
    parent = dict(
        os.environ,
        PYTHONPATH=str(task_packages),
        PYTHONHOME=str(tmp_path / "nonexistent-python-home"),
        SANDBOX_WORK_DIR=str(source),
        LLM_MODEL="example",
        LLM_BASE_URL="https://example.invalid",
        LLM_API_KEY="unused",
        HARNESS_REQUEST_TIMEOUT_SEC="10",
    )
    from evaluation.harness.budget_protocol import TaskBudget

    parent.update(TaskBudget(10, "isolation-test").environment())
    subprocess.run(
        [sys.executable, "-E", "-s", "-u", str(tmp_path / "driver.py")],
        cwd=tmp_path,
        env=parent,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert (tmp_path / "logs/harness-reply.txt").read_text() == str(task_packages)


def test_gso_verifier_clears_import_settings_after_outer_shell_startup(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "json.py").write_text("raise RuntimeError('foreign package imported')")
    environment = SimpleNamespace(_verifier_environment=True, environment_name="gso-example")
    support = EnvironmentSupport(environment)
    # Test a compound command: cleanup must apply to the whole verifier script,
    # not just to the first command preceding a shell separator.
    command = (
        "true && "
        + sys.executable
        + " -c 'import json, os; print(json.dumps({k: os.environ.get(k) "
        'for k in ["PYTHONPATH", "PYTHONHOME", "TASK_SETTING"]}))\''
    )
    result = subprocess.run(
        ["bash", "-c", support.command(command)],
        env=dict(
            os.environ,
            PYTHONPATH=str(foreign),
            PYTHONHOME="/nonexistent-python-home",
            TASK_SETTING="kept",
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "PYTHONPATH": None,
        "PYTHONHOME": None,
        "TASK_SETTING": "kept",
    }
    environment._verifier_environment = False
    assert support.command(command) == command
    environment._verifier_environment = True
    environment.environment_name = "other-benchmark"
    assert support.command(command) == command


def test_mcp_public_client_is_uploaded_inside_workspace(tmp_path):
    environment = SimpleNamespace(exec=AsyncMock(), upload_file=AsyncMock())
    environment.exec.return_value = SimpleNamespace(return_code=0)
    support = EnvironmentSupport(environment)
    support.are = object()
    workspace = tmp_path / "task with spaces"
    asyncio.run(support.prepare_mcp(str(workspace)))
    _, target = environment.upload_file.await_args.args
    assert Path(target).is_relative_to(workspace)
    assert Path(target).name == "client.py"
    assert "scenario" not in environment.upload_file.await_args.args[0].name
    instructions = support.mcp_instructions()
    assert target in instructions
    assert "/opt/harbor-mcp/client.py" not in instructions


def test_mcp_publication_failure_does_not_claim_ready_client():
    environment = SimpleNamespace(exec=AsyncMock(), upload_file=AsyncMock())
    environment.exec.return_value = SimpleNamespace(return_code=1)
    support = EnvironmentSupport(environment)
    support.are = object()
    with pytest.raises(RuntimeError, match="publish"):
        asyncio.run(support.prepare_mcp("/app"))
    with pytest.raises(RuntimeError, match="not been published"):
        support.mcp_instructions()
    environment.upload_file.assert_not_awaited()
