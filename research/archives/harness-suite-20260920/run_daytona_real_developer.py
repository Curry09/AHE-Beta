#!/usr/bin/env python3
"""Start one real OpenAgents/vigil developer worker inside Daytona."""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from daytona import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    Image,
    Resources,
    SessionExecuteRequest,
)

ROOT = Path(__file__).resolve().parents[3]
OPENAGENTS = ROOT / "OpenAgents"
CLAUDE = Path("/root/.local/share/claude/versions/2.1.261")
REMOTE = Path(__file__).with_name("remote_real_developer_smoke.py")
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
    target = Path(tempfile.mkdtemp(prefix="hse-oa-")) / name
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
    if not OPENAGENTS.is_dir() or not CLAUDE.is_file():
        raise SystemExit("OpenAgents checkout or Claude binary is missing")
    wis = env_file(ROOT / ".env")
    if not wis.get("wis_base_url") or not wis.get("wis_api_key"):
        raise SystemExit("WIS endpoint/key missing from root .env")
    if not wis.get("openrouter_api_key"):
        raise SystemExit("OpenRouter fallback key missing from root .env")

    run_dir = OUT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-real-developer")
    run_dir.mkdir(parents=True, exist_ok=False)
    oa_tgz = archive_dir(OPENAGENTS, "openagents.tar.gz")
    manifest = {
        "suite": "harness-suite-20260920",
        "task_id": "real-openagents-developer-smoke",
        "execution": "daytona",
        "owner_mode": "mechanical_review_false_before_worker",
        "openagents_sha": os.popen(f"git -C {OPENAGENTS} rev-parse HEAD").read().strip(),
        "claude_version": "2.1.261",
        "started_at": datetime.now(UTC).isoformat(),
    }
    box = None
    daytona = Daytona(DaytonaConfig(api_key=key))
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
            "/opt/harness-venv/bin/pip install --no-cache-dir requests ruamel.yaml jsonschema argcomplete && "
            "curl -fL --retry 3 'https://dl.gitea.com/gitea/1.22.6/gitea-1.22.6-linux-amd64' "
            "-o /tmp/gitea-bin && chmod 755 /tmp/gitea-bin && rm -f /tmp/python312.tar.gz"
        )
        box = daytona.create(
            CreateSandboxFromImageParams(
                image=runtime_image,
                resources=Resources(cpu=2, memory=8, disk=10),
                ephemeral=True,
                ttl_minutes=60,
                labels={"purpose": "real-developer-smoke", "owner_mode": "mechanical"},
                env_vars={
                    "WIS_BASE_URL": wis["wis_base_url"],
                    "WIS_API_KEY": wis["wis_api_key"],
                    # The WIS hostname resets connections from Daytona's
                    # egress IP. OpenRouter exposes the same Anthropic
                    # contract and is reachable from the sandbox, so use it
                    # only for this remote smoke while retaining WIS for the
                    # local harness experiments.
                    "MODEL_BASE_URL": "https://openrouter.ai/api",
                    "MODEL_API_KEY": wis["openrouter_api_key"],
                    "ANTHROPIC_MODEL": "anthropic/claude-sonnet-4.6",
                    "ANTHROPIC_SMALL_FAST_MODEL": "anthropic/claude-sonnet-4.6",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "anthropic/claude-sonnet-4.6",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "anthropic/claude-sonnet-4.6",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "anthropic/claude-sonnet-4.6",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32768",
                    "PYTHONUNBUFFERED": "1",
                },
            ),
            timeout=1200,
        )
        manifest["sandbox_id"] = box.id
        box.fs.upload_file(str(oa_tgz), "/tmp/openagents.tar.gz")
        box.fs.upload_file(str(REMOTE), "/tmp/remote_real_developer_smoke.py")
        box.fs.upload_file(str(CLAUDE), "/tmp/claude-bin")
        setup = (
            "mkdir -p /opt/claude-bin && cp /tmp/claude-bin /opt/claude-bin/claude && chmod 755 /opt/claude-bin/claude && "
            "tar -xzf /tmp/openagents.tar.gz -C /tmp && "
            "/opt/harness-venv/bin/pip install --no-cache-dir /tmp/OpenAgents"
        )
        setup_result = box.process.exec(setup, timeout=300)
        (run_dir / "setup.log").write_text(setup_result.result or "", encoding="utf-8")
        if setup_result.exit_code != 0:
            raise RuntimeError(f"developer setup failed: {setup_result.result}")
        sid = "real-developer-smoke"
        box.process.create_session(sid)
        started = box.process.execute_session_command(
            sid,
            SessionExecuteRequest(
                command="/opt/harness-venv/bin/python -u /tmp/remote_real_developer_smoke.py",
                run_async=True,
            ),
            timeout=60,
        )
        code, stdout, stderr = wait_command(box, sid, started.cmd_id, 1800)
        (run_dir / "remote-stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "remote-stderr.log").write_text(stderr, encoding="utf-8")
        for name in (
            "real-developer.json",
            "developer-stdout.log",
            "developer-stderr.log",
            "gitea.log",
            "model-probe.log",
        ):
            probe = box.process.exec(f"test -f /tmp/eval-output/{name}", timeout=30)
            if probe.exit_code == 0:
                box.fs.download_file(f"/tmp/eval-output/{name}", str(run_dir / name))
        manifest["remote_exit_code"] = code
        manifest["passed"] = code == 0
        if code != 0:
            raise RuntimeError(f"real developer runner failed with exit code {code}")
        print(f"RUN_DIR {run_dir}")
        print(f"RESULT {run_dir / 'real-developer.json'}")
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
