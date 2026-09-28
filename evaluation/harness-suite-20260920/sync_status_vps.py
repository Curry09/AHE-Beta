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
import subprocess
import tempfile
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


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
        experiment_id = str(value.get("experiment_id") or "")
        if experiment_id.startswith("n16-kimi"):
            return "模型对比实验(KIMI) N=16"
        if experiment_id.startswith("n16-all-gpt6-luna"):
            return "模型对比实验(GPT-6 Luna) N=16"
        if experiment_id.startswith("n16-") and "model" in experiment_id:
            return "模型对比实验 N=16"
        n = value.get("n")
        if n and "-r5-design-r6-users-" in experiment_id:
            return f"Scaling N={n}（补跑设计开发＋第6轮）"
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
        # File downloads can time out for large recovery ledgers even while
        # the sandbox command channel is healthy. Only the dashboard fields
        # are needed; project them inside the sandbox instead of retrying a
        # multi-megabyte transfer.
        if path == "/opt/hse-run/recovery/recovery.json":
            return _run_remote(
                sandbox, "python3 -c " + shlex.quote(_RECOVERY_PROJECTION), limit=None
            )
        if path == "/opt/hse-round/backend/data/live/run.json":
            return _run_remote(sandbox, "cat -- " + shlex.quote(path), limit=None)
        return ""


_RECOVERY_PROJECTION = """\
import json
from pathlib import Path

source = json.loads(Path('/opt/hse-run/recovery/recovery.json').read_text())
round_key = str(source.get('round'))
current = (source.get('rounds') or {}).get(round_key) or {}
stages = {}
for name, stage in (current.get('stages') or {}).items():
    units = stage.get('units') or {}
    if isinstance(units, dict):
        units = units.values()
    stages[name] = {
        'status': stage.get('status'),
        'updated_at': stage.get('updated_at'),
        'units': [
            {'status': unit.get('status'),
             'input': {'issue': (unit.get('input') or {}).get('issue')}}
            for unit in units if isinstance(unit, dict)
        ],
    }
print(json.dumps({
    'round': source.get('round'),
    'revision': source.get('revision'),
    'updated_at': source.get('updated_at'),
    'rounds': {round_key: {
        'stages': stages,
        'admitted_issue_ids': current.get('admitted_issue_ids'),
    }},
}, ensure_ascii=False, separators=(',', ':')))
"""


def _run_remote(sandbox, command: str, limit: int | None = 24_000) -> str:
    """Run a bounded read-only probe inside the sandbox."""
    try:
        result = sandbox.commands.run(command, timeout=15)
        text = str(getattr(result, "stdout", "") or "")
        return text if limit is None else text[-limit:]
    except Exception:
        return ""


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def api_sources(env_text: str) -> dict[str, str]:
    """Report provider names from effective sandbox endpoints, never credentials."""
    endpoints = {}
    allowed = {
        "HARNESS_LLM_BASE_URL": "harness",
        "USER_LLM_BASE_URL": "user",
        "DESIGNER_LLM_BASE_URL": "designer",
        "DEVELOPER_LLM_BASE_URL": "developer",
    }
    for line in env_text.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key.strip() not in allowed:
            continue
        try:
            host = (urlsplit(value.strip().strip("\"' ")).hostname or "").lower()
        except ValueError:
            host = ""
        if host == "api.boyuerichdata.opensphereai.com":
            source = "Boyue"
        elif host == "aigateway.paperbypass.com":
            source = "WIS"
        elif host == "openrouter.ai":
            source = "OpenRouter"
        else:
            source = "未知"
        endpoints[allowed[key.strip()]] = source
    return endpoints


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


