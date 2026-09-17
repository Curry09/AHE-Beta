#!/usr/bin/env python3
"""Run tau3 task + user simulator entirely inside one Daytona sandbox."""

from __future__ import annotations

from datetime import datetime, timezone
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
HARNESS = Path(
    os.environ.get("HARNESS_V0_ARCHIVE", HERE / "artifacts/harness-v0-cade14d.tar.gz")
)
TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
MODEL = "openrouter/z-ai/glm-5.2"


def main() -> int:
    daytona_key, model_key = credentials()
    run_dir = new_run_dir(HERE, "tau3-airline-7-harnessv0-daytona")
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    sandbox = None
    manifest = {
        "benchmark": "tau3-bench Core/Text",
        "source_commit": TAU_COMMIT,
        "nexau_commit": NEXAU_COMMIT,
        "task": "airline/7",
        "execution_location": "daytona",
        "local_benchmark_dependencies": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image="python:3.12-slim-bookworm",
                resources=Resources(cpu=2, memory=8, disk=10),
                ephemeral=True,
                ttl_minutes=90,
                labels={"purpose": "tau3-harness-v0-preflight"},
                env_vars={
                    "OPENROUTER_API_KEY": model_key,
                    "LLM_API_KEY": model_key,
                    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "LLM_MODEL": "z-ai/glm-5.2",
                    "AGENT_LLM": MODEL,
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

        exec_logged(
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
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}'",
            1800,
        )
        exec_logged(
            sandbox,
            run_dir,
            "version-check",
            "/opt/tau-venv/bin/python -c \"import tau2; print(tau2.__file__)\" "
            "&& /opt/harness-venv/bin/python -c \"import nexau; print(nexau.__file__)\"",
            120,
        )
        response = sandbox.process.exec(
            "/opt/tau-venv/bin/python -u /opt/pilot/remote_tau3_runner.py "
            "--domain airline --task-id 7 --seed 17 --max-steps 40",
            timeout=3600,
        )
        (run_dir / "remote-runner.log").write_text(
            response.result or "", encoding="utf-8"
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
        if response.exit_code != 0:
            raise RuntimeError(f"remote tau3 runner failed: {response.exit_code}")
        manifest["controller_completed"] = True
        return 0
    except Exception as exc:
        manifest["controller_completed"] = False
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
