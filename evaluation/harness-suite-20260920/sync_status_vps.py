#!/usr/bin/env python3
"""Best-effort E2B -> VPS status relay for one run.

The relay is deliberately outside the experiment controller: a failed VPS or
SSH connection must never stop the evaluation.  Only live/recovery metadata and
the tail of the controller log are copied.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import secrets
import subprocess
import tempfile
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def experiment_name(run_id: str) -> str:
    """Stable human label derived from the frozen local run receipt."""
    if run_id.startswith("probe-"):
        return "内部探针（隐藏）"
    if run_id == "20260922T045045Z-5bb0a2":
        return "Scaling N=1（latency recovery）"
    if run_id == "20260921T220110Z-33a8ee":
        return "N1 旧版失败运行（隐藏）"
    for path in (ROOT / "evaluation" / "harness-suite-20260920" / "runs").rglob("state.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if value.get("run_id") != run_id:
            continue
        n = value.get("n")
        if n:
            return f"Scaling N={n}（5轮混合实验）"
        identity = (value.get("identity") or {})
        experiment_id = str(identity.get("experiment_id") or "")
        if experiment_id:
            return experiment_id
    return "未标注实验"


def _kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip("\"'")
    return out


def _read_remote(sandbox, path: str, limit: int | None = 240_000) -> str:
    try:
        value = sandbox.files.read(path, request_timeout=20)
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        text = str(value)
        # Tail truncation is appropriate for logs/events, but it corrupts JSON
        # when the file is larger than the transport budget.  Callers that
        # need a complete JSON document pass ``limit=None``.
        return text if limit is None else text[-limit:]
    except Exception:
        return ""


def _run_remote(sandbox, command: str, limit: int = 24_000) -> str:
    """Run a bounded read-only probe inside the sandbox."""
    try:
        result = sandbox.commands.run(command, timeout=10)
        return str(getattr(result, "stdout", "") or "")[-limit:]
    except Exception:
        return ""


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _unit_rows(value: object) -> list[dict]:
    """Normalize a recovery stage's units without assuming its container type."""
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _normalized_state(value: dict | None, *, default: str = "pending") -> str:
    value = value or {}
    raw = str(value.get("status") or "").strip().lower()
    if bool(value.get("running")) or raw in {"running", "in_progress", "active"}:
        return "running"
    if raw in {"failed", "error", "timeout", "timed_out", "失败", "超时"}:
        return "failed"
    if raw in {"completed", "complete", "done", "finished", "success", "succeeded", "已完成", "完成"}:
        return "finished"
    return default


def proposal_progress(current_round: dict, runtime: dict, timing_text: str) -> dict:
    """Admission/closure come from recovery, activity from OpenAgents observations.

    A producer's repeated `in-flight` is only liveness, never a completion
    signal. Do not count every delivery_wait/running unit as an active worker.
    """
    units = _unit_rows(((current_round.get('stages') or {}).get('delivery_wait') or {}).get('units'))
    by_issue = {u.get('input', {}).get('issue'): u for u in units}
    admitted = current_round.get('admitted_issue_ids')
    if admitted is None:
        admitted = list(by_issue)
    numbers = sorted({n for n in admitted if isinstance(n, int) and not isinstance(n, bool)})
    latest, actions = {}, {}
    for line in timing_text.splitlines():
        row = _json(line)
        if not isinstance(row, dict) or row.get('issue') not in numbers:
            continue
        number = row['issue']
        if str(row.get('at', '')) >= str(latest.get(number, {}).get('at', '')):
            latest[number] = row
        if row.get('phase') not in {'in-flight', 'ready'}:
            actions[number] = row
    runs = runtime.get('runs') or {}
    rows = []
    for number in numbers:
        unit = by_issue.get(number) or {}
        event = latest.get(number) or {}
        run = runs.get(str(number)) or {}
        phase = event.get('phase')
        ledger_status = unit.get('status', 'pending')
        if ledger_status == 'completed':
            state = 'completed'
        elif ledger_status in {'failed', 'blocked'}:
            state = ledger_status
        elif run.get('status') == 'done':
            state = 'awaiting_confirmation'
        elif phase == 'ready':
            state = 'ready'
        elif phase in {'in-flight', 'solve', 'rebase', 'fix-ci', 'e2e', 'review-or-fix', 'merge', 'reply'}:
            state = 'processing'
        else:
            state = 'unknown'
        action = actions.get(number) or {}
        rows.append({
            'issue': number, 'pr': event.get('pr') or run.get('pr_number'),
            'state': state, 'ledger_status': ledger_status,
            'runtime_status': run.get('status'), 'observed_phase': phase,
            'last_action': action.get('phase'), 'last_action_at': action.get('at'),
            'last_observed_at': event.get('at'),
        })
    summary = {name: sum(r['state'] == name for r in rows) for name in (
        'completed', 'processing', 'ready', 'awaiting_confirmation', 'failed', 'blocked', 'unknown')}
    return {'admitted': len(rows), **summary, 'items': rows}


