#!/usr/bin/env python3
"""Fail-closed parallel controller for the frozen mixed scaling matrix.

Dry-run and preflight are useful today. A real start additionally requires a
trusted per-N runtime receipt and an executor command supplied by that bundle.
The controller never silently substitutes the N=1 SWE-only runner for N>1.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
CONFIG = SUITE / "configs" / "scaling-e2b-20260922.json"
MIXED = SUITE / "configs" / "mixed-scaling-20260922.json"
ASSIGNMENTS = SUITE / "configs" / "mixed-scaling-20260922.tasks.json"
ROLES = SUITE / "configs" / "n1-e2b-20260922.json"
NS = (1, 4, 8, 16, 32)


class LaunchGateError(RuntimeError):
    pass


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def selected(raw: str) -> list[int]:
    values = NS if raw == "all" else sorted({int(item) for item in raw.split(",") if item.strip()})
    if not values or any(value not in NS for value in values):
        raise LaunchGateError(f"--n 只能是 {','.join(map(str, NS))} 或 all")
    return values


def plan(ns: list[int]) -> list[dict]:
    membership = load(MIXED)["scaling_sets"]
    rows = load(ASSIGNMENTS)["tasks"]
    by_key = {str(row["task_key"]): row for row in rows}
    result = []
    for n in ns:
        keys = list(membership[f"N{n}"])
        tasks = [by_key[key] for key in keys]
        result.append(
            {
                "n": n,
                "experiment_id": f"hse-n{n}-e2b-20260922",
                "task_count": len(tasks),
                "task_keys": keys,
                "simulated_user": sum(item["interaction"] == "simulated_user" for item in tasks),
                "direct": sum(item["interaction"] == "direct" for item in tasks),
                "ordinary": sum(item["stratum"] == "ordinary" for item in tasks),
                "mechanism": sum(item["stratum"] == "mechanism" for item in tasks),
                "runtime_receipt": str(
                    SUITE / "prepared" / "scaling-e2b-20260922" / f"n{n}" / "receipt.json"
                ),
            }
        )
    return result


def validate_roles() -> list[str]:
    config = load(ROLES)
    roles = config.get("roles") or {}
    errors = []
    for name in ("harness", "user_simulator", "triager", "designer", "developer", "owner"):
        if name not in roles:
            errors.append(f"角色配置缺失：{name}")
    for name in ("harness", "user_simulator", "triager", "designer", "developer"):
        role = roles.get(name) or {}
        for field in ("provider", "model", "protocol"):
            if not role.get(field):
                errors.append(f"{name}.{field} 缺失")
    if roles.get("owner", {}).get("llm") is not False:
        errors.append("owner 必须是 mechanical / llm=false")
    return errors


def gate(rows: list[dict]) -> list[str]:
    errors = validate_roles()
    mixed = load(MIXED)
    assignment = load(ASSIGNMENTS)
    launch = load(CONFIG)["launch_gate"]
    if mixed.get("status") != "launchable":
        errors.append(f"mixed config status={mixed.get('status')!r}，不是 launchable")
    if assignment.get("status") != "frozen":
        errors.append(f"task assignment status={assignment.get('status')!r}，不是 frozen")
    for row in rows:
        receipt = Path(row["runtime_receipt"])
        if not receipt.is_file():
            errors.append(f"N{row['n']} 缺 runtime receipt：{receipt}")
        else:
            document = load(receipt)
            if document.get("status") != "ready":
                errors.append(f"N{row['n']} runtime receipt status={document.get('status')!r}")
    if not launch.get("preflight_all_selected_before_any_start"):
        errors.append("配置未开启 all-selected preflight gate")
    return errors


def redacted(rows: list[dict]) -> dict:
    role_config = load(ROLES)["roles"]
    return {
        "config": str(CONFIG),
        "assignments": str(ASSIGNMENTS),
        "provider": load(CONFIG)["provider"],
        "rounds": load(CONFIG)["rounds"],
        "roles": role_config,
        "experiments": rows,
        "credentials": "not loaded by dry-run/preflight",
    }


def run_one(row: dict, command: list[str], resume: bool) -> dict:
    n = row["n"]
    formatted = [item.replace("{n}", str(n)).replace("{experiment_id}", row["experiment_id"]) for item in command]
    process = subprocess.Popen(
        formatted,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "HSE_SCALING_N": str(n), "HSE_SCALING_EXPERIMENT_ID": row["experiment_id"],
             "HSE_SCALING_ACTION": "resume" if resume else "fresh"},
    )
    stdout, _ = process.communicate()
    path = SUITE / "runs" / "scaling-e2b-20260922" / f"n{n}" / "controller.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stdout, encoding="utf-8")
    return {"n": n, "experiment_id": row["experiment_id"], "returncode": process.returncode, "log": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", default="all", help="comma-separated N values or all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-launch", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--executor", help="trusted bundle command, supports {n} and {experiment_id}")
    args = parser.parse_args()
    if args.start and args.resume:
        parser.error("--start 与 --resume 不能同时使用")
    try:
        ns = selected(args.n)
        rows = plan(ns)
        if args.dry_run or not (args.check_launch or args.start or args.resume):
            print(json.dumps(redacted(rows), ensure_ascii=False, indent=2))
            return 0
        errors = gate(rows)
        if errors:
            for error in errors:
                print("LAUNCH_GATE_ERROR:", error, file=os.sys.stderr)
            return 2
        if not args.executor:
            raise LaunchGateError("--start/--resume 需要 --executor，不能默认替换成 N=1 runner")
        command = shlex.split(args.executor)
        if not command:
            raise LaunchGateError("--executor 不能为空")
        action_resume = bool(args.resume)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(rows)) as pool:
            futures = [pool.submit(run_one, row, command, action_resume) for row in rows]
            results = [future.result() for future in futures]
        print(json.dumps({"started_at": datetime.now(UTC).isoformat(), "results": results}, ensure_ascii=False, indent=2))
        return 0 if all(item["returncode"] == 0 for item in results) else 1
    except (OSError, KeyError, ValueError, json.JSONDecodeError, LaunchGateError) as exc:
        print(f"LAUNCH_ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
