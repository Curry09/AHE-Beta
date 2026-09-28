#!/usr/bin/env python3
"""Run one selected SWE-bench Verified case with a fresh Daytona grader."""

from __future__ import annotations

import argparse
import json
import traceback
from datetime import UTC, datetime
from pathlib import Path

from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Image, Resources
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
HARNESS = harness_archive_path(HERE)
PREPARED = prepared_root(HERE)
DATASET = PREPARED / "controller-private/swe-bench-verified-full.jsonl"
OFFICIAL_EVAL_ROOT = (
    HERE.parents[2]
    / "auto-designer-experiments/glm52fp8-spec-anchoring-e2e-20260830/logs/run_evaluation"
    / "spec-anchor-incumbent/incumbent"
)
NEXAU_COMMIT = "09e747b59e3684d5541d557087d6d93790c5a43f"
CASES = {
    "astropy__astropy-12907": {
        "image": "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest",
        "followup": (
            "Before I accept this, test all nested CompoundModel association forms, "
            "including equivalent parenthesizations, and confirm existing separability "
            "tests still pass. Fix anything missing and report concrete results."
        ),
    },
    "django__django-15957": {
        "image": "swebench/sweb.eval.x86_64.django_1776_django-15957:latest",
        "followup": (
            "Before I accept this, verify sliced Prefetch querysets for forward and "
            "reverse many-to-many and reverse foreign keys, including offsets and "
            "ordering. Run the focused regression suite and fix any failure."
        ),
    },
}