def snapshot(sandbox, run_id: str, sandbox_id: str) -> tuple[dict, str, str]:
    run = _json(_read_remote(sandbox, "/opt/hse-round/backend/data/live/run.json", limit=None))
    agents = _json(_read_remote(sandbox, "/opt/hse-round/backend/data/live/agents.json", limit=None))
    # recovery.json contains the frozen prompts and can exceed 240 KB.  Never
    # parse a tail-truncated JSON document: that silently erased stages,
    # delivery units, and proposal counts from the dashboard.
    recovery = _json(_read_remote(sandbox, "/opt/hse-run/recovery/recovery.json", limit=None))
    if not isinstance(run, dict) or not isinstance(recovery, dict):
        raise ValueError('Incomplete status read; retaining last valid VPS snapshot')
    exit_code = _read_remote(sandbox, "/opt/hse-run/exit_code", 100).strip()
    log_tail = _read_remote(sandbox, "/opt/hse-run/controller.log", 16_000)
    events = _read_remote(sandbox, "/opt/hse-run/recovery/recovery.jsonl", 16_000)
    run = run if isinstance(run, dict) else {}
    agents = agents if isinstance(agents, dict) else {}
    recovery = recovery if isinstance(recovery, dict) else {}
    # Recovery is authoritative for the phase; live/run.json is only a legacy projection.
    round_states = recovery.get("rounds") or {}
    current_round = round_states.get(str(recovery.get("round"))) or {}
    stages = current_round.get("stages") or {}
    oa_root = '/opt/hse-round/backend/data/harness_sandbox/harness_repo/.openagents/'
    oa_runtime = _json(_read_remote(sandbox, oa_root + 'runtime-state.json', limit=None))
    oa_timing = _run_remote(sandbox, 'tail -c 131072 ' + oa_root + 'timing.jsonl', 131072)
    proposals = proposal_progress(current_round, oa_runtime if isinstance(oa_runtime, dict) else {}, oa_timing)
    phase = next((name for name in ("users", "triage", "divergent", "designer", "owner", "delivery_wait", "round_sealed")
                  if (stages.get(name) or {}).get("status") != "completed"), "completed")
    agent_rows = list(agents.values())
    timestamps = [str(run.get("updated_at") or "")]
    timestamps += [str(row.get("updated_at") or "") for row in agent_rows if isinstance(row, dict)]
    timestamps += [str(recovery.get("updated_at") or "")]
    timestamps = [value for value in timestamps if value]
    last_heartbeat = max(timestamps) if timestamps else None
    # Role status is deliberately separate from delivery-unit progress.  The
    # old implementation treated the role rows as task units (e.g. 1/4), which
    # made a healthy delivery wait look like a failed task.
    by_role = {str(row.get("role")): row for row in agent_rows if isinstance(row, dict)}
    stage_for_role = {"user": "users", "triager": "triage", "pm": "divergent",
                      "designer": "designer", "owner": "owner"}
    components: list[dict] = []
    for role in ("user", "triager", "pm", "designer", "owner"):
        row = by_role.get(role)
        stage = stages.get(stage_for_role[role]) or {}
        state = _normalized_state(stage, default="")
        if not state:
            state = _normalized_state(row, default="pending")
        if exit_code and state == "running":
            state = "interrupted"
        units = _unit_rows(stage.get('units'))
        components.append({
            "name": role,
            "state": state or "pending",
            "running": state == "running",
            "updated_at": (row or {}).get("updated_at") or stage.get("updated_at"),
            "completed": sum(_normalized_state(unit) == 'finished' for unit in units),
            "failed": sum(_normalized_state(unit) == 'failed' for unit in units),
            "total": len(units),
        })
    process_list = _run_remote(sandbox, "ps -eo args", 12_000)
    openagents_running = any(
        token in line.lower() and "grep" not in line.lower()
        for line in process_list.splitlines()
        for token in ("openagents", "vigil")
    )
    oa_state = "running" if openagents_running else ("finished" if phase == "completed" or exit_code else "pending")
    terminal = bool(exit_code)
    if terminal and openagents_running:
        oa_state = "retained"
    components.append({
        "name": "openagents",
        "state": oa_state,
        "running": oa_state == "running",
        "post_exit": terminal and openagents_running,
        "process_running": openagents_running,
    })

    delivery_stage = stages.get("delivery_wait") or {}
    delivery_rows = _unit_rows(delivery_stage.get("units"))
    delivery_completed = sum(_normalized_state(row) == "finished" for row in delivery_rows)
    delivery_failed = sum(_normalized_state(row) == "failed" for row in delivery_rows)
    delivery_running = sum(_normalized_state(row) == "running" for row in delivery_rows)
    delivery_total = len(delivery_rows)
    status = {
        "schema": "hse-status-v1",
        "run_id": run_id,
        "experiment_name": experiment_name(run_id),
        "sandbox_id": sandbox_id,
        # ``done`` used to mean merely ``run.json.running == false``.  That
        # is not a successful outcome: a controller can exit on a blocked
        # round before its exit_code file is visible to the relay.  Keep the
        # terminal states explicit and reserve ``finished`` for exit 0.
        "state": (
            "finished" if exit_code == "0" else "controller_exited"
        ) if exit_code else (
            "running" if run.get("running", True) else
            "controller_exited"
        ),
        "round": run.get("round", 0),
        "total_rounds": run.get("total_rounds", 0),
        "phase": phase if recovery else run.get("phase", ""),
        "completed": delivery_completed,
        "failed": delivery_failed,
        "total_units": delivery_total,
        "delivery": {
            "completed": delivery_completed,
            "failed": delivery_failed,
            "running": delivery_running,
            "pending": max(0, delivery_total - delivery_completed - delivery_failed - delivery_running),
            "total": delivery_total,
        },
        "components": components,
        "proposals": proposals,
        "last_heartbeat": last_heartbeat,
        "started_at": run.get("started_at"),
        "updated_at": datetime.now(UTC).isoformat(),
        "exit_code": int(exit_code) if exit_code.lstrip("-").isdigit() else None,
        "recovery_revision": recovery.get("revision"),
        "agents": agent_rows,
    }
    if last_heartbeat:
        try:
            heartbeat = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=UTC)
            status["stalled_for_seconds"] = max(0, int((datetime.now(UTC) - heartbeat).total_seconds()))
        except ValueError:
            status["stalled_for_seconds"] = None
    else:
        status["stalled_for_seconds"] = None
    return status, events, log_tail