_REMOTE_COLLECT = """\
import json
import pathlib

def read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}

def tail(path, size):
    try:
        with open(path, 'rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - size))
            return stream.read().decode('utf-8', 'replace')
    except OSError:
        return ''

def compact_timing(path):
    latest = {}
    actions = {}
    for line in tail(path, 131072).splitlines():
        try:
            source = json.loads(line)
        except ValueError:
            continue
        if not isinstance(source, dict):
            continue
        issue = source.get('issue')
        if not isinstance(issue, int) or isinstance(issue, bool):
            continue
        row = {key: source.get(key) for key in ('issue', 'pr', 'phase', 'at')}
        if str(row.get('at') or '') >= str(latest.get(issue, {}).get('at') or ''):
            latest[issue] = row
        if row.get('phase') not in ('in-flight', 'ready'):
            actions[issue] = row
    rows = []
    for issue in sorted(latest):
        rows.append(latest[issue])
        action = actions.get(issue)
        if action is not None and action != latest[issue]:
            rows.append(action)
    return '\\n'.join(json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in rows)

source = read_json('/opt/hse-run/recovery/recovery.json')
round_key = str(source.get('round'))
current = (source.get('rounds') or {}).get(round_key) or {}
stages = {}
for name, stage in (current.get('stages') or {}).items():
    units = stage.get('units') or {}
    if isinstance(units, dict):
        units = units.values()
    stages[name] = {
        'status': stage.get('status'),
        'updated_at': stage.get('updated_at'),
        'units': [
            {'status': unit.get('status'),
             'input': {'issue': (unit.get('input') or {}).get('issue')}}
            for unit in units if isinstance(unit, dict)
        ],
    }
recovery = {
    'round': source.get('round'),
    'revision': source.get('revision'),
    'updated_at': source.get('updated_at'),
    'rounds': {round_key: {
        'stages': stages,
        'admitted_issue_ids': current.get('admitted_issue_ids'),
    }},
}
runtime = read_json('/opt/hse-round/backend/data/harness_sandbox/harness_repo/.openagents/runtime-state.json')
runs = runtime.get('runs') or {}
runtime = {'runs': {key: {'status': value.get('status'), 'pr_number': value.get('pr_number')}
                    for key, value in runs.items() if isinstance(value, dict)}}
agent_source = read_json('/opt/hse-round/backend/data/live/agents.json')
agents = {key: {field: value.get(field) for field in
                ('role', 'status', 'running', 'round', 'started_at', 'updated_at')}
          for key, value in agent_source.items() if isinstance(value, dict)}
env_lines = tail('/opt/hse-round/backend/.env', 64000).splitlines()
allowed = {'HARNESS_LLM_BASE_URL', 'USER_LLM_BASE_URL',
           'DESIGNER_LLM_BASE_URL', 'DEVELOPER_LLM_BASE_URL'}
env_text = '\\n'.join(line for line in env_lines if line.partition('=')[0].strip() in allowed)
openagents_running = False
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    try:
        args = path.read_bytes().split(b'\\0')
    except OSError:
        continue
    if b'vigil' in args and any(b'openagents' in arg for arg in args):
        openagents_running = True
        break
print(json.dumps({
    'run': read_json('/opt/hse-round/backend/data/live/run.json'),
    'agents': agents,
    'recovery': recovery,
    'runtime': runtime,
    'env': env_text,
    'exit_code': tail('/opt/hse-run/exit_code', 100).strip(),
    'log_tail': tail('/opt/hse-run/controller.log', 16000),
    'events': tail('/opt/hse-run/recovery/recovery.jsonl', 16000),
    'timing': compact_timing('/opt/hse-round/backend/data/harness_sandbox/harness_repo/.openagents/timing.jsonl'),
    'openagents_running': openagents_running,
}, ensure_ascii=False, separators=(',', ':')))
"""


def _collect_bundle(sandbox) -> dict | None:
    # A transport timeout means the sandbox connection needs to be reopened.
    # Falling back to many file downloads on that same connection can stall a
    # relay for minutes and suppress every subsequent refresh.
    result = sandbox.commands.run(
        "python3 -c " + shlex.quote(_REMOTE_COLLECT), timeout=30
    )
    value = _json(getattr(result, "stdout", ""))
    if (isinstance(value, dict) and isinstance(value.get("run"), dict)
            and value["run"] and isinstance(value.get("recovery"), dict)
            and value["recovery"].get("round") is not None):
        return value
    return None


def snapshot(sandbox, run_id: str, sandbox_id: str) -> tuple[dict, str, str]:
    bundle = _collect_bundle(sandbox)
    if bundle is not None:
        run = bundle["run"]
        agents = bundle.get("agents")
        sources = api_sources(str(bundle.get("env") or ""))
        recovery = bundle["recovery"]
        exit_code = str(bundle.get("exit_code") or "").strip()
        log_tail = str(bundle.get("log_tail") or "")
        events = str(bundle.get("events") or "")
        oa_runtime = bundle.get("runtime")
        oa_timing = str(bundle.get("timing") or "")
        openagents_running = bool(bundle.get("openagents_running"))
    else:
        run = _json(_read_remote(sandbox, "/opt/hse-round/backend/data/live/run.json", limit=None))
        agents = _json(_read_remote(sandbox, "/opt/hse-round/backend/data/live/agents.json", limit=None))
        sources = api_sources(_read_remote(sandbox, "/opt/hse-round/backend/.env", limit=None))
        # Never parse a tail-truncated recovery JSON document.
        recovery = _json(_read_remote(sandbox, "/opt/hse-run/recovery/recovery.json", limit=None))
        exit_code = _read_remote(sandbox, "/opt/hse-run/exit_code", 100).strip()
        log_tail = _read_remote(sandbox, "/opt/hse-run/controller.log", 16_000)
        events = _read_remote(sandbox, "/opt/hse-run/recovery/recovery.jsonl", 16_000)
        oa_root = '/opt/hse-round/backend/data/harness_sandbox/harness_repo/.openagents/'
        oa_runtime = _json(_read_remote(sandbox, oa_root + 'runtime-state.json', limit=None))
        oa_timing = _run_remote(sandbox, 'tail -c 131072 ' + oa_root + 'timing.jsonl', 131072)
        process_list = _run_remote(sandbox, "ps -eo args", 12_000)
        openagents_running = any(
            token in line.lower() and "grep" not in line.lower()
            for line in process_list.splitlines()
            for token in ("openagents", "vigil")
        )
    if not isinstance(run, dict) or not isinstance(recovery, dict):
        raise ValueError('Incomplete status read; retaining last valid VPS snapshot')
    run = run if isinstance(run, dict) else {}
    agents = agents if isinstance(agents, dict) else {}
    recovery = recovery if isinstance(recovery, dict) else {}
    # Recovery is authoritative for the phase; live/run.json is only a legacy projection.
    round_states = recovery.get("rounds") or {}
    current_round = round_states.get(str(recovery.get("round"))) or {}
    stages = current_round.get("stages") or {}
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
        "api_sources": sources,
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


