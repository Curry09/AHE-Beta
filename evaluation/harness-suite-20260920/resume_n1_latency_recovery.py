"""One-run, explicitly authorised N1 timing-policy recovery; never fresh-start."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import run_n1_e2b as runner
import sync_status_vps as relay


def main() -> None:
    from e2b import Sandbox

    run_id = "20260922T045045Z-5bb0a2"
    directory = runner.SUITE / "runs" / f"e2b-n1-20260922-{run_id}"
    state = runner.read_json(directory / "state.json")
    values = relay._kv(runner.ROOT.parent / ".e2b")
    values.update(relay._kv(runner.ROOT / ".e2b"))
    key = values.get("E2B_API_KEY") or values.get("API_KEY") or values.get("API_KET")
    sandbox = Sandbox.connect(state["sandbox_id"], api_key=key)
    probe = sandbox.commands.run(
        "pgrep -af '[p]ython.*scripts/run_swebench_closed_loop.py' || true", timeout=10
    )
    if probe.stdout.strip():
        raise RuntimeError("Controller already running; refusing duplicate resume")
    recovery = json.loads(sandbox.files.read("/opt/hse-run/recovery/recovery.json"))
    if recovery["identity"] != {
        k: v for k, v in state["identity"].items() if k != "recovery_root"
    }:
        raise RuntimeError("Recovery identity mismatch")
    if recovery["round"] != 3 or recovery["rounds"]["3"]["stages"]["users"]["status"] != "completed":
        raise RuntimeError("Not the expected round-3 triage checkpoint")
    if sandbox.files.read("/opt/hse-run/exit_code").strip() != "1":
        raise RuntimeError("Expected failed controller exit code 1")
    paths = ["backend/auto_designer/usage.py", "backend/auto_designer/loop/live_tracer.py",
             "backend/auto_designer/designer/agent_runtime.py"]
    updates = {}
    for rel in paths:
        old = sandbox.files.read("/opt/hse-round/" + rel)
        new = (runner.ROOT / rel).read_text()
        base = subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=runner.ROOT, text=True)
        if old not in (base, new):
            raise RuntimeError(f"Unexpected remote changes: {rel}")
        updates[rel] = new
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = f"/opt/hse-run/recovery-overrides/latency-{stamp}"
    sandbox.commands.run(
        f"mkdir -p {backup}; cp /opt/hse-run/exit_code {backup}/exit_code; "
        f"cp /opt/hse-run/recovery/recovery.json {backup}/recovery.json; "
        f"cd /opt/hse-round && cp --parents {' '.join(paths)} {backup}/",
        user="root", timeout=20,
    )
    for rel, body in updates.items():
        sandbox.files.write("/opt/hse-round/" + rel, body, user="root")
    sandbox.commands.run(
        "/opt/hse-venv/bin/python -m py_compile " +
        " ".join("/opt/hse-round/" + rel for rel in paths), user="root", timeout=20,
    )
    policy = {"AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1",
              "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": "600"}
    receipt = {"kind": "authorised-timing-policy-recovery", "run_id": run_id,
               "at": stamp, "parent_identity": recovery["identity"],
               "parent_revision": recovery["revision"], "effective_env": policy,
               "backup": backup, "scope": "shared-demand-role-runtime-only",
               "files": {p: hashlib.sha256(t.encode()).hexdigest() for p, t in updates.items()}}
    sandbox.files.write(backup + "/receipt.json", json.dumps(receipt, indent=2), user="root")
    sandbox.commands.run(f"mv /opt/hse-run/exit_code {backup}/exit_code.previous", user="root", timeout=10)

    def launch(command, **kwargs):
        kwargs["envs"] = {**kwargs.get("envs", {}), **policy}
        return sandbox.commands.run(command, **kwargs)

    proxy = SimpleNamespace(commands=SimpleNamespace(run=launch))
    plan = runner.read_json(runner.DEFAULT_CONFIG)
    command = runner.start_remote(proxy, plan, state["identity"], True)
    receipt["command_pid"] = getattr(command, "pid", None)
    state.setdefault("runtime_overrides", []).append(receipt)
    state["resumed_at"] = datetime.now(UTC).isoformat()
    runner.write_state(directory, state)
    print(json.dumps({"run_id": run_id, "sandbox_id": state["sandbox_id"],
                      "policy": policy, "backup": backup, "pid": receipt["command_pid"]}))


if __name__ == "__main__":
    main()
