#!/usr/bin/env python3
"""Run tau3 task + user simulator entirely inside one Daytona sandbox."""

from __future__ import annotations

import argparse
import os
import shlex
import traceback
from datetime import UTC, datetime
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Resources
from daytona_common import (
    credentials,
    download_artifacts,
    evaluation_model,
    exec_async_logged,
    exec_logged,
    harness_archive_path,
    harness_eval_label,
    new_run_dir,
    openrouter_litellm_model,
    safe_run_label,
    sha256_file,
    user_simulator_model,
    write_controller_manifest,
)
from timeout_policy import (
    remote_command_timeout,
    resolve_task_timeouts,
    sandbox_ttl_minutes,
)

HERE = Path(__file__).resolve().parent
HARNESS = harness_archive_path(HERE)
TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="airline")
    parser.add_argument("--task-id", default="7")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-steps", type=int, default=40)
    args = parser.parse_args()
    timeouts = resolve_task_timeouts()
    agent_model = evaluation_model()
    simulator_model = user_simulator_model()
    agent_llm = openrouter_litellm_model(agent_model)
    simulator_llm = openrouter_litellm_model(simulator_model)
    daytona_key, model_key = credentials()
    safe_task = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.task_id)[:80]
    harness_label = harness_eval_label(HARNESS)
    run_dir = new_run_dir(
        HERE,
        f"tau3-{args.domain}-{safe_task}-{safe_run_label(harness_label)}-{safe_run_label(agent_model)}-daytona",
    )
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    sandbox = None
    manifest = {
        "benchmark": "tau3-bench Core/Text",
        "source_commit": TAU_COMMIT,
        "nexau_commit": NEXAU_COMMIT,
        "ag_ui_protocol": "0.1.22",
        "task": f"{args.domain}/{args.task_id}",
        "nl_judge_model": "openrouter/openai/gpt-4.1",
        "seed": args.seed,
        "max_steps": args.max_steps,
        "harness_archive_sha256": sha256_file(HARNESS),
        "harness_label": harness_label,
        "agent_model": agent_model,
        "user_simulator_model": simulator_model,
        "execution_location": "daytona",
        "local_benchmark_dependencies": False,
        "agent_timeout_seconds": timeouts.agent_seconds,
        "agent_timeout_source": timeouts.agent_source,
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image="python:3.12-slim-bookworm",
                resources=Resources(cpu=2, memory=6, disk=10),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(
                    1800, timeouts.agent_seconds, minimum_minutes=90
                ),
                labels={"purpose": "tau3-harness-v0-preflight", "domain": args.domain},
                env_vars={
                    "OPENROUTER_API_KEY": model_key,
                    "LLM_API_KEY": model_key,
                    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "LLM_MODEL": agent_model,
                    "AGENT_LLM": agent_llm,
                    "USER_SIMULATOR_LLM": simulator_llm,
                    "NL_JUDGE_LLM": "openrouter/openai/gpt-4.1",
                    "HARNESS_AGENT_LABEL": harness_label,
                    "HARNESS_V0_ARTIFACT_DIR": "/tmp/eval-output",
                    "TAU2_DATA_DIR": "/opt/tau2-bench/data",
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONPATH": "/opt/pilot",
                },
            ),
            timeout=900,
        )
        manifest["sandbox_id"] = sandbox.id
        print(f"CREATED {sandbox.id}", flush=True)
        sandbox.process.exec("mkdir -p /opt/pilot", timeout=30)
        sandbox.fs.upload_file(str(HARNESS), "/opt/pilot/harness-v0.tar.gz")
        sandbox.fs.upload_file(str(HERE / "remote_tau3_runner.py"), "/opt/pilot/remote_tau3_runner.py")
        for path in sorted((HERE / "adapters").rglob("*.py")):
            remote = "/opt/pilot/" + str(path.relative_to(HERE))
            parent = os.path.dirname(remote)
            sandbox.process.exec(f"mkdir -p {parent}", timeout=30)
            sandbox.fs.upload_file(str(path), remote)

        bootstrap_exit, bootstrap_stdout, bootstrap_stderr = exec_async_logged(
            sandbox,
            run_dir,
            "bootstrap",
            "apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates "
            "&& rm -rf /var/lib/apt/lists/* "
            f"&& curl -fsSL --retry 3 'https://github.com/sierra-research/tau2-bench/archive/{TAU_COMMIT}.tar.gz' -o /tmp/tau3.tar.gz "
            "&& mkdir -p /opt/tau2-bench "
            "&& tar -xzf /tmp/tau3.tar.gz -C /opt/tau2-bench --strip-components=1 "
            "&& python3 -m venv /opt/tau-venv "
            "&& /opt/tau-venv/bin/pip install --no-cache-dir "
            "-e /opt/tau2-bench "
            "&& python3 -m venv /opt/harness-venv "
            "&& /opt/harness-venv/bin/pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' "
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}'",
            1800,
        )
        if bootstrap_exit != 0:
            raise RuntimeError(
                f"remote bootstrap failed: {bootstrap_exit}: "
                f"{(bootstrap_stdout + bootstrap_stderr)[-3000:]}"
            )
        exec_logged(
            sandbox,
            run_dir,
            "version-check",
            "/opt/tau-venv/bin/python -c \"import tau2; print(tau2.__file__)\" "
            "&& /opt/harness-venv/bin/python -c \"import nexau; print(nexau.__file__)\"",
            120,
        )
        agent_exit, agent_stdout, agent_stderr = exec_async_logged(
            sandbox,
            run_dir,
            "tau-run",
            "/opt/tau-venv/bin/python -u /opt/pilot/remote_tau3_runner.py "
            f"--domain {shlex.quote(args.domain)} --task-id {shlex.quote(args.task_id)} "
            f"--seed {args.seed} --max-steps {args.max_steps} "
            f"--timeout {timeouts.agent_seconds}",
            remote_command_timeout(timeouts.agent_seconds),
        )
        download_artifacts(
            sandbox,
            run_dir,
            (
                "manifest.json",
                "simulation.json",
                "adapter-turns.json",
                "harness-transcript.jsonl",
                "harness-stderr.log",
            ),
        )
        manifest["agent_exit_code"] = agent_exit
        if agent_exit != 0:
            raise RuntimeError(
                f"remote tau3 runner failed: {agent_exit}: "
                f"{(agent_stdout + agent_stderr)[-3000:]}"
            )
        manifest["controller_completed"] = True
        return 0
    except Exception as exc:
        manifest["controller_completed"] = False
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        manifest["traceback"] = traceback.format_exc()
        print(f"RUN_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write_controller_manifest(run_dir, manifest)
        if sandbox is not None:
            try:
                client.delete(sandbox, timeout=120, wait=True)
                print(f"DELETED {sandbox.id}", flush=True)
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
