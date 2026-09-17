#!/usr/bin/env python3
"""One-task Daytona smoke test for frozen harness v0.

The benchmark repository and grader test patch are kept separate: the harness sees
the clean SWE-bench task image, and the official regression patch is applied only
after the model patch has been captured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import re
import time
import traceback
from urllib.parse import urlsplit

from daytona import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    Image,
    Resources,
    SessionExecuteRequest,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARNESS_ARCHIVE = Path(
    os.environ.get("HARNESS_V0_ARCHIVE", HERE / "artifacts/harness-v0-cade14d.tar.gz")
)
IMAGE = "swebench/sweb.eval.x86_64.psf_1776_requests-6028:latest"
MODEL = "z-ai/glm-5.2"
INSTANCE_ID = "psf__requests-6028"
BASE_COMMIT = "0192aac24123735b3eaf9b08df46429bb770c283"
DATASET = HERE / "prepared/controller-private/swe-bench-verified-full.jsonl"

PROBLEM_STATEMENT = r"""Proxy authentication bug
<!-- Summary. -->

When using proxies in python 3.8.12, I get an error 407. Using any other version of python works fine. I am assuming it could be to do with this https://docs.python.org/3/whatsnew/3.8.html#notable-changes-in-python-3-8-12.

<!-- What you expected. -->

I should get a status of 200.

<!-- What happened instead. -->

I get a status code of 407.

```python
import requests

r = requests.get('https://example.org/', proxies=proxies)
print(r.status_code)
```

Additional investigation from the issue thread found that Requests 2.27.0 loses
`user:pwd` from the proxy netloc in `prepend_scheme_if_needed`; Requests 2.26.0
does not. Please fix the issue in the current repository and run relevant tests.
"""

STRICT_USER_FOLLOWUP = (
    "Before I accept this, verify the proxy-auth regression with tests and also "
    "confirm the ordinary no-auth URL cases still work. If anything is untested, "
    "run the smallest relevant test set now and report the concrete result."
)

TEST_PATCH = r"""diff --git a/tests/test_utils.py b/tests/test_utils.py
--- a/tests/test_utils.py
+++ b/tests/test_utils.py
@@ -602,6 +602,14 @@ def test_parse_header_links(value, expected):
         ('example.com/path', 'http://example.com/path'),
         ('//example.com/path', 'http://example.com/path'),
         ('example.com:80', 'http://example.com:80'),
+        (
+            'http://user:pass@example.com/path?query',
+            'http://user:pass@example.com/path?query'
+        ),
+        (
+            'http://user@example.com/path?query',
+            'http://user@example.com/path?query'
+        )
     ))
 def test_prepend_scheme_if_needed(value, expected):
     assert prepend_scheme_if_needed(value, 'http') == expected
"""


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def wait_for_replies(sandbox, session_id: str, command_id: str, count: int, timeout: float):
    deadline = time.monotonic() + timeout
    last_stdout = ""
    while time.monotonic() < deadline:
        logs = sandbox.process.get_session_command_logs(session_id, command_id)
        last_stdout = logs.stdout or ""
        events = []
        for line in last_stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        replies = [event for event in events if event.get("type") == "reply"]
        if len(replies) >= count:
            return events, replies
        command = sandbox.process.get_session_command(session_id, command_id)
        if command.exit_code is not None:
            raise RuntimeError(
                f"harness exited before reply {count}: exit={command.exit_code}; "
                f"stdout={last_stdout[-2000:]}"
            )
        time.sleep(2)
    raise TimeoutError(f"timed out waiting for harness reply {count}; stdout={last_stdout[-2000:]}")


def load_eval_targets() -> tuple[list[str], list[str]]:
    rows = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("instance_id") == INSTANCE_ID
    ]
    if len(rows) != 1:
        raise RuntimeError(f"expected one dataset row for {INSTANCE_ID}, got {len(rows)}")
    return json.loads(rows[0]["FAIL_TO_PASS"]), json.loads(rows[0]["PASS_TO_PASS"])


def parse_requests_pytest_log(log: str) -> dict[str, str]:
    """Mirror SWE-bench's parse_log_pytest_options for psf/requests."""
    option_pattern = re.compile(r"(.*?)\[(.*)\]")
    statuses = {"PASSED", "FAILED", "SKIPPED", "XFAIL", "XPASS", "ERROR"}
    result: dict[str, str] = {}
    for line in log.splitlines():
        parts = line.split()
        if len(parts) <= 1 or parts[0] not in statuses:
            continue
        match = option_pattern.search(parts[1])
        if match:
            main, option = match.groups()
            if option.startswith("/") and not option.startswith("//") and "*" not in option:
                option = "/" + option.split("/")[-1]
            name = f"{main}[{option}]"
        else:
            name = parts[1]
        result[name] = parts[0]
    return result


