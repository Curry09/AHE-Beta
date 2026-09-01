# Spec-0047/T4：experiment CLI（create/plan/preflight/start/status/stop/resume/archive/destroy）。
"""Operator-facing commands. Mutating commands print a secret-free plan first."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from auto_designer.experiment import runtime
from auto_designer.experiment.config import experiments_root
from auto_designer.experiment.manifest import last_state, read_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="experiment", description="并行实验运行时")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create")
    create.add_argument("--config", type=Path, required=True)
    for name in ("plan", "preflight", "start", "status", "stop", "resume", "archive"):
        item = sub.add_parser(name)
        item.add_argument("experiment_id")
    destroy = sub.add_parser("destroy")
    destroy.add_argument("experiment_id")
    destroy.add_argument("--confirm", required=True)
    return parser


def _emit(*, payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def dispatch(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = experiments_root()
    cmd = args.cmd
    if cmd == "create":
        result = runtime.create(config_path=args.config, root=root)
        _emit(
            payload={"action": "create", **{k: result[k] for k in ("experiment_id", "root")}},
            as_json=args.json,
        )
        return 0
    experiment_id = args.experiment_id
    if cmd == "plan":
        _emit(payload=runtime.plan(experiment_id=experiment_id, root=root), as_json=args.json)
        return 0
    if cmd == "preflight":
        _emit(payload=runtime.preflight(experiment_id=experiment_id, root=root), as_json=args.json)
        return 0
    if cmd == "start":
        plan = runtime.plan(experiment_id=experiment_id, root=root)
        _emit(payload={"action": "start", **plan}, as_json=args.json)
        ctx = runtime.start(experiment_id=experiment_id, root=root)
        _emit(payload={"running": True, "compose_project": ctx.compose_project}, as_json=args.json)
        return 0
    if cmd == "status":
        from auto_designer.experiment.config import experiment_paths

        paths = experiment_paths(experiment_id=experiment_id, root=root)
        payload = {
            "experiment_id": experiment_id,
            "state": last_state(path=paths["journal"]),
            "manifest": read_manifest(path=paths["manifest"]),
        }
        _emit(payload=payload, as_json=args.json)
        return 0
    if cmd == "stop":
        runtime.stop(experiment_id=experiment_id, root=root)
        _emit(payload={"action": "stop", "experiment_id": experiment_id}, as_json=args.json)
        return 0
    if cmd == "resume":
        ctx = runtime.resume(experiment_id=experiment_id, root=root)
        _emit(
            payload={"action": "resume", "compose_project": ctx.compose_project}, as_json=args.json
        )
        return 0
    if cmd == "archive":
        dest = runtime.archive(experiment_id=experiment_id, root=root)
        _emit(payload={"action": "archive", "path": str(dest)}, as_json=args.json)
        return 0
    if cmd == "destroy":
        runtime.destroy(experiment_id=experiment_id, confirm=args.confirm, root=root)
        _emit(payload={"action": "destroy", "experiment_id": experiment_id}, as_json=args.json)
        return 0
    parser.error(f"未知命令 {cmd}")
    return 2


def main() -> int:
    return dispatch(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