_REMOTE_PUBLISH = """\
import json
import os
import pathlib
import re
import sys
import tempfile

payload = json.load(sys.stdin)
run_id = payload["run_id"]
if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
    raise ValueError("invalid run ID")
status = payload["status"]
if json.loads(status).get("run_id") != run_id:
    raise ValueError("status run ID mismatch")
directory = pathlib.Path(payload["remote_root"]) / run_id
directory.mkdir(parents=True, exist_ok=True)
fd, staging = tempfile.mkstemp(prefix=".status-", suffix=".json", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(status)
        stream.flush()
        os.fsync(stream.fileno())
    (directory / "events.jsonl").write_text(payload["events"], encoding="utf-8")
    (directory / "log.tail").write_text(payload["log_tail"], encoding="utf-8")
    os.replace(staging, directory / "status.json")
finally:
    if os.path.exists(staging):
        os.unlink(staging)
"""


def _ssh_proxy_options() -> list[str]:
    """Use the configured network proxy for SSH when one is available."""
    raw = os.environ.get("HSE_VPS_SSH_PROXY") or os.environ.get("ALL_PROXY", "")
    try:
        proxy = urlsplit(raw)
        host, port = proxy.hostname, proxy.port
    except ValueError:
        return []
    if not host or not port or proxy.username or proxy.password:
        return []
    mode = {"socks5": "5", "socks5h": "5", "http": "connect"}.get(proxy.scheme.lower())
    if mode is None:
        return []
    address = f"{shlex.quote(host)}:{port}"
    return ["-o", f"ProxyCommand=nc -X {mode} -x {address} %h %p"]


def push(directory: Path, host: str, password: str, remote_root: str, run_id: str, port: str) -> bool:
    env, askpass = _ssh_env(password)
    try:
        payload = {
            "remote_root": remote_root,
            "run_id": run_id,
            "status": (directory / "status.json").read_text(encoding="utf-8"),
            "events": (directory / "events.jsonl").read_text(encoding="utf-8"),
            "log_tail": (directory / "log.tail").read_text(encoding="utf-8"),
        }
        # One SSH connection publishes all three files. The status rename is
        # last, so readers never see a partial JSON document.
        result = subprocess.run(
            ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=5",
             "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
             *_ssh_proxy_options(),
             f"root@{host}", "python3 -c " + shlex.quote(_REMOTE_PUBLISH)],
            env=env,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=25,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
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
    port = vps.get("VPS_PORT") or (lines[2].strip() if len(lines) > 2 else "22")
    if not host or not password:
        return 2
    from e2b import Sandbox

    e2b_values = _kv(ROOT.parent / ".e2b")
    e2b_values.update(_kv(ROOT / ".e2b"))
    e2b_key = e2b_values.get("API_KEY") or e2b_values.get("E2B_API_KEY") or e2b_values.get("API_KET")
    if not e2b_key:
        return 2
    sandbox = None
    with tempfile.TemporaryDirectory(prefix="hse-status-") as tmp:
        directory = Path(tmp) / args.run_id
        directory.mkdir()
        failures = 0
        while True:
            try:
                if sandbox is None:
                    sandbox = Sandbox.connect(args.sandbox_id, api_key=e2b_key, timeout=30)
                status, events, log_tail = snapshot(sandbox, args.run_id, args.sandbox_id)
                (directory / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (directory / "events.jsonl").write_text(events, encoding="utf-8")
                (directory / "log.tail").write_text(log_tail, encoding="utf-8")
                ok = push(directory, host, password, args.remote_root, args.run_id, port)
                failures = 0 if ok else failures + 1
                if ok and status.get("exit_code") is not None and not any(
                    c.get('process_running', c.get('running')) for c in status.get('components', [])
                ):
                    return int(status["exit_code"])
            except Exception:
                failures += 1
                # A paused/resumed sandbox can invalidate the old envd connection.
                sandbox = None
                Path(str(directory) + ".relay-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            time.sleep(args.interval if not failures else min(30.0, 10.0 * failures))


if __name__ == "__main__":
    raise SystemExit(main())
