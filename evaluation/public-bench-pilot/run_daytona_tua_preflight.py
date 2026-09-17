#!/usr/bin/env python3
"""Run one TUA task end-to-end in Daytona without local Harbor/Docker."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import traceback

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Resources

from daytona_common import (
    credentials,
    download_artifacts,
    exec_logged,
    new_run_dir,
    write_controller_manifest,
)


HERE = Path(__file__).resolve().parent
TASK_NAME = "106-create-charles-ssh-user"
TASK = (
    HERE
    / "prepared/controller-private/task-sources/tua-bench/tasks"
    / TASK_NAME
)
HARNESS = Path(
    os.environ.get("HARNESS_V0_ARCHIVE", HERE / "artifacts/harness-v0-cade14d.tar.gz")
)
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
STRICT_FOLLOWUP = (
    "Before I accept this, verify every requested account property yourself: the "
    "login shell, password authentication, exact home path, ownership, and write "
    "permission. Fix anything missing and report concrete checks."
)


def main() -> int:
    daytona_key, model_key = credentials()
    run_dir = new_run_dir(HERE, f"tua-{TASK_NAME}-harnessv0-daytona")
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    sandbox = None
    manifest = {
        "benchmark": "TUA-Bench",
        "task": TASK_NAME,
        "nexau_commit": NEXAU_COMMIT,
        "execution_location": "daytona",
        "grader_visibility": "uploaded only after agent exit",
        "local_benchmark_dependencies": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image="ubuntu:24.04",
                resources=Resources(cpu=2, memory=4, disk=10),
                ephemeral=True,
                ttl_minutes=90,
                labels={"purpose": "tua-harness-v0-preflight", "task": TASK_NAME},
                env_vars={
                    "LLM_API_KEY": model_key,
                    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "LLM_MODEL": "z-ai/glm-5.2",
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
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}' "
            "&& sudo -u agent mkdir -p /app/harness-v0",
            1800,
        )

        sandbox.fs.upload_file(str(HARNESS), "/tmp/harness-v0.tar.gz")
        sandbox.fs.upload_file(
            str(HERE / "adapters/harness_v0/stdio.py"), "/app/stdio.py"
        )
        sandbox.fs.upload_file(
            str(HERE / "adapters/harness_v0/harbor_driver.py"),
            "/app/harness_driver.py",
        )
        sandbox.fs.upload_file(str(TASK / "instruction.md"), "/app/instruction.md")
        sandbox.fs.upload_file(STRICT_FOLLOWUP.encode(), "/app/followup.md")
        exec_logged(
            sandbox,
            run_dir,
            "harness-unpack",
            "tar -xzf /tmp/harness-v0.tar.gz -C /app/harness-v0 "
            "&& chown -R agent:agent /app/harness-v0 /app/stdio.py "
            "/app/harness_driver.py /app/instruction.md /app/followup.md",
            120,
        )
        response = sandbox.process.exec(
            "sudo -u agent -E /app/.harness-venv/bin/python -u /app/harness_driver.py "
            "--python /app/.harness-venv/bin/python --harness-dir /app/harness-v0 "
            "--work-dir /app --instruction-file /app/instruction.md "
            "--followup-file /app/followup.md "
            "--transcript /tmp/eval-output/harness-transcript.jsonl "
            "--stderr /tmp/eval-output/harness-stderr.log --timeout 360",
            timeout=900,
        )
        (run_dir / "remote-agent.log").write_text(
            response.result or "", encoding="utf-8"
        )
        manifest["agent_exit_code"] = response.exit_code
        if response.exit_code != 0:
            raise RuntimeError(f"remote harness failed: {response.exit_code}")

        # The verifier stays outside the agent-visible filesystem until now.
        sandbox.process.exec("mkdir -p /tests /logs/verifier /logs/artifacts", timeout=30)
        sandbox.fs.upload_file(
            str(TASK / "tests/test_outputs.py"), "/tests/test_outputs.py"
        )
        sandbox.fs.upload_file(str(TASK / "tests/test.sh"), "/tests/test.sh")
        grader = sandbox.process.exec(
            "chmod +x /tests/test.sh "
            "&& chown -R agent:agent /tests /logs "
            "&& cd /tmp "
            "&& sudo -u agent -E env PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin "
            "bash /tests/test.sh",
            timeout=600,
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
            json.dumps(
                {"reward": reward, "passed": manifest["passed"]}, indent=2
            )
            + "\n",
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
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_controller_manifest(run_dir, manifest)
        if sandbox is not None:
            try:
                client.delete(sandbox, timeout=120, wait=True)
                print(f"DELETED {sandbox.id}", flush=True)
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
