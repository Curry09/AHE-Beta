#!/usr/bin/env python3
"""Explicit, audited OOM migration for the already-authorized N=1 recovery.

Never used by normal resume. Requires a quiescent source and empty target
controller; copies the source runtime as well as state to prevent model/config
drift. The source sandbox is retained, not killed.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import run_n1_e2b as runner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--gitea-env", type=Path, required=True)
    args = ap.parse_args()
    creds = runner.credentials(args.gitea_env)
    from e2b import Sandbox

    old = Sandbox.connect(args.source, api_key=creds["E2B_API_KEY"])
    new = Sandbox.connect(args.target, api_key=creds["E2B_API_KEY"])
    run_dir = runner.SUITE / "runs" / f"e2b-n1-20260922-{args.run_id}"
    state = runner.read_json(run_dir / "state.json")
    assert state["sandbox_id"] == args.source, "already migrated or wrong source"
    assert args.source != args.target
    plan = runner.load_plan(runner.DEFAULT_CONFIG)
    assert state["identity"]["config_hash"] == runner.config_hash(runner.DEFAULT_CONFIG)
    assert state["identity"]["controller_sha"] == runner.git_sha()
    # The probes emit only process names, never credentials/arguments.
    for box in (old, new):
        names = box.commands.run("ps -eo comm=", timeout=20).stdout.splitlines()
        assert not any(n.strip() in {"openagents", "claude"} for n in names), "worker still alive"
    memory = new.commands.run("awk '/MemTotal/{print $2}' /proc/meminfo", timeout=20).stdout
    assert int(memory.strip()) > 1900000, "target has less than 2 GiB nominal RAM"
    # Source is quiescent. Preserve its exact packages, executable, role config,
    # Claude session history, git/worktrees, WAL files and recovery receipts.
    remote = "/tmp/hse-oom-runtime-exact.tgz"
    command = (
        "umask 077; tar -I 'gzip -1' -cf "
        + remote
        + " -C / opt/hse-round opt/hse-run opt/hse-venv opt/task-venv opt/python"
        " usr/local/bin/claude home/user/.claude home/user/.claude.json"
    )
    print("Archiving exact source runtime and state", flush=True)
    old.commands.run(command, user="root", timeout=1800)
    digest = old.commands.run("sha256sum " + remote, user="root", timeout=60).stdout.split()[0]
    with tempfile.TemporaryDirectory(prefix="hse-oom-exact-") as directory:
        archive = Path(directory) / "runtime.tgz"
        with archive.open("wb") as out:
            os.chmod(archive, 0o600)
            with old.files.read(
                remote, format="stream", user="root", request_timeout=1800
            ) as stream:
                for chunk in stream:
                    out.write(chunk)
        assert runner.sha256(archive) == digest, "download checksum mismatch"
        print("Verified archive bytes:", archive.stat().st_size, flush=True)
        with archive.open("rb") as inp:
            new.files.write(remote, inp, user="root", request_timeout=1800, use_octet_stream=True)
    actual = new.commands.run("sha256sum " + remote, user="root", timeout=60).stdout.split()[0]
    assert actual == digest, "upload checksum mismatch"
    print("Archive verified on target; restoring", flush=True)
    new.commands.run("tar -xzf " + remote + " -C /", user="root", timeout=1800)
    ledger = "/opt/hse-run/recovery/recovery.json"
    old_json = old.files.read(ledger, user="root")
    assert new.files.read(ledger, user="root") == old_json, "ledger drift"
    saved = json.loads(old_json)
    assert saved["identity"]["run_id"] == args.run_id
    assert new.files.read("/opt/hse-run/exit_code", user="root").strip() == "137"
    new.commands.run(
        "mv /opt/hse-run/exit_code /opt/hse-run/exit_code.pre-oom-migration",
        user="root",
        timeout=20,
    )
    receipt = {
        "type": "oom-recovery",
        "source_sandbox_id": args.source,
        "target_sandbox_id": args.target,
        "target_memory_mb": 2048,
        "archive_sha256": digest,
        "recovery_revision_before": saved["revision"],
        "at": runner.now(),
        "status": "restored-not-started",
        "identity_unchanged": True,
    }
    runner.write_state(run_dir, {**state, "sandbox_id": args.target, "migration": receipt})
    # Keep the frozen identity unchanged. Migration metadata is NOT process env.
    command = runner.start_remote(new, plan, state["identity"], True)
    receipt["status"] = "resume-start-requested"
    runner.write_state(
        run_dir,
        {
            **state,
            "sandbox_id": args.target,
            "migration": receipt,
            "resume_command_pid": getattr(command, "pid", None),
            "resumed_at": runner.now(),
        },
    )
    print("RESUME_START_REQUESTED", args.target, flush=True)


if __name__ == "__main__":
    main()
