#!/usr/bin/env python3
"""Run one historical persona-loop trial in a Daytona sandbox.

This is intentionally different from the public-bench pilot's one-turn
follow-up runner.  The harness and AgenticPersonaClient run in the same remote
workspace, preserving the local experiment's private read/run checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tarfile
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Image, Resources
from daytona import SessionExecuteRequest

ROOT = Path(__file__).resolve().parents[3]
AUTO = ROOT / "auto-designer"
HARNESS = (
    ROOT
    / "auto-designer-experiment-configs/harness-mixed16-20260916-strict-goal-r3/launch/harness-v0.tar.gz"
)
FIXTURE = AUTO / "backend/seed_workspaces/billing-split/project"
REMOTE_RUNNER = Path(__file__).with_name("remote_historical_billing.py")
OUT = Path(__file__).parent / "runs"


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def archive_dir(source: Path, name: str) -> Path:
    target = Path(tempfile.mkdtemp(prefix="hse-")) / name
    with tarfile.open(target, "w:gz") as archive:
        archive.add(source, arcname=source.name)
    return target


def wait_command(box, session_id: str, command_id: str, timeout: int) -> tuple[int, str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = box.process.get_session_command(session_id, command_id)
        if current.exit_code is not None:
            logs = box.process.get_session_command_logs(session_id, command_id)
            return int(current.exit_code), logs.stdout or "", logs.stderr or ""
        time.sleep(4)
    raise TimeoutError(f"remote command exceeded {timeout}s")


def main() -> int:
    key = os.environ.get("DAYTONA_API_KEY", "").strip()
    if not key:
        raise SystemExit("DAYTONA_API_KEY is required; export it without committing it")
    if not HARNESS.is_file() or not FIXTURE.is_dir():
        raise SystemExit("missing pinned harness archive or billing fixture")

    model_env = env_file(AUTO / "backend/.env")
    # The historical internal endpoint is only resolvable from the local
    # evaluation network.  Daytona runs on a separate network, so use the
    # configured public OpenRouter fallback when available; the harness and
    # persona protocol remain unchanged.
    root_env = env_file(ROOT / ".env") if (ROOT / ".env").is_file() else {}
    if root_env.get("openrouter_api_key"):
        model_env.update(
            {
                "HARNESS_LLM_API_KEY": root_env["openrouter_api_key"],
                "HARNESS_LLM_BASE_URL": "https://openrouter.ai/api/v1",
                "HARNESS_LLM_MODEL": "z-ai/glm-5.2",
                "USER_LLM_API_KEY": root_env["openrouter_api_key"],
                "USER_LLM_BASE_URL": "https://openrouter.ai/api/v1",
                # Keep the user-simulator model aligned with the prior paper
                # runs; DS4 Flash is more reliable on the strict JSON action
                # envelope than using the coding model for both roles.
                "USER_LLM_MODEL": "deepseek/deepseek-v4-flash",
            }
        )
    daytona = Daytona(DaytonaConfig(api_key=key))
    run_dir = OUT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-billing-historical")
    run_dir.mkdir(parents=True, exist_ok=False)
    # The pinned harness is already a tarball; wrapping it would leave the
    # archive itself under /opt/harness instead of extracting its files.
    harness_tgz = HARNESS
    fixture_tgz = archive_dir(FIXTURE, "project.tar.gz")
    backend_tgz = archive_dir(AUTO / "backend/auto_designer", "auto_designer.tar.gz")
    box = None
    manifest = {
        "suite": "harness-suite-20260920",
        "task_id": "billing-split-historical-mechanism-smoke",
        "harness_archive_sha256": hashlib.sha256(HARNESS.read_bytes()).hexdigest(),
        "execution": "daytona",
        "mechanism": "historical_agentic_persona_shared_workspace",
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        base = Image.base("swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest")
        runtime_image = base.run_commands(
            "curl -fL --retry 3 "
            "'https://github.com/astral-sh/python-build-standalone/releases/download/20260814/"
            "cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' "
            "-o /tmp/python312.tar.gz && "
            "echo '5acfa3e9ba26b51ae161c83aff278da915b590d22373a424b2ba55b8afe91fcc  /tmp/python312.tar.gz' "
            "| sha256sum -c - && tar -xzf /tmp/python312.tar.gz -C /opt && "
            "/opt/python/bin/python3 -m venv /opt/harness-venv && "
            "/opt/harness-venv/bin/pip install --no-cache-dir "
            "ag-ui-protocol==0.1.22 openai python-dotenv ruamel.yaml requests "
            "'git+https://github.com/nex-agi/NexAU.git@09e747b59e3684d5541d557087d6d93790c5a43f' && "
            "rm -f /tmp/python312.tar.gz"
        )
        box = daytona.create(
            CreateSandboxFromImageParams(
                image=runtime_image,
                resources=Resources(cpu=2, memory=8, disk=10),
                ephemeral=True,
                ttl_minutes=45,
                labels={"purpose": "historical-persona-smoke", "task": "billing-split"},
                env_vars={
                    "LLM_API_KEY": model_env.get("HARNESS_LLM_API_KEY", ""),
                    "LLM_BASE_URL": model_env.get("HARNESS_LLM_BASE_URL", ""),
                    "LLM_MODEL": model_env.get("HARNESS_LLM_MODEL", ""),
                    "USER_LLM_API_KEY": model_env.get("USER_LLM_API_KEY", ""),
                    "USER_LLM_BASE_URL": model_env.get("USER_LLM_BASE_URL", ""),
                    "USER_LLM_MODEL": model_env.get("USER_LLM_MODEL", ""),
                    "PYTHONUNBUFFERED": "1",
                    "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
                },
            ),
            timeout=1200,
        )
        manifest["sandbox_id"] = box.id
        for local, remote in (
            (harness_tgz, "/tmp/harness.tar.gz"),
            (fixture_tgz, "/tmp/project.tar.gz"),
            (backend_tgz, "/tmp/auto_designer.tar.gz"),
            (REMOTE_RUNNER, "/tmp/remote_historical_billing.py"),
        ):
            box.fs.upload_file(str(local), remote)
        setup = (
            "mkdir -p /opt/harness /opt/auto-designer/backend /testbed /tmp/eval-output && "
            "tar -xzf /tmp/harness.tar.gz -C /opt/harness && "
            "tar -xzf /tmp/auto_designer.tar.gz -C /opt/auto-designer/backend && "
            "tar -xzf /tmp/project.tar.gz -C /testbed --strip-components=1 && "
            "cd /testbed && git init -q && git add . && git -c user.email=smoke@example.invalid "
            "-c user.name=smoke commit -qm baseline"
        )
        setup_result = box.process.exec(setup, timeout=120)
        (run_dir / "setup.log").write_text(setup_result.result or "", encoding="utf-8")
        if setup_result.exit_code != 0:
            raise RuntimeError(f"sandbox setup failed: {setup_result.result}")

        session_id = "historical-persona-smoke"
        box.process.create_session(session_id)
        started = box.process.execute_session_command(
            session_id,
            SessionExecuteRequest(
                command="PYTHONPATH=/opt/auto-designer/backend /opt/harness-venv/bin/python -u /tmp/remote_historical_billing.py",
                run_async=True,
            ),
            timeout=60,
        )
        code, stdout, stderr = wait_command(box, session_id, started.cmd_id, 2400)
        (run_dir / "remote-stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "remote-stderr.log").write_text(stderr, encoding="utf-8")
        for name in ("result.json", "model.patch"):
            probe = box.process.exec(f"test -f /tmp/eval-output/{shlex.quote(name)}", timeout=30)
            if probe.exit_code == 0:
                box.fs.download_file(f"/tmp/eval-output/{name}", str(run_dir / name))
        manifest["remote_exit_code"] = code
        manifest["passed"] = code == 0
        if code != 0:
            raise RuntimeError(f"historical remote runner failed with exit code {code}")
        print(f"RUN_DIR {run_dir}")
        print(f"RESULT {run_dir / 'result.json'}")
        return 0
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        (run_dir / "controller-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if box is not None:
            try:
                daytona.delete(box, timeout=180, wait=True)
                print(f"DELETED_SANDBOX {box.id}")
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
