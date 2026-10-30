"""One configuration for preparation, execution and recovery."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .config import PlanError
from .configuration import load
from .report import summarize_run


@contextmanager
def _run_lock(root):
    import fcntl

    with (root / "controller.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PlanError("Another controller owns this run") from error
        yield


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        prog="harbor-eval", description="Single-configuration Harbor Index evaluation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare", "plan", "run"):
        p = commands.add_parser(name)
        p.add_argument("--config", type=Path, default=Path("evaluation.yaml"))
        if name in ("plan", "run"):
            p.add_argument(
                "--new-run",
                action="store_true",
                help="Explicitly create a new run identity",
            )
        if name == "run":
            p.add_argument("--env-file", type=Path)
    for name in ("resume", "report", "review", "regrade"):
        p = commands.add_parser(name)
        p.add_argument("run_root", type=Path)
        if name != "report":
            p.add_argument("--env-file", type=Path, default=Path(".env"))
        if name == "regrade":
            p.add_argument("--trial", required=True)
    args = parser.parse_args(argv)
    if args.command in ("validate", "prepare", "plan", "run"):
        config = load(args.config)
        config.validate_sources()
        if args.command == "validate":
            output = {
                "configuration": "valid",
                "tasks": len(config.task_names()),
                "harnesses": config.data["harnesses"],
                "trials": len(config.task_names())
                * len(config.data["harnesses"])
                * config.data["execution"]["repetitions"],
                "paid_calls": 0,
            }
        elif args.command == "prepare":
            from .preparation import prepare

            _, cases, _, harnesses = prepare(config)
            output = {
                "prepared_tasks": len(cases),
                "harnesses": [h["id"] for h in harnesses],
                "paid_calls": 0,
            }
        else:
            from .preparation import plan

            manifest, root = plan(config, new_run=args.new_run)
            output = {
                "run_root": str(root),
                "trials": len(manifest["trials"]),
                "manifest_digest": manifest["manifest_digest"],
            }
            if args.command == "run":
                from .runner import execute

                env_file = args.env_file or config.source.parent / ".env"
                print(
                    json.dumps({"starting": str(root), "trials": len(manifest["trials"])}),
                    flush=True,
                )
                with _run_lock(root):
                    output = execute(manifest, root, env_file)
    else:
        root = args.run_root.resolve()
        manifest = json.loads((root / "manifest.json").read_text())
        if args.command == "report":
            output = summarize_run(root)
        else:
            with _run_lock(root):
                if args.command == "resume":
                    from .runner import execute

                    output = execute(manifest, root, args.env_file)
                elif args.command == "review":
                    from .runner import review_saved

                    output = review_saved(manifest, root, args.env_file)
                else:
                    from .credentials import preflight
                    from .harbor.executor import HarborExecutor

                    preflight(manifest, args.env_file)
                    output = HarborExecutor(manifest, root, args.env_file).regrade(args.trial)
                    summarize_run(root)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0
