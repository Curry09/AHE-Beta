#!/usr/bin/env python3
"""Run one selected TUA-Bench task entirely in a Daytona sandbox."""

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
    upload_tree,
    user_simulator_model,
    write_controller_manifest,
)
from timeout_policy import (
    remote_command_timeout,
    resolve_task_timeouts,
    sandbox_ttl_minutes,
)

HERE = Path(__file__).resolve().parent
PREPARED = prepared_root(HERE)
TASK_ROOT = PREPARED / "controller-private/task-sources/tua-bench/tasks"
HARNESS = harness_archive_path(HERE)
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
PIVOT_PACKAGES = (
    "asciinema ca-certificates curl dbus-x11 fonts-liberation git libreoffice-calc "
    "python3 python3-uno python3-venv sudo tmux x11-utils xauth xdotool xvfb file"
)
EPUB_PACKAGES = (
    "at-spi2-core ca-certificates chromium curl dbus-x11 gir1.2-atspi-2.0 git "
    "libatk-adaptor python3 python3-pip python3-pyatspi python3-venv sudo tar tmux "
    "x11-utils xauth xdg-utils xvfb xz-utils"
)
CASES = {
    "010-pivot-product-revenue": {
        "cpu": 1,
        "memory": 2,
        "disk": 10,
        "apt": PIVOT_PACKAGES,
        "pip": "cssselect==1.3.0 formulas==1.3.1 lxml==5.4.0 openpyxl==3.1.5 pandas==2.3.2 pymupdf==1.26.4 pypdf==6.1.1 rapidfuzz==3.13.0 xmltodict==0.14.2",
        "setup": (
            "curl -fL --retry 3 --retry-delay 1 "
            "'https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/libreoffice_calc/51719eea-10bc-4246-a428-ac7c433dd4b3/BoomerangSales.xlsx' "
            "-o /app/BoomerangSales.xlsx"
        ),
        "followup": (
            "Before I accept this, reopen or programmatically inspect the saved workbook. "
            "Verify every revenue value uses retail price, quantity, and discount, and "
            "that Sheet2 is a correct per-product pivot summary. Fix and save in place."
        ),
    },
    "080-convert-novel-epub": {
        "cpu": 2,
        "memory": 4,
        "disk": 10,
        "apt": EPUB_PACKAGES,
        "pip": "cssselect==1.2.0 formulas==1.2.9 lxml==5.3.0 mutagen==1.47.0 openpyxl==3.1.5 pandas==2.2.3 pdfplumber==0.11.4 playwright==1.52.0 python-docx==1.1.2 pytesseract==0.3.13 PyYAML==6.0.2 rapidfuzz==3.10.1 tldextract==5.1.2 xmltodict==0.13.0",
        "setup": "sudo -u agent -E /opt/venv/bin/python /tmp/tua-env/build_setup.py",
        "followup": (
            "Before I accept this, validate the EPUB container, chapter order, title and "
            "readability against all source TXT chapters. Fix omissions or malformed "
            "metadata and leave one accepted filename in the requested directory."
        ),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=sorted(CASES))
    parser.add_argument(
        "--standard-input-only",
        action="store_true",
        help="send only the official benchmark instruction (no strict follow-up)",
    )
    parser.add_argument("--llm-user-simulator", action="store_true")
    args = parser.parse_args()
    if args.standard_input_only and args.llm_user_simulator:
        parser.error("--standard-input-only and --llm-user-simulator are mutually exclusive")
    task_name = args.task
    model = evaluation_model()
    simulator_model = user_simulator_model()
    case = CASES[task_name]
    task = TASK_ROOT / task_name
    timeouts = resolve_task_timeouts(task / "task.toml")
    daytona_key, model_key = credentials()
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    harness_label = harness_eval_label(HARNESS)
    run_dir = new_run_dir(
        HERE,
        f"tua-{task_name}-{safe_run_label(harness_label)}-{safe_run_label(model)}-daytona",
    )
    sandbox = None
    manifest = {
        "benchmark": "TUA-Bench",
        "task": task_name,
        "harness_archive_sha256": sha256_file(HARNESS),
        "harness_label": harness_label,
        "agent_model": model,
        "nexau_commit": NEXAU_COMMIT,
        "ag_ui_protocol": "0.1.22",
        "execution_location": "daytona",
        "grader_visibility": "uploaded only after agent exit",
        "input_mode": (
            "official-plus-llm-user-followup"
            if args.llm_user_simulator
            else "official-single-turn"
            if args.standard_input_only
            else "official-plus-strict-followup"
        ),
        "user_simulator_model": simulator_model if args.llm_user_simulator else None,
        "agent_timeout_seconds": timeouts.agent_seconds,
        "agent_timeout_source": timeouts.agent_source,
        "verifier_timeout_seconds": timeouts.verifier_seconds,
        "environment_build_timeout_seconds": timeouts.environment_build_seconds,
        "resource_note": (
            "080 official task requests 20GB; Daytona tier caps one sandbox at 10GB"
            if task_name == "080-convert-novel-epub"
            else "matches selected task resource ceiling"
        ),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image="ubuntu:24.04",
                resources=Resources(cpu=case["cpu"], memory=case["memory"], disk=case["disk"]),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(
                    timeouts.environment_build_seconds,
                    timeouts.agent_seconds,
                    timeouts.verifier_seconds,
                    minimum_minutes=90,
                ),
                labels={"purpose": "tua-agent-grader", "task": task_name},
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
        bootstrap = (
            "export DEBIAN_FRONTEND=noninteractive; apt-get update && "
            f"apt-get install -y --no-install-recommends {case['apt']} && "
            "rm -rf /var/lib/apt/lists/* && python3 -m venv --system-site-packages /opt/venv && "
            "/opt/venv/bin/pip install --no-cache-dir --upgrade pip && "
            f"/opt/venv/bin/pip install --no-cache-dir {case['pip']} && "
            "(id -u agent >/dev/null 2>&1 || useradd -m -s /bin/bash agent) && "
            "test -e /home/user || ln -s /home/agent /home/user && "
            "echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent && chmod 0440 /etc/sudoers.d/agent && "
            "mkdir -p /app /tmp/eval-output /tmp/tua-env /logs/verifier /logs/artifacts && "
            "python3 -m venv /app/.harness-venv && /app/.harness-venv/bin/pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' "
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}'"
        )
        code, out, err = exec_async_logged(sandbox, run_dir, "bootstrap", bootstrap, 2400)
        if code != 0:
            raise RuntimeError(f"bootstrap failed: {(out + err)[-3000:]}")
        if task_name == "080-convert-novel-epub":
            sandbox.fs.upload_file(str(task / "environment/build_setup.py"), "/tmp/tua-env/build_setup.py")
            sandbox.fs.upload_file(str(task / "environment/task_spec.json"), "/tmp/tua-env/task_spec.json")
        setup_code, setup_out, setup_err = exec_async_logged(
            sandbox,
            run_dir,
            "task-setup",
            case["setup"],
            timeouts.environment_build_seconds or 1800,
        )
        if setup_code != 0:
            raise RuntimeError(f"task setup failed: {(setup_out + setup_err)[-3000:]}")
        sandbox.fs.upload_file(str(HARNESS), "/tmp/harness.tar.gz")
        sandbox.fs.upload_file(str(HERE / "adapters/harness_v0/stdio.py"), "/app/stdio.py")
        sandbox.fs.upload_file(str(HERE / "adapters/harness_v0/harbor_driver.py"), "/app/harness_driver.py")
        sandbox.fs.upload_file(str(HERE / "adapters/harness_v0/llm_user_simulator.py"), "/app/llm_user_simulator.py")
        sandbox.fs.upload_file(str(task / "instruction.md"), "/app/instruction.md")
        if not args.standard_input_only and not args.llm_user_simulator:
            sandbox.fs.upload_file(case["followup"].encode(), "/app/followup.md")
        exec_logged(
            sandbox,
            run_dir,
            "agent-ready",
            "mkdir -p /app/harness-v0 && tar -xzf /tmp/harness.tar.gz -C /app/harness-v0 && "
            "chown -R agent:agent /app /home/agent /tmp/eval-output /logs",
            180,
        )
        followup_arg = (
            "--llm-user-simulator --user-simulator-output /tmp/eval-output/user-simulator.json "
            if args.llm_user_simulator
            else ""
            if args.standard_input_only
            else "--followup-file /app/followup.md "
        )
        code, stdout, stderr = exec_async_logged(
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
        manifest["agent_exit_code"] = code
        download_artifacts(sandbox, run_dir, ("harness-transcript.jsonl", "harness-stderr.log", "user-simulator.json"))
        if code != 0:
            raise RuntimeError(f"remote harness failed: {code}: {(stdout + stderr)[-3000:]}")

        # Hidden evaluator material enters the sandbox only after the harness exits.
        upload_tree(sandbox, task / "tests", "/tests")
        grader = sandbox.process.exec(
            "chmod +x /tests/test.sh && chown -R agent:agent /tests /logs && "
            "sudo -u agent -E env PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin bash /tests/test.sh",
            timeout=timeouts.verifier_seconds or 1800,
        )
        (run_dir / "grader.log").write_text(grader.result or "", encoding="utf-8")
        reward = float(sandbox.fs.download_file("/logs/verifier/reward.txt").decode().strip())
        passed = reward == 1.0
        manifest.update({"grader_exit_code": grader.exit_code, "reward": reward, "passed": passed, "controller_completed": True})
        (run_dir / "result.json").write_text(json.dumps({"reward": reward, "passed": passed}, indent=2) + "\n", encoding="utf-8")
        print(f"RESULT reward={reward} passed={passed}", flush=True)
        return 0 if passed else 2
    except Exception as exc:
        manifest.update({"controller_completed": False, "passed": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        print(f"RUN_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write_controller_manifest(run_dir, manifest)
        if sandbox is not None:
            try:
                client.delete(sandbox, timeout=180, wait=True)
                print(f"DELETED {sandbox.id}", flush=True)
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