def dataset_row(instance_id: str) -> dict:
    matches = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("instance_id") == instance_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one dataset row for {instance_id}, got {len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance_id", choices=sorted(CASES))
    parser.add_argument(
        "--standard-input-only",
        action="store_true",
        help="send only the official benchmark problem statement (no strict follow-up)",
    )
    parser.add_argument("--llm-user-simulator", action="store_true")
    args = parser.parse_args()
    if args.standard_input_only and args.llm_user_simulator:
        parser.error("--standard-input-only and --llm-user-simulator are mutually exclusive")
    instance_id = args.instance_id
    case = CASES[instance_id]
    timeouts = resolve_task_timeouts()
    model = evaluation_model()
    simulator_model = user_simulator_model()
    row = dataset_row(instance_id)
    eval_script = OFFICIAL_EVAL_ROOT / instance_id / "eval.sh"
    if not eval_script.is_file():
        raise SystemExit(f"missing official generated eval script: {eval_script}")
    daytona_key, model_key = credentials()
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    harness_label = harness_eval_label(HARNESS)
    run_dir = new_run_dir(
        HERE,
        f"swe-{instance_id}-{safe_run_label(harness_label)}-{safe_run_label(model)}-daytona",
    )
    agent_box = grader_box = None
    manifest = {
        "benchmark": "SWE-bench Verified",
        "instance_id": instance_id,
        "image": case["image"],
        "base_commit": row["base_commit"],
        "harness_archive_sha256": sha256_file(HARNESS),
        "harness_label": harness_label,
        "agent_model": model,
        "nexau_commit": NEXAU_COMMIT,
        "ag_ui_protocol": "0.1.22",
        "execution_location": "daytona",
        "grader_mode": "fresh separate Daytona sandbox",
        "grader_script_provenance": "official SWE-bench generated eval.sh from prior pinned evaluation",
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
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        runtime_image = Image.base(case["image"]).run_commands(
            "curl -fL --retry 3 "
            "'https://github.com/astral-sh/python-build-standalone/releases/download/20260814/"
            "cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' "
            "-o /tmp/python312.tar.gz && "
            "echo '5acfa3e9ba26b51ae161c83aff278da915b590d22373a424b2ba55b8afe91fcc  /tmp/python312.tar.gz' "
            "| sha256sum -c - && tar -xzf /tmp/python312.tar.gz -C /opt && "
            "/opt/python/bin/python3 -m venv /opt/harness-venv && "
            "/opt/harness-venv/bin/pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' "
            f"'git+https://github.com/nex-agi/NexAU.git@{NEXAU_COMMIT}' && "
            "rm -f /tmp/python312.tar.gz"
        )
        agent_box = client.create(
            CreateSandboxFromImageParams(
                image=runtime_image,
                resources=Resources(cpu=2, memory=6, disk=10),
                ephemeral=True,
                ttl_minutes=sandbox_ttl_minutes(timeouts.agent_seconds, minimum_minutes=60),
                labels={"purpose": "swe-agent", "instance": instance_id},
                env_vars={
                    "LLM_API_KEY": model_key,
                    "LLM_BASE_URL": "https://openrouter.ai/api/v1",
                    "LLM_MODEL": model,
                    "USER_SIMULATOR_MODEL": simulator_model,
                    "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
                    "PYTHONUNBUFFERED": "1",
                    "PATH": "/opt/miniconda3/envs/testbed/bin:/opt/miniconda3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                },
            ),
            timeout=1200,
        )
        manifest["agent_sandbox_id"] = agent_box.id
        exec_logged(agent_box, run_dir, "agent-init", "mkdir -p /opt/harness /tmp/eval-output", 60)
        agent_box.fs.upload_file(str(HARNESS), "/tmp/harness.tar.gz")
        agent_box.fs.upload_file(str(HERE / "adapters/harness_v0/stdio.py"), "/tmp/stdio.py")
        agent_box.fs.upload_file(
            str(HERE / "adapters/harness_v0/harbor_driver.py"), "/tmp/harness_driver.py"
        )
        agent_box.fs.upload_file(
            str(HERE / "adapters/harness_v0/llm_user_simulator.py"), "/tmp/llm_user_simulator.py"
        )
        agent_box.fs.upload_file(row["problem_statement"].encode(), "/tmp/instruction.md")
        if not args.standard_input_only and not args.llm_user_simulator:
            agent_box.fs.upload_file(case["followup"].encode(), "/tmp/followup.md")
        exec_logged(
            agent_box,
            run_dir,
            "harness-unpack",
            "tar -xzf /tmp/harness.tar.gz -C /opt/harness",
            120,
        )
        followup_arg = (
            "--llm-user-simulator --user-simulator-output /tmp/eval-output/user-simulator.json "
            if args.llm_user_simulator
            else ""
            if args.standard_input_only
            else "--followup-file /tmp/followup.md "
        )
        code, stdout, stderr = exec_async_logged(
            agent_box,
            run_dir,
            "agent",
            "/opt/harness-venv/bin/python -u /tmp/harness_driver.py "
            "--python /opt/harness-venv/bin/python --harness-dir /opt/harness "
            "--work-dir /testbed --instruction-file /tmp/instruction.md "
            f"{followup_arg}--transcript /tmp/eval-output/harness-transcript.jsonl "
            "--stderr /tmp/eval-output/harness-stderr.log "
            f"--timeout {timeouts.agent_seconds}",
            remote_command_timeout(timeouts.agent_seconds),
        )
        manifest["agent_exit_code"] = code
        download_artifacts(
            agent_box,
            run_dir,
            ("harness-transcript.jsonl", "harness-stderr.log", "user-simulator.json"),
        )
        if code != 0:
            raise RuntimeError(f"remote harness failed: {code}: {(stdout + stderr)[-3000:]}")
        patch = agent_box.process.exec("git -C /testbed diff --binary", timeout=120).result or ""
        (run_dir / "model.patch").write_text(patch, encoding="utf-8")
        manifest["model_patch_bytes"] = len(patch.encode())
        if not patch.strip():
            raise RuntimeError("harness produced no repository patch")
        client.delete(agent_box, timeout=180, wait=True)
        manifest["agent_sandbox_deleted"] = True
        agent_box = None

        grader_box = client.create(
            CreateSandboxFromImageParams(
                image=case["image"],
                resources=Resources(cpu=2, memory=6, disk=10),
                ephemeral=True,
                ttl_minutes=30,
                labels={"purpose": "swe-grader", "instance": instance_id},
            ),
            timeout=900,
        )
        manifest["grader_sandbox_id"] = grader_box.id
        grader_box.fs.upload_file(str(run_dir / "model.patch"), "/tmp/model.patch")
        grader_box.fs.upload_file(str(eval_script), "/tmp/eval.sh")
        apply_result = grader_box.process.exec(
            "cd /testbed && git apply /tmp/model.patch", timeout=120
        )
        (run_dir / "grader-apply.log").write_text(apply_result.result or "", encoding="utf-8")
        if apply_result.exit_code != 0:
            raise RuntimeError(f"model patch did not apply in fresh grader: {apply_result.result}")
        grader = grader_box.process.exec("chmod +x /tmp/eval.sh && bash /tmp/eval.sh", timeout=1800)
        grader_output = grader.result or ""
        (run_dir / "grader.log").write_text(grader_output, encoding="utf-8")
        marker = ">>>>> Test Exit Code: 0"
        resolved = marker in grader_output
        manifest.update(
            {
                "grader_process_exit_code": grader.exit_code,
                "official_test_exit_code": 0 if resolved else None,
                "passed": resolved,
                "controller_completed": True,
                "fail_to_pass_total": len(json.loads(row["FAIL_TO_PASS"])),
                "pass_to_pass_total": len(json.loads(row["PASS_TO_PASS"])),
            }
        )
        (run_dir / "result.json").write_text(
            json.dumps({"reward": int(resolved), "passed": resolved}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"RESULT reward={int(resolved)} passed={resolved}", flush=True)
        return 0 if resolved else 2
    except Exception as exc:
        manifest.update(
            {
                "controller_completed": False,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
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
                    print(
                        f"{label.upper()}_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True
                    )


if __name__ == "__main__":
    raise SystemExit(main())
