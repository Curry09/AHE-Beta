#!/usr/bin/env python3
"""Run one TUA task end-to-end in Daytona without local Harbor/Docker."""

from __future__ import annotations

import argparse
import json
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
    prepared_root,
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
TASK_NAME = "106-create-charles-ssh-user"
TASK = prepared_root(HERE) / "controller-private/task-sources/tua-bench/tasks" / TASK_NAME
HARNESS = harness_archive_path(HERE)
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
STRICT_FOLLOWUP = (
    "Before I accept this, verify every requested account property yourself: the "
    "login shell, password authentication, exact home path, ownership, and write "
    "permission. Fix anything missing and report concrete checks."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-user-simulator", action="store_true")
    args = parser.parse_args()
    timeouts = resolve_task_timeouts(TASK / "task.toml")
    daytona_key, model_key = credentials()
    model = evaluation_model()
    simulator_model = user_simulator_model()
    harness_label = harness_eval_label(HARNESS)
    run_dir = new_run_dir(
        HERE,
        f"tua-{TASK_NAME}-{safe_run_label(harness_label)}-{safe_run_label(model)}-daytona",
    )
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    sandbox = None
    manifest = {
        "benchmark": "TUA-Bench",
        "task": TASK_NAME,
        "harness_archive_sha256": sha256_file(HARNESS),
        "harness_label": harness_label,
        "agent_model": model,
        "nexau_commit": NEXAU_COMMIT,
        "execution_location": "daytona",
        "grader_visibility": "uploaded only after agent exit",
        "input_mode": (
            "official-plus-llm-user-followup"
            if args.llm_user_simulator
            else "official-plus-strict-followup"
        ),
        "user_simulator_model": simulator_model if args.llm_user_simulator else None,
        "local_benchmark_dependencies": False,
        "agent_timeout_seconds": timeouts.agent_seconds,
        "agent_timeout_source": timeouts.agent_source,
        "verifier_timeout_seconds": timeouts.verifier_seconds,
        "environment_build_timeout_seconds": timeouts.environment_build_seconds,
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image="ubuntu:24.04",
                resources=Resources(cpu=2, memory=4, disk=10),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(
                    timeouts.environment_build_seconds,
                    timeouts.agent_seconds,
                    timeouts.verifier_seconds,
                    minimum_minutes=90,
                ),
                labels={"purpose": "tua-harness-v0-preflight", "task": TASK_NAME},
                env_vars={
                    "LLM_API_KEY": model_key,
                    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "LLM_MODEL": model,
                    "USER_SIMULATOR_MODEL": simulator_model,
                    "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
                    "PYTHONUNBUFFERED": "1",
                },
            ),
            timeout=900,
        )
        manifest["sandbox_id"] = sandbox.id
        print(f"CREATED {sandbox.id}", flush=True)

        exec_logged(
            sandbox,
            run_dir,
            "task-bootstrap",
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update && apt-get install -y --no-install-recommends "
            "ca-certificates curl expect git python3 python3-venv sudo "
            "&& python3 -m venv /opt/venv "
            "&& /opt/venv/bin/pip install --no-cache-dir --upgrade pip "
            "&& /opt/venv/bin/pip install --no-cache-dir pytest==8.4.1 "
            "&& (id -u agent >/dev/null 2>&1 || useradd -m -s /bin/bash agent) "
            "&& echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent "
            "&& chmod 0440 /etc/sudoers.d/agent "
            "&& mkdir -p /app/.osworld /home/test1 /tmp/eval-output "
            "&& chown -R agent:agent /app /home/agent /tmp/eval-output "
            "&& curl -fsSL --retry 3 --retry-delay 1 "
            "'https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/os/5812b315-e7bd-4265-b51f-863c02174c28/check_password.sh' "
            "-o /app/.osworld/check_password.sh "
            "&& chmod +x /app/.osworld/check_password.sh "
            "&& chown -R agent:agent /app",
            1800,
        )
        exec_logged(
            sandbox,
            run_dir,
            "harness-install",
            "sudo -u agent python3 -m venv /app/.harness-venv "
            "&& sudo -u agent /app/.harness-venv/bin/pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' "
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}' "
            "&& sudo -u agent mkdir -p /app/harness-v0",
            1800,
        )

        sandbox.fs.upload_file(str(HARNESS), "/tmp/harness-v0.tar.gz")
        sandbox.fs.upload_file(str(HERE / "adapters/harness_v0/stdio.py"), "/app/stdio.py")
        sandbox.fs.upload_file(
            str(HERE / "adapters/harness_v0/harbor_driver.py"),
            "/app/harness_driver.py",
        )
        sandbox.fs.upload_file(
            str(HERE / "adapters/harness_v0/llm_user_simulator.py"),
            "/app/llm_user_simulator.py",
        )
        sandbox.fs.upload_file(str(TASK / "instruction.md"), "/app/instruction.md")
        if not args.llm_user_simulator:
            sandbox.fs.upload_file(STRICT_FOLLOWUP.encode(), "/app/followup.md")
        exec_logged(
            sandbox,
            run_dir,
            "harness-unpack",
            "tar -xzf /tmp/harness-v0.tar.gz -C /app/harness-v0 "
            "&& chown -R agent:agent /app/harness-v0 /app/stdio.py "
            "/app/harness_driver.py /app/llm_user_simulator.py /app/instruction.md "
            + ("" if args.llm_user_simulator else "/app/followup.md"),
            120,
        )
        followup_arg = (
            "--llm-user-simulator --user-simulator-output /tmp/eval-output/user-simulator.json "
            if args.llm_user_simulator
            else "--followup-file /app/followup.md "
        )
        agent_exit_code, agent_stdout, agent_stderr = exec_async_logged(
            sandbox,
            run_dir,
            "agent",
            "sudo -u agent -E /app/.harness-venv/bin/python -u /app/harness_driver.py "
            "--python /app/.harness-venv/bin/python --harness-dir /app/harness-v0 "
            f"--work-dir /app --instruction-file /app/instruction.md {followup_arg}"
            "--transcript /tmp/eval-output/harness-transcript.jsonl "
            "--stderr /tmp/eval-output/harness-stderr.log "
            f"--timeout {timeouts.agent_seconds}",
            remote_command_timeout(timeouts.agent_seconds),
        )
        manifest["agent_exit_code"] = agent_exit_code
        download_artifacts(
            sandbox,
            run_dir,
            ("harness-transcript.jsonl", "harness-stderr.log", "user-simulator.json"),
        )
        if agent_exit_code != 0:
            raise RuntimeError(
                f"remote harness failed: {agent_exit_code}: {(agent_stdout + agent_stderr)[-2000:]}"
            )

        # The verifier stays outside the agent-visible filesystem until now.
        sandbox.process.exec("mkdir -p /tests /logs/verifier /logs/artifacts", timeout=30)
        sandbox.fs.upload_file(str(TASK / "tests/test_outputs.py"), "/tests/test_outputs.py")
        sandbox.fs.upload_file(str(TASK / "tests/test.sh"), "/tests/test.sh")
        grader = sandbox.process.exec(
            "chmod +x /tests/test.sh "
            "&& chown -R agent:agent /tests /logs "
            "&& cd /tmp "
            "&& sudo -u agent -E env PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin "
            "bash /tests/test.sh",
            timeout=timeouts.verifier_seconds or 1800,
        )
        (run_dir / "grader.log").write_text(grader.result or "", encoding="utf-8")
        reward_raw = sandbox.fs.download_file("/logs/verifier/reward.txt")
        reward = int(reward_raw.decode().strip())
        manifest.update(
            {
                "grader_exit_code": grader.exit_code,
                "reward": reward,
                "passed": grader.exit_code == 0 and reward == 1,
                "controller_completed": True,
            }
        )
        download_artifacts(
            sandbox,
            run_dir,
            ("harness-transcript.jsonl", "harness-stderr.log"),
        )
        account_state = sandbox.fs.download_file("/logs/artifacts/account_state.txt")
        (run_dir / "account_state.txt").write_bytes(account_state)
        (run_dir / "result.json").write_text(
            json.dumps({"reward": reward, "passed": manifest["passed"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"RESULT reward={reward} passed={manifest['passed']}", flush=True)
        return 0 if manifest["passed"] else 2
    except Exception as exc:
        manifest["controller_completed"] = False
        manifest["passed"] = False
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
