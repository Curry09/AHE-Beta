#!/usr/bin/env python3
"""Hourly dashboard monitor with conservative same-sandbox resume."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
DEFAULT_URL = "http://38.47.121.235:18080/api/runs"
GITEA_ENV = Path("/tmp/hse-gitea.env")
ALLOWED_N = {1, 4, 8, 16, 32}
ACTIVE_RUN_IDS = (
    "20260922T045045Z-5bb0a2",
    "20260922T133329Z-e04374",
    "20260922T133332Z-0e6120",
    "20260922T184216Z-124e65",
    "20260922T184219Z-bae826",
)


def log(message: str, path: Path) -> None:
    line = f"{datetime.now(UTC).isoformat()} {message}"
    print(line, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def fetch(url: str) -> list[dict]:
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed operator URL
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, list):
        raise ValueError("dashboard returned a non-list run payload")
    return [row for row in value if isinstance(row, dict)]


def local_state(run_id: str) -> tuple[int | None, Path | None]:
    for path in (SUITE / "runs").rglob("state.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if value.get("run_id") != run_id:
            continue
        n = value.get("n")
        if n is None and "e2b-n1-" in str(path):
            n = 1
        return int(n) if n is not None else None, path
    return None, None


def resume_one(row: dict, log_path: Path) -> None:
    run_id = str(row.get("run_id") or "")
    n, state_path = local_state(run_id)
    if not run_id or n not in ALLOWED_N or state_path is None:
        log(f"SKIP resume: no frozen local state for {run_id!r}", log_path)
        return
    command = [
        sys.executable,
        str(SUITE / "resume_checkpoint_e2b.py"),
        "--n",
        str(n),
        "--run-id",
        run_id,
    ]
    log(f"RECOVERY inspect run={run_id} n={n}", log_path)
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
    output = (result.stdout + "\n" + result.stderr).strip().replace("\x00", "")
    log(f"RESUME result run={run_id} rc={result.returncode} output={output[-1200:]}", log_path)


def check_once(url: str, log_path: Path) -> None:
    try:
        rows = fetch(url)
    except Exception as exc:  # noqa: BLE001 - monitor survives dashboard blips
        log(f"CHECK dashboard_error={type(exc).__name__}: {exc}", log_path)
        rows = []
    # Dashboard age/running flags are not liveness evidence. Probe only the five
    # explicitly monitored experiments, even when the dashboard is unreachable.
    visible = {str(row.get("run_id")): row for row in rows}
    rows = [
        visible.get(run_id, {"run_id": run_id, "state": "dashboard_unavailable"})
        for run_id in ACTIVE_RUN_IDS
    ]
    for row in rows:
        run_id = str(row.get("run_id") or "")
        state = str(row.get("state") or "")
        exit_code = row.get("exit_code")
        log(f"CHECK run={run_id} state={state} phase={row.get('phase')} exit={exit_code}", log_path)
        try:
            resume_one(row, log_path)
        except Exception as exc:
            log(f"RECOVERY error run={run_id} {type(exc).__name__}: {exc}", log_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=3600)
    parser.add_argument("--dashboard-url", default=DEFAULT_URL)
    parser.add_argument("--log", type=Path, default=SUITE / "runs" / "monitor.log")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    lock = args.log.with_suffix(".lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    while True:
        check_once(args.dashboard_url, args.log)
        if args.once:
            return 0
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
