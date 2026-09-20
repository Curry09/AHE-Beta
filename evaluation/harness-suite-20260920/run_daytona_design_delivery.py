#!/usr/bin/env python3
"""Daytona smoke for design + historical mechanical Owner handoff."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Image, Resources
from daytona import SessionExecuteRequest

ROOT = Path(__file__).resolve().parents[3]
AUTO = ROOT / "auto-designer"
BACKEND = AUTO / "backend"
AGENT_DEFS = BACKEND / "agent_defs"
HARNESS_TEMPLATE = BACKEND / "harness_template"
REMOTE_RUNNER = Path(__file__).with_name("remote_design_delivery_smoke.py")
OUT = Path(__file__).parent / "runs"


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def archive_dir(source: Path, name: str) -> Path:
    target = Path(tempfile.mkdtemp(prefix="hse-role-")) / name
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
        raise SystemExit("DAYTONA_API_KEY is required")
    root_env = env_file(ROOT / ".env")
    openrouter_key = root_env.get("openrouter_api_key", "")
    if not openrouter_key:
        raise SystemExit("root .env has no OpenRouter fallback")

    run_dir = OUT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-design-delivery")
    run_dir.mkdir(parents=True, exist_ok=False)
    agents_tgz = archive_dir(AGENT_DEFS, "agent_defs.tar.gz")
    backend_tgz = archive_dir(BACKEND / "auto_designer", "auto_designer.tar.gz")
    harness_tgz = archive_dir(HARNESS_TEMPLATE, "harness_template.tar.gz")
    manifest = {
        "suite": "harness-suite-20260920",
        "task_id": "design-delivery-mechanical-owner-smoke",
        "execution": "daytona",
        "designer_model": "z-ai/glm-5.2",
        "owner_mode": "review_false_mechanical",
        "developer_stage": "handoff_preflight_only",
        "backend_sha256": hashlib.sha256((BACKEND / "auto_designer/__init__.py").read_bytes()).hexdigest(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    box = None
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
        box = Daytona(DaytonaConfig(api_key=key)).create(
            CreateSandboxFromImageParams(
                image=runtime_image,
                resources=Resources(cpu=2, memory=8, disk=10),
                ephemeral=True,
                ttl_minutes=45,
                labels={"purpose": "design-delivery-smoke", "owner_mode": "mechanical"},
                env_vars={
                    "DESIGNER_LLM_API_KEY": openrouter_key,
                    "DESIGNER_LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "DESIGNER_LLM_MODEL": "z-ai/glm-5.2",
                    "PYTHONUNBUFFERED": "1",
                },
            ),
            timeout=1200,
        )
        manifest["sandbox_id"] = box.id
        for local, remote in (
            (agents_tgz, "/tmp/agent_defs.tar.gz"),
            (backend_tgz, "/tmp/auto_designer.tar.gz"),
            (harness_tgz, "/tmp/harness_template.tar.gz"),
            (REMOTE_RUNNER, "/tmp/remote_design_delivery_smoke.py"),
        ):
            box.fs.upload_file(str(local), remote)
        setup = (
            "mkdir -p /opt/auto-designer/backend /opt/auto-designer/harness_repo /tmp/eval-output && "
            "tar -xzf /tmp/auto_designer.tar.gz -C /opt/auto-designer/backend && "
            "tar -xzf /tmp/agent_defs.tar.gz -C /opt/auto-designer/backend && "
            "tar -xzf /tmp/harness_template.tar.gz -C /opt/auto-designer/harness_repo --strip-components=1 && "
            "cd /opt/auto-designer/harness_repo && git init -q && git add . && "
            "git -c user.email=smoke@example.invalid -c user.name=smoke commit -qm baseline"
        )
        setup_result = box.process.exec(setup, timeout=120)
        (run_dir / "setup.log").write_text(setup_result.result or "", encoding="utf-8")
        if setup_result.exit_code != 0:
            raise RuntimeError(f"sandbox setup failed: {setup_result.result}")
        sid = "design-delivery-smoke"
        box.process.create_session(sid)
        started = box.process.execute_session_command(
            sid,
            SessionExecuteRequest(
                command="PYTHONPATH=/opt/auto-designer/backend /opt/harness-venv/bin/python -u /tmp/remote_design_delivery_smoke.py",
                run_async=True,
            ),
            timeout=60,
        )
        code, stdout, stderr = wait_command(box, sid, started.cmd_id, 2400)
        (run_dir / "remote-stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "remote-stderr.log").write_text(stderr, encoding="utf-8")
        probe = box.process.exec("test -f /tmp/eval-output/design-delivery.json", timeout=30)
        if probe.exit_code == 0:
            box.fs.download_file("/tmp/eval-output/design-delivery.json", str(run_dir / "design-delivery.json"))
        manifest["remote_exit_code"] = code
        manifest["passed"] = code == 0
        if code != 0:
            raise RuntimeError(f"design/delivery remote runner failed with exit code {code}")
        print(f"RUN_DIR {run_dir}")
        print(f"RESULT {run_dir / 'design-delivery.json'}")
        return 0
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        (run_dir / "controller-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if box is not None:
            try:
                Daytona(DaytonaConfig(api_key=key)).delete(box, timeout=180, wait=True)
                print(f"DELETED_SANDBOX {box.id}")
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
