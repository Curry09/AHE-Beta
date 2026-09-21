"""CLI for plan validation, freezing, execution, resume, and reports."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .benchmarks import get_plugin
from .config import load_plan
from .manifest import freeze_manifest
from .orchestrator import Orchestrator
from .report import compare_runs, summarize_run
from .schema import PlanError


def _framework_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _resolve(plan) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for case in plan.cases:
        plugin = get_plugin(case.benchmark)
        spec = plugin.resolve_case(case, plan.fallback_agent_timeout_seconds)
        for interaction in plan.interactions:
            if interaction.mode not in spec.supported_interactions:
                raise PlanError(
                    f"{case.benchmark}/{case.task_id} does not support {interaction.mode.value}"
                )
        resolved[f"{case.benchmark}/{case.task_id}"] = {
            "agent_timeout_seconds": spec.budget.agent_timeout_seconds,
            "outer_agent_timeout_seconds": spec.budget.outer_agent_timeout_seconds,
            "agent_timeout_source": spec.budget.agent_source,
            "verifier_timeout_seconds": spec.budget.verifier_timeout_seconds,
            "environment_build_timeout_seconds": spec.budget.environment_build_timeout_seconds,
            "clock": spec.budget.clock,
            "resources": dict(spec.resources),
            "grader_isolation": spec.grader.isolation,
        }
    return resolved


def _plan(path: str, output_root: str) -> tuple[dict[str, Any], Path]:
    plan = load_plan(path)
    resolved = _resolve(plan)
    manifest = freeze_manifest(plan, framework_commit=_framework_commit(), resolved_cases=resolved)
    run_root = Path(output_root) / manifest["run_id"]
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("manifest_digest") != manifest["manifest_digest"]:
            raise PlanError("run id collision with different manifest")
    else:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return manifest, run_root


def _load_callable(path: str):
    module_name, separator, attribute = path.partition(":")
    if not separator:
        raise PlanError("executor must use module:function syntax")
    return getattr(importlib.import_module(module_name), attribute)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hbench")
    parser.add_argument("--output-root", default="evaluation/runs")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("plan")
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("plan")
    run = sub.add_parser("run")
    run.add_argument("plan")
    run.add_argument("--executor", required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("run_root")
    resume.add_argument("--executor", required=True)
    summarize = sub.add_parser("summarize")
    summarize.add_argument("run_root")
    compare_cmd = sub.add_parser("compare")
    compare_cmd.add_argument("left")
    compare_cmd.add_argument("right")
    args = parser.parse_args(argv)

    if args.command == "validate":
        plan = load_plan(args.plan)
        plan.validate_local_artifacts()
        _resolve(plan)
        print("PLAN_VALID")
        return 0
    if args.command == "plan":
        manifest, root = _plan(args.plan, args.output_root)
        print(json.dumps({"run_root": str(root), "manifest": manifest}, ensure_ascii=False))
        return 0
    if args.command == "run":
        manifest, root = _plan(args.plan, args.output_root)
        summary = Orchestrator(manifest, root, _load_callable(args.executor)).run()
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    if args.command == "resume":
        root = Path(args.run_root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        summary = Orchestrator(manifest, root, _load_callable(args.executor)).run()
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    if args.command == "summarize":
        print(json.dumps(summarize_run(args.run_root), ensure_ascii=False))
        return 0
    print(json.dumps(compare_runs(args.left, args.right), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