def score_targets(log: str, fail_to_pass: list[str], pass_to_pass: list[str]) -> dict:
    status_map = parse_requests_pytest_log(log)
    passing = {"PASSED", "XFAIL"}
    maintained = passing | {"SKIPPED"}
    failed_f2p = [name for name in fail_to_pass if status_map.get(name) not in passing]
    failed_p2p = [name for name in pass_to_pass if status_map.get(name) not in maintained]
    scored_names = set(fail_to_pass) | set(pass_to_pass)
    unrelated_errors = sorted(
        name for name, status in status_map.items()
        if status == "ERROR" and name not in scored_names
    )
    return {
        "fail_to_pass_total": len(fail_to_pass),
        "fail_to_pass_success": len(fail_to_pass) - len(failed_f2p),
        "fail_to_pass_failure": failed_f2p,
        "pass_to_pass_total": len(pass_to_pass),
        "pass_to_pass_success": len(pass_to_pass) - len(failed_p2p),
        "pass_to_pass_failure": failed_p2p,
        "unrelated_error_count": len(unrelated_errors),
        "unrelated_errors": unrelated_errors,
        "resolved": not failed_f2p and not failed_p2p,
    }


def main() -> int:
    root_env = load_env(ROOT / ".env")
    model_base = "https://openrouter.ai/api/v1"
    model_key = root_env.get("openrouter_api_key", "")
    if not model_base or not model_key:
        raise SystemExit("OPENROUTER_API_KEY is unavailable")
    model_host = urlsplit(model_base).hostname
    if not model_host:
        raise SystemExit("wis_base_url does not contain a valid hostname")
    if not HARNESS_ARCHIVE.is_file():
        raise SystemExit("frozen harness archive is missing")
    fail_to_pass, pass_to_pass = load_eval_targets()

    daytona_key = os.environ.get("DAYTONA_API_KEY") or getpass("Daytona API key: ")
    client = Daytona(DaytonaConfig(api_key=daytona_key))
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = HERE / "runs" / f"{run_stamp}-{INSTANCE_ID}-harnessv0"
    run_dir.mkdir(parents=True, exist_ok=False)

    sandbox = None
    grader_sandbox = None
    session_id = "harness-v0"
    command_id = None
    trace: list[dict] = []
    manifest = {
        "instance_id": INSTANCE_ID,
        "benchmark": "SWE-bench Verified",
        "image": IMAGE,
        "harness_archive_sha256": "dd7cdd91a4dc170af3662cdca28d2ed9fbd0dd2676e57ce9a4041146a488e011",
        "nexau_commit": "09e747b59e3684d5541d557087d6d93790c5a43f",
        "runtime_install_location": "daytona",
        "model": MODEL,
        "model_base_host": model_host,
        "model_route_note": "OpenRouter is used because Daytona Tier 1/2 blocks the original custom gateway domain.",
        "user_simulator": "deterministic-strict-followup-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
    }

    try:
        print(f"RUN_DIR {run_dir}", flush=True)
        print(f"CREATE image={IMAGE} with remote-built harness runtime", flush=True)
        runtime_image = Image.base(IMAGE).run_commands(
            "curl -fL --retry 3 "
            "'https://github.com/astral-sh/python-build-standalone/releases/download/20260814/"
            "cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' "
            "-o /tmp/python312.tar.gz && "
            "echo '5acfa3e9ba26b51ae161c83aff278da915b590d22373a424b2ba55b8afe91fcc  "
            "/tmp/python312.tar.gz' | sha256sum -c - && "
            "tar -xzf /tmp/python312.tar.gz -C /opt && "
            "/opt/python/bin/python3 -m venv /opt/harness-venv && "
            "/opt/harness-venv/bin/pip install --no-cache-dir "
            "'git+https://github.com/nex-agi/NexAU.git@09e747b59e3684d5541d557087d6d93790c5a43f' && "
            "rm -f /tmp/python312.tar.gz"
        )
        sandbox = client.create(
            CreateSandboxFromImageParams(
                image=runtime_image,
                resources=Resources(cpu=2, memory=8, disk=10),
                ephemeral=True,
                ttl_minutes=45,
                labels={"purpose": "harness-v0-smoke", "instance": INSTANCE_ID},
                env_vars={
                    "LLM_MODEL": MODEL,
                    "LLM_BASE_URL": model_base,
                    "LLM_API_KEY": model_key,
                    "SANDBOX_WORK_DIR": "/testbed",
                    "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
                    "PYTHONUNBUFFERED": "1",
                    "PATH": "/opt/miniconda3/envs/testbed/bin:/opt/miniconda3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                },
            ),
            timeout=900,
            on_snapshot_create_logs=lambda chunk: print(
                f"IMAGE_BUILD {chunk}", flush=True
            ),
        )
        manifest["sandbox_id"] = sandbox.id
        print(f"CREATED {sandbox.id}", flush=True)

        sandbox.fs.upload_file(str(HARNESS_ARCHIVE), "/tmp/harness-v0.tar.gz")
        print("UPLOADED frozen harness (runtime installs remotely)", flush=True)

        setup_commands = [
            (
                "install_remote_runtime",
                "mkdir -p /opt/harness && "
                "tar -xzf /tmp/harness-v0.tar.gz -C /opt/harness && "
                "/opt/harness-venv/bin/python -c "
                "'import nexau; print(nexau.__file__)'",
                1800,
            ),
            (
                "gateway_preflight",
                "/opt/harness-venv/bin/python -c \""
                "import os,requests; "
                "r=requests.get(os.environ['LLM_BASE_URL'], timeout=30); "
                "print(r.status_code)\"",
                60,
            ),
        ]
        for name, command, timeout in setup_commands:
            print(f"SETUP_START {name}", flush=True)
            response = sandbox.process.exec(command, timeout=timeout)
            (run_dir / f"setup-{name}.log").write_text(
                (response.result or ""), encoding="utf-8"
            )
            if response.exit_code != 0:
                raise RuntimeError(f"setup {name} failed: {response.exit_code}: {response.result[-3000:]}")
            print(f"SETUP_OK {name}", flush=True)

        baseline = sandbox.process.exec(
            "git -C /testbed status --porcelain && git -C /testbed rev-parse HEAD",
            timeout=60,
        )
        print("BASELINE " + (baseline.result or "").strip().replace("\n", " "), flush=True)

        sandbox.process.create_session(session_id)
        command = sandbox.process.execute_session_command(
            session_id,
            SessionExecuteRequest(
                command="/opt/harness-venv/bin/python -u /opt/harness/entry.py",
                run_async=True,
                suppress_input_echo=True,
            ),
            timeout=60,
        )
        command_id = command.cmd_id
        print(f"HARNESS_STARTED {session_id} {command_id}", flush=True)

        turn0 = {"type": "message", "text": PROBLEM_STATEMENT}
        trace.append({"role": "user", "turn": 0, "content": PROBLEM_STATEMENT})
        sandbox.process.send_session_command_input(
            session_id, command_id, json.dumps(turn0, ensure_ascii=False) + "\n"
        )
        events, replies = wait_for_replies(sandbox, session_id, command_id, 1, 360)
        trace.append({"role": "harness", "turn": 0, "event": replies[0]})
        print("TURN0_REPLY " + str(replies[0].get("text", ""))[:500].replace("\n", " "), flush=True)

        turn1 = {"type": "message", "text": STRICT_USER_FOLLOWUP}
        trace.append({"role": "user", "turn": 1, "content": STRICT_USER_FOLLOWUP})
        sandbox.process.send_session_command_input(
            session_id, command_id, json.dumps(turn1, ensure_ascii=False) + "\n"
        )
        events, replies = wait_for_replies(sandbox, session_id, command_id, 2, 360)
        trace.append({"role": "harness", "turn": 1, "event": replies[1]})
        print("TURN1_REPLY " + str(replies[1].get("text", ""))[:500].replace("\n", " "), flush=True)

        sandbox.process.send_session_command_input(
            session_id, command_id, json.dumps({"type": "shutdown"}) + "\n"
        )
        time.sleep(2)
        raw_logs = sandbox.process.get_session_command_logs(session_id, command_id)
        (run_dir / "harness-stdout.jsonl").write_text(raw_logs.stdout or "", encoding="utf-8")
        (run_dir / "harness-stderr.log").write_text(raw_logs.stderr or "", encoding="utf-8")
        (run_dir / "interaction-trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        patch_response = sandbox.process.exec(
            "git -C /testbed diff --binary", timeout=60
        )
        model_patch = patch_response.result or ""
        (run_dir / "model.patch").write_text(model_patch, encoding="utf-8")
        manifest["model_patch_bytes"] = len(model_patch.encode())
        if not model_patch.strip():
            raise RuntimeError("harness produced no repository patch")
        print(f"PATCH_CAPTURED bytes={manifest['model_patch_bytes']}", flush=True)

        sandbox.process.delete_session(session_id)
        command_id = None
        client.delete(sandbox, timeout=120, wait=True)
        print(f"DELETED_AGENT {sandbox.id}", flush=True)
        manifest["agent_sandbox_deleted"] = True
        sandbox = None

        grader_sandbox = client.create(
            CreateSandboxFromImageParams(
                image=IMAGE,
                resources=Resources(cpu=1, memory=2, disk=10),
                ephemeral=True,
                ttl_minutes=20,
                labels={"purpose": "swebench-grader", "instance": INSTANCE_ID},
            ),
            timeout=900,
        )
        manifest["grader_sandbox_id"] = grader_sandbox.id
        grader_sandbox.fs.upload_file(str(run_dir / "model.patch"), "/tmp/model.patch")
        grader_sandbox.fs.upload_file(TEST_PATCH.encode(), "/tmp/official-test.patch")
        grader = grader_sandbox.process.exec(
            "cd /testbed && "
            "git apply /tmp/model.patch && "
            f"git checkout {BASE_COMMIT} -- tests/test_utils.py && "
            "git apply /tmp/official-test.patch && "
            "/opt/miniconda3/envs/testbed/bin/pytest -rA tests/test_utils.py",
            timeout=600,
        )
        grader_output = grader.result or ""
        (run_dir / "grader.log").write_text(grader_output, encoding="utf-8")
        score = score_targets(grader_output, fail_to_pass, pass_to_pass)
        manifest["grader_exit_code"] = grader.exit_code
        manifest["grader_score"] = score
        manifest["passed"] = score["resolved"]
        manifest["grading_semantics"] = "fresh Daytona sandbox"
        print(f"GRADER_EXIT_CODE {grader.exit_code}", flush=True)
        print(
            "GRADER_SCORE "
            f"f2p={score['fail_to_pass_success']}/{score['fail_to_pass_total']} "
            f"p2p={score['pass_to_pass_success']}/{score['pass_to_pass_total']} "
            f"unrelated_errors={score['unrelated_error_count']}",
            flush=True,
        )
        print("GRADER_TAIL " + grader_output[-1000:].replace("\n", " "), flush=True)

        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if manifest["passed"] else 2
    except Exception as exc:
        manifest["passed"] = False
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        manifest["traceback"] = traceback.format_exc()
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"RUN_ERROR {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        if grader_sandbox is not None:
            try:
                client.delete(grader_sandbox, timeout=120, wait=True)
                print(f"DELETED_GRADER {grader_sandbox.id}", flush=True)
            except Exception as exc:
                print(f"GRADER_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)
        if sandbox is not None:
            if command_id is not None:
                try:
                    sandbox.process.delete_session(session_id)
                except Exception as exc:
                    print(f"SESSION_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)
            try:
                client.delete(sandbox, timeout=120, wait=True)
                print(f"DELETED {sandbox.id}", flush=True)
            except Exception as exc:
                print(f"SANDBOX_CLEANUP_WARNING {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
