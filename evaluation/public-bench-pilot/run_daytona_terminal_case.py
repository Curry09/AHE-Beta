#!/usr/bin/env python3
"""Run one selected Terminal-Bench 4.0 task in Daytona with a fresh grader."""

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
TASK_ROOT = PREPARED / "controller-private/task-sources/terminal-bench-4.0/tasks"
HARNESS = harness_archive_path(HERE)
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
CASES = {
    "music-harmony": {
        "agent_image": "python:3.12-slim-bookworm",
        "agent_bootstrap": "apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*",
        "agent_fixture": ("environment/data", "/app"),
        "artifacts": ["harmony.mxl"],
        "followup": (
            "Before I accept this, inspect all SATB voices against the supplied bass, "
            "check ranges, spacing, forbidden parallels, tendency-tone resolution, "
            "and MusicXML readability. Fix any issue and leave /app/harmony.mxl."
        ),
        "grader_image": "python:3.11-slim",
        "grader_bootstrap": "pip install --no-cache-dir music21==7.3.3 && mkdir -p /tests /app /logs/verifier",
    },
    "production-planning": {
        "agent_image": "python:3.13-slim-bookworm",
        "agent_bootstrap": "apt-get update && apt-get install -y --no-install-recommends bash git ca-certificates && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir pyyaml==6.0.2",
        "agent_fixture": ("environment/data", "/app/data"),
        "artifacts": ["output/erp_writeback.sql", "output/mes_writeback.sql", "output/wms_writeback.sql"],
        "followup": (
            "Before I accept this, replay-check all three writeback files against the "
            "ERP, MES, and WMS constraints, including capacities, inventory, dates, "
            "and cross-database consistency. Fix all issues and leave only executable SQL."
        ),
        "grader_image": "python:3.13-slim-bookworm",
        "grader_bootstrap": "pip install --no-cache-dir pytest==9.1.1 pyyaml==6.0.2 pytest-json-ctrf==0.5.2 && mkdir -p /tests /app/output /logs/verifier",
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
        f"terminal-{task_name}-{safe_run_label(harness_label)}-{safe_run_label(model)}-daytona",
    )
    agent_box = grader_box = None
    manifest = {
        "benchmark": "Terminal-Bench 4.0",
        "task": task_name,
        "harness_archive_sha256": sha256_file(HARNESS),
        "harness_label": harness_label,
        "agent_model": model,
        "nexau_commit": NEXAU_COMMIT,
        "ag_ui_protocol": "0.1.22",
        "execution_location": "daytona",
        "grader_mode": "fresh separate Daytona sandbox",
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
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        agent_box = client.create(
            CreateSandboxFromImageParams(
                image=case["agent_image"],
                resources=Resources(cpu=2, memory=4, disk=10),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(
                    timeouts.environment_build_seconds,
                    timeouts.agent_seconds,
                    minimum_minutes=60,
                ),
                labels={"purpose": "terminal-agent", "task": task_name},
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
        manifest["agent_sandbox_id"] = agent_box.id
        exec_logged(
            agent_box,
            run_dir,
            "agent-bootstrap",
            case["agent_bootstrap"] + " && pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' "
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}' "
            "&& mkdir -p /app/harness-v0 /tmp/eval-output",
            1800,
        )
        fixture_from, fixture_to = case["agent_fixture"]
        upload_tree(agent_box, task / fixture_from, fixture_to)
        if task_name == "production-planning":
            exec_logged(agent_box, run_dir, "fixture-permissions", "chmod +x /app/data/dbgw.py && mkdir -p /app/output", 60)
        agent_box.fs.upload_file(str(HARNESS), "/tmp/harness.tar.gz")
        agent_box.fs.upload_file(str(HERE / "adapters/harness_v0/stdio.py"), "/app/stdio.py")
        agent_box.fs.upload_file(str(HERE / "adapters/harness_v0/harbor_driver.py"), "/app/harness_driver.py")
        agent_box.fs.upload_file(str(HERE / "adapters/harness_v0/llm_user_simulator.py"), "/app/llm_user_simulator.py")
        agent_box.fs.upload_file(str(task / "instruction.md"), "/app/instruction.md")
        if not args.standard_input_only and not args.llm_user_simulator:
            agent_box.fs.upload_file(case["followup"].encode(), "/app/followup.md")
        exec_logged(agent_box, run_dir, "harness-unpack", "tar -xzf /tmp/harness.tar.gz -C /app/harness-v0", 120)
        followup_arg = (
            "--llm-user-simulator --user-simulator-output /tmp/eval-output/user-simulator.json "
            if args.llm_user_simulator
            else ""
            if args.standard_input_only
            else "--followup-file /app/followup.md "
        )
        code, stdout, stderr = exec_async_logged(
            agent_box,
            run_dir,
            "agent",
            "python -u /app/harness_driver.py --python /usr/local/bin/python "
            "--harness-dir /app/harness-v0 --work-dir /app --instruction-file /app/instruction.md "
            f"{followup_arg}--transcript /tmp/eval-output/harness-transcript.jsonl "
            "--stderr /tmp/eval-output/harness-stderr.log "
            f"--timeout {timeouts.agent_seconds}",
            remote_command_timeout(timeouts.agent_seconds),
        )
        manifest["agent_exit_code"] = code
        download_artifacts(agent_box, run_dir, ("harness-transcript.jsonl", "harness-stderr.log", "user-simulator.json"))
        if code != 0:
            raise RuntimeError(f"remote harness failed: {code}: {(stdout + stderr)[-3000:]}")
        missing = []
        for relative in case["artifacts"]:
            remote = f"/app/{relative}"
            if agent_box.process.exec(f"test -f {remote}", timeout=30).exit_code != 0:
                missing.append(relative)
                continue
            local = run_dir / "artifacts" / relative
            local.parent.mkdir(parents=True, exist_ok=True)
            agent_box.fs.download_file(remote, str(local))
        manifest["missing_artifacts"] = missing
        client.delete(agent_box, timeout=180, wait=True)
        manifest["agent_sandbox_deleted"] = True
        agent_box = None

        if missing:
            manifest.update({"controller_completed": True, "reward": 0, "passed": False})
            (run_dir / "result.json").write_text(json.dumps({"reward": 0, "passed": False, "missing_artifacts": missing}, indent=2) + "\n", encoding="utf-8")
            print(f"RESULT reward=0 passed=False missing={missing}", flush=True)
            return 2

        grader_box = client.create(
            CreateSandboxFromImageParams(
                image=case["grader_image"],
                resources=Resources(cpu=2, memory=4, disk=10),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(
                    timeouts.environment_build_seconds,
                    timeouts.verifier_seconds,
                    minimum_minutes=30,
                ),
                labels={"purpose": "terminal-grader", "task": task_name},
            ),
            timeout=900,
        )
        manifest["grader_sandbox_id"] = grader_box.id
        exec_logged(grader_box, run_dir, "grader-bootstrap", case["grader_bootstrap"], 1200)
        upload_tree(grader_box, task / "tests", "/tests")
        for relative in case["artifacts"]:
            grader_box.fs.upload_file(str(run_dir / "artifacts" / relative), f"/app/{relative}")
        grader = grader_box.process.exec(
            "chmod +x /tests/test.sh && cd /tmp && bash /tests/test.sh",
            timeout=timeouts.verifier_seconds or 1800,
        )
        (run_dir / "grader.log").write_text(grader.result or "", encoding="utf-8")
        reward = int(grader_box.fs.download_file("/logs/verifier/reward.txt").decode().strip())
        manifest.update({"grader_exit_code": grader.exit_code, "reward": reward, "passed": reward == 1, "controller_completed": True})
        (run_dir / "result.json").write_text(json.dumps({"reward": reward, "passed": reward == 1}, indent=2) + "\n", encoding="utf-8")
        print(f"RESULT reward={reward} passed={reward == 1}", flush=True)
        return 0 if reward == 1 else 2
    except Exception as exc:
        manifest.update({"controller_completed": False, "passed": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
        print(f"RUN_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write_controller_manifest(run_dir, manifest)
        for label, box in (("grader", grader_box), ("agent", agent_box)):
            if box is not None:
                try:
                    client.delete(box, timeout=180, wait=True)
                    print(f"DELETED_{label.upper()} {box.id}", flush=True)
                except Exception as exc:
                    print(f"{label.upper()}_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
