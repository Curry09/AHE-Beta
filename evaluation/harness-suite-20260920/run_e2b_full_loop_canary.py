#!/usr/bin/env python3
"""Run one one-round E2B/Boyue full-loop canary with the formal resource template.

The canary uses the frozen O03 path, but does not modify the N=1 run or its
recovery identity.  Its receipt is evidence for N=4/N=8 runtime preparation,
not a benchmark score.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import run_n1_e2b as n1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-alias", default="hse-runtime-8g-v1")
    parser.add_argument("--template-build-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gitea-env", type=Path)
    parser.add_argument("--gitea-url", help="publicly reachable Gitea URL for the sandbox")
    parser.add_argument("--source-sandbox-id", help="reuse the frozen Gitea credentials from an existing E2B sandbox")
    args = parser.parse_args()

    creds = n1.credentials(args.gitea_env)
    if args.source_sandbox_id:
        from e2b import Sandbox

        source = Sandbox.connect(args.source_sandbox_id, api_key=creds["E2B_API_KEY"])
        result = source.commands.run(
            "cat /opt/hse-round/backend/deploy/gitea/.env",
            user="root",
            timeout=30,
        )
        if result.exit_code != 0:
            raise n1.LaunchError("source sandbox Gitea credentials are unavailable")
        for line in (result.stdout or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in {"GITEA_URL", "OWNER", "TOKEN"} and value.strip():
                    if key.strip() == "GITEA_URL":
                        creds["GITEA_URL"] = value.strip().rstrip("/")
                    elif key.strip() == "OWNER":
                        creds["GITEA_USER"] = value.strip()
                    elif key.strip() == "TOKEN":
                        creds["GITEA_TOKEN"] = value.strip()
    if args.gitea_url:
        creds["GITEA_URL"] = args.gitea_url.rstrip("/")
    plan = n1.load_plan(n1.DEFAULT_CONFIG)
    plan = json.loads(json.dumps(plan))
    plan["rounds"]["count"] = 1
    plan["execution"]["resource_profile"] = {
        "template_alias": args.template_alias,
        "template_build_id": args.template_build_id,
        "cpu_count": 4,
        "memory_mb": 8192,
        "storage_mb": 10240,
        "profile": "developer",
    }
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-canary-" + secrets.token_hex(3)
    repo_name = f"hse-e2b-canary-{run_id}"
    n1.ensure_repo(creds, repo_name, False)
    identity = n1.identity(n1.DEFAULT_CONFIG, run_id)
    sandbox = None
    output = {
        "schema_version": "hse-e2b-full-loop-canary-v1",
        "status": "failed",
        "full_loop": False,
        "run_id": run_id,
        "template_alias": args.template_alias,
        "template_build_id": args.template_build_id,
        "resources": {"cpu_count": 4, "memory_mb": 8192, "storage_mb": 10240},
    }
    try:
        sandbox = n1.create_sandbox(plan, creds, run_id, repo_name, identity)
        command = n1.start_remote(sandbox, plan, identity, False)
        output.update({"sandbox_id": sandbox.sandbox_id, "command_pid": getattr(command, "pid", None)})
        # Keep the SDK connection alive while the background command runs.  E2B
        # tears down a background command when the client process disappears;
        # a canary must observe the actual one-round result, not just enqueue it.
        deadline = time.monotonic() + 3600
        exit_code = None
        while time.monotonic() < deadline:
            probe = sandbox.commands.run(
                "test -f /opt/hse-run/exit_code && cat /opt/hse-run/exit_code || true",
                user="root",
                timeout=30,
            )
            text = (probe.stdout or "").strip()
            if text:
                try:
                    exit_code = int(text.splitlines()[-1])
                except ValueError:
                    exit_code = 1
                break
            time.sleep(10)
        if exit_code is None:
            raise n1.LaunchError("full-loop canary exceeded 3600 seconds")
        output.update({"exit_code": exit_code, "status": "passed" if exit_code == 0 else "failed", "full_loop": exit_code == 0})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        output["error"] = f"{type(exc).__name__}: {exc}"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