def _ssh_env(password: str) -> tuple[dict[str, str], Path]:
    fd, name = tempfile.mkstemp(prefix="hse-askpass-")
    os.close(fd)
    path = Path(name)
    path.write_text("#!/bin/sh\nprintf '%s\\n' \"$HSE_VPS_PASSWORD\"\n", encoding="utf-8")
    path.chmod(0o700)
    env = dict(os.environ)
    env.update({"DISPLAY": ":0", "SSH_ASKPASS": str(path), "SSH_ASKPASS_REQUIRE": "force", "HSE_VPS_PASSWORD": password})
    return env, path


def push(directory: Path, host: str, password: str, remote_root: str, run_id: str) -> bool:
    env, askpass = _ssh_env(password)
    remote_dir = f"{remote_root.rstrip('/')}/{run_id}"
    target = f"root@{host}:{remote_dir}"
    try:
        opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=8"]
        try:
            mkdir = subprocess.run(["ssh", *opts, f"root@{host}", "mkdir", "-p", f"{remote_root.rstrip('/')}/{run_id}"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if mkdir.returncode != 0:
            return False
        try:
            # Publish status with a same-directory atomic rename. Direct scp
            # truncates status.json first, causing transient parse failures and
            # missing rows while the HTTP server reads the half-written file.
            staging = '.status-' + secrets.token_hex(8) + '.json'
            result = subprocess.run(["scp", *opts, str(directory / "status.json"), target + '/' + staging], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if result.returncode != 0:
                return False
            result = subprocess.run(["ssh", *opts, f"root@{host}",
                'mv -- ' + shlex.quote(remote_dir + '/' + staging) + ' ' + shlex.quote(remote_dir + '/status.json')],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if result.returncode != 0:
                return False
            subprocess.run(["scp", *opts, str(directory / "events.jsonl"), str(directory / "log.tail"), target], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
    finally:
        askpass.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sandbox-id", required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--vps-file", type=Path, default=ROOT.parent / ".vps")
    parser.add_argument("--remote-root", default="/srv/hse-status")
    args = parser.parse_args()
    vps = _kv(args.vps_file)
    lines = args.vps_file.read_text(encoding="utf-8").splitlines() if args.vps_file.is_file() else []
    host = vps.get("VPS_HOST") or (lines[0].strip() if lines else "")
    password = vps.get("VPS_PASSWORD") or (lines[1].strip() if len(lines) > 1 else "")
    if not host or not password:
        return 2
    from e2b import Sandbox

    e2b_values = _kv(ROOT.parent / ".e2b")
    e2b_values.update(_kv(ROOT / ".e2b"))
    e2b_key = e2b_values.get("API_KEY") or e2b_values.get("E2B_API_KEY") or e2b_values.get("API_KET")
    if not e2b_key:
        return 2
    # E2B control-plane requests can transiently fail exactly when a new
    # sandbox is being resumed.  Keep the relay alive and retry rather than
    # silently disappearing before its first VPS snapshot.
    sandbox = None
    while sandbox is None:
        try:
            sandbox = Sandbox.connect(args.sandbox_id, api_key=e2b_key, timeout=30)
        except Exception:
            time.sleep(min(30.0, max(5.0, args.interval)))
    with tempfile.TemporaryDirectory(prefix="hse-status-") as tmp:
        directory = Path(tmp) / args.run_id
        directory.mkdir()
        failures = 0
        while True:
            try:
                status, events, log_tail = snapshot(sandbox, args.run_id, args.sandbox_id)
                (directory / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (directory / "events.jsonl").write_text(events, encoding="utf-8")
                (directory / "log.tail").write_text(log_tail, encoding="utf-8")
                ok = push(directory, host, password, args.remote_root, args.run_id)
                failures = 0 if ok else failures + 1
                if ok and status.get("exit_code") is not None and not any(
                    c.get('process_running', c.get('running')) for c in status.get('components', [])
                ):
                    return int(status["exit_code"])
            except Exception:
                failures += 1
                Path(str(directory) + ".relay-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            time.sleep(min(60.0, max(2.0, args.interval) * (1 + min(failures, 5))))


if __name__ == "__main__":
    raise SystemExit(main())
