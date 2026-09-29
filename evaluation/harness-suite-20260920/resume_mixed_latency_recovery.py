"""Explicit same-sandbox recovery with the configured latency policy.

Only demand-role timing files change. Task payloads, identities and completed
recovery units are preserved. Never creates a fresh experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime

import run_scaling_bundle_e2b as runner
import sync_status_vps as relay


def main():
    from e2b import Sandbox

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--n", required=True, type=int, choices=(4, 8, 16, 32))
    args = parser.parse_args()
    path = runner.SUITE / "runs/scaling-e2b-20260922" / f"n{args.n}" / args.run_id / "state.json"
    state = runner.read_json(path)
    assert state["run_id"] == args.run_id and state["n"] == args.n
    values = relay._kv(runner.ROOT.parent / ".e2b")
    values.update(relay._kv(runner.ROOT / ".e2b"))
    key = values.get("E2B_API_KEY") or values.get("API_KEY") or values.get("API_KET")
    sandbox = Sandbox.connect(state["sandbox_id"], api_key=key)
    processes = sandbox.commands.run("ps -eo pid,ppid,args", timeout=20).stdout
    if any(
        "python" in line and "scripts/run_mixed_closed_loop.py" in line
        for line in processes.splitlines()
    ):
        raise RuntimeError("Controller already running; refusing duplicate resume")
    recovery = json.loads(sandbox.files.read("/opt/hse-run/recovery/recovery.json"))
    ident = recovery["identity"]
    assert ident["run_id"] == args.run_id
    assert ident["experiment_id"] == f"hse-n{args.n}-e2b-20260922"
    current = recovery["rounds"][str(recovery["round"])]
    assert current["stages"]["users"]["status"] == "completed"
    assert not current.get("admitted_issue_ids"), (
        "Delivery already admitted; manual worker handoff required"
    )
    assert sandbox.files.read("/opt/hse-run/exit_code").strip() == "1"
    script = sandbox.files.read("/opt/hse-round/run.sh")
    for key_name, env in [
        ("run_id", "RUN_ID"),
        ("experiment_id", "EXPERIMENT_ID"),
        ("config_hash", "CONFIG_HASH"),
        ("controller_sha", "CONTROLLER_SHA"),
        ("plan_hash", "PLAN_HASH"),
    ]:
        assert f"AUTO_DESIGNER_{env}={ident[key_name]}" in script, key_name
    paths = [
        "backend/auto_designer/usage.py",
        "backend/auto_designer/loop/live_tracer.py",
        "backend/auto_designer/demand/agent_runtime.py",
    ]
    updates = {}
    for rel in paths:
        old = sandbox.files.read("/opt/hse-round/" + rel)
        new = (runner.ROOT / rel).read_text()
        base = subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=runner.ROOT, text=True)
        if old not in (base, new):
            raise RuntimeError(f"Unexpected remote edits: {rel}")
        updates[rel] = new
    policy_config = runner.read_json(runner.CONFIG)["timeouts"]["latency_isolated_timeout"]
    assert policy_config["enabled"]
    policy = {
        "AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1",
        "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": str(policy_config["wall_guard_grace_seconds"]),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = "/opt/hse-run/recovery-overrides/latency-" + stamp
    sandbox.commands.run(
        f"mkdir -p {backup} && cp /opt/hse-run/recovery/recovery.json {backup}/recovery.json "
        f"&& cp /opt/hse-run/exit_code {backup}/exit_code "
        f"&& cd /opt/hse-round && cp --parents {' '.join(paths)} {backup}/",
        user="root",
        timeout=30,
    )
    for rel, body in updates.items():
        sandbox.files.write("/opt/hse-round/" + rel, body, user="root")
    sandbox.commands.run(
        "/opt/hse-venv/bin/python -m py_compile "
        + " ".join("/opt/hse-round/" + rel for rel in paths),
        user="root",
        timeout=30,
    )
    # A blocked run retained an idle vigil. Do not create two delivery workers.
    # Validate the exact process belongs to this run and has no active children.
    for line in processes.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3 or "openagents vigil --parallel" not in parts[2]:
            continue
        pid = int(parts[0])
        if any(row.strip().split(None, 2)[1:2] == [str(pid)] for row in processes.splitlines()[1:]):
            raise RuntimeError("Retained vigil has children; refusing to interrupt delivery")
        cwd = sandbox.commands.run(f"readlink /proc/{pid}/cwd", timeout=10).stdout.strip()
        assert cwd == "/opt/hse-round/backend/data/harness_sandbox/harness_repo"
        sandbox.commands.run(f"kill -TERM {pid}", user="root", timeout=10)
    receipt = {
        "kind": "authorised-timing-policy-recovery",
        "run_id": args.run_id,
        "parent_identity": ident,
        "parent_revision": recovery["revision"],
        "at": stamp,
        "backup": backup,
        "effective_env": policy,
        "files": {p: hashlib.sha256(t.encode()).hexdigest() for p, t in updates.items()},
    }
    sandbox.files.write(backup + "/receipt.json", json.dumps(receipt, indent=2), user="root")
    sandbox.commands.run(
        f"mv /opt/hse-run/exit_code {backup}/exit_code.previous", user="root", timeout=10
    )
    cmd = sandbox.commands.run(
        "bash /opt/hse-round/run.sh",
        envs={**policy, "AUTO_DESIGNER_RUN_MODE": "resume"},
        user="user",
        background=True,
        timeout=86400,
    )
    receipt["command_pid"] = getattr(cmd, "pid", None)
    state.setdefault("runtime_overrides", []).append(receipt)
    runner.write_state(path, state)
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "sandbox_id": state["sandbox_id"],
                "policy": policy,
                "pid": receipt["command_pid"],
                "backup": backup,
            }
        )
    )


if __name__ == "__main__":
    main()
