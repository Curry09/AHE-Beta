# Spec-0071/T3: one public v2 experiment command surface.
"""Operator-facing commands with credential-free lifecycle receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from auto_designer.experiment import runtime


def _emit(*, payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _prepare_progress(payload: dict) -> None:
    detail = (
        f"log: {payload['preparation_log']}"
        if payload.get("preparation_log")
        else f"frozen materials: {payload['run_dir']}"
    )
    print(
        f"[prepare] run {payload['run_id']} · preparing environment; {detail}",
        file=sys.stderr,
        flush=True,
    )


def _batch_progress(payload: dict) -> None:
    """Spec-0074/T3: progress stays on stderr, leaving JSON stdout parseable."""
    counts = payload.get("counts", {})
    detail = (
        f"active {counts.get('active', 0)} · pending {counts.get('pending', 0)} · "
        f"completed {counts.get('completed', 0)}"
        if counts
        else payload.get("entry_id", "freezing members")
    )
    for entry_id, item in payload.get("entries", {}).items():
        progress = item.get("last_status", {}).get("progress", {})
        round_no = progress.get("current_round")
        current = progress.get("rounds", {}).get(str(round_no), {})
        users = current.get("users", {})
        if users.get("expected"):
            detail += (
                f" · {entry_id} R{round_no}: {users.get('completed', 0)}/{users['expected']}"
                f" sessions completed, {users.get('running', 0)} running"
            )
    print(
        f"[batch] {payload['batch_id']} · "
        f"{payload.get('batch_state', payload.get('phase', 'working'))} · {detail}",
        file=sys.stderr,
        flush=True,
    )


def _dispatch_batch(args: argparse.Namespace) -> dict:
    # Spec-0074/T3: the existing entry owns both single-run and batch commands.
    from auto_designer.experiment import batch

    if args.batch_cmd == "check":
        return batch.check_batch(
            config_path=args.config, offline=args.offline, secrets_file=args.secrets_file
        )
    if args.batch_cmd == "prepare":
        return batch.prepare_batch(
            config_path=args.config,
            root=args.runs_dir,
            secrets_file=args.secrets_file,
            progress=_batch_progress,
        )
    common = {
        "batch_id": args.batch_id,
        "root": args.runs_dir,
        "secrets_file": args.secrets_file,
    }
    if args.batch_cmd in {"run", "resume"}:
        return batch.run_batch(
            **common, resume_batch=args.batch_cmd == "resume", progress=_batch_progress
        )
    return {
        "status": batch.status_batch,
        "stop": batch.stop_batch,
        "collect": batch.collect_batch,
    }[args.batch_cmd](**common)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="experiment", description="Unified local/E2B experiment controller"
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--secrets-file", type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "prepare"):
        item = sub.add_parser(name)
        item.add_argument("--config", type=Path, required=True)
        item.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
        item.add_argument("--grading-plan", type=Path)
        item.add_argument("--grading-worker-public-key", type=Path)
        if name == "check":
            item.add_argument("--offline", action="store_true")
            item.add_argument("--probe-models", action="store_true")
    for name in ("run", "status", "logs", "stop", "resume", "collect", "destroy"):
        item = sub.add_parser(name)
        item.add_argument("run_id", nargs="?" if name == "run" else None)
        if name == "run":
            item.add_argument("--config", type=Path)
        item.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
        if name == "logs":
            item.add_argument("--tail", type=int, default=100)
            item.add_argument("--follow", action="store_true")
        if name == "stop":
            item.add_argument("--grace-seconds", type=float, default=30)
        if name == "destroy":
            item.add_argument("--confirm", required=True)
            item.add_argument("--discard-uncollected", action="store_true")
    worker = sub.add_parser(
        "assessment-worker", help="Grade sealed sessions on a trusted Docker host"
    )
    worker.add_argument("run_id")
    worker.add_argument("--plan", type=Path, required=True)
    worker.add_argument("--signing-key", type=Path, required=True)
    worker.add_argument("--follow", action="store_true")
    worker.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
    dashboard = sub.add_parser("dashboard", help="View one local run or collected E2B snapshot")
    dashboard.add_argument("run_id")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    dashboard.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
    # Spec-0075/T3: post-run grading never starts a controller or reads credentials.
    grade = sub.add_parser("grade", help="Grade original collected sessions using a private --plan")
    grade.add_argument("run_id")
    grade.add_argument("--plan", type=Path, required=True, help="Private grading-plan-v1 JSON")
    grade.add_argument("--round", dest="round_no", type=int)
    grade.add_argument("--offline", action="store_true")
    # Spec-0076/T2: source adapters emit the existing task recipe, without provisioning.
    task = sub.add_parser("task", help="Convert seed cards or text into ordinary task packages")
    task_commands = task.add_subparsers(dest="task_cmd", required=True)
    seeds = task_commands.add_parser("import-seeds", help="Import explicitly provided seed cards")
    seeds.add_argument("library", type=Path)
    seeds.add_argument("--seed", dest="seed_ids", action="append")
    text = task_commands.add_parser("from-text", help="Create a task from a text instruction")
    text.add_argument("--instruction", type=Path, required=True)
    text.add_argument("--id", dest="task_id", required=True)
    text.add_argument("--not-in-benchmark", action="store_true", required=True)
    for item in (seeds, text):
        item.add_argument("--output", type=Path, required=True)
        item.add_argument(
            "--interaction", choices=("direct", "simulated_user"), default="simulated_user"
        )
    # Spec-0074/T3: explicit lists, without a second launcher or executor DSL.
    batch = sub.add_parser("batch", help="Manage a frozen list of experiment configurations")
    commands = batch.add_subparsers(dest="batch_cmd", required=True)
    for name in ("check", "prepare", "run", "status", "stop", "resume", "collect"):
        item = commands.add_parser(name)
        item.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
        if name in {"check", "prepare"}:
            item.add_argument("--config", type=Path, required=True)
        else:
            item.add_argument("batch_id")
        if name == "check":
            item.add_argument("--offline", action="store_true")
    return parser


def dispatch(argv: list[str] | None = None) -> int:
    import time

    from auto_designer.experiment.config import ConfigError

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "task":
            from auto_designer.experiment.task_import import import_seed_tasks, import_text_task

            if args.task_cmd == "import-seeds":
                result = import_seed_tasks(
                    library=args.library,
                    output=args.output,
                    seed_ids=args.seed_ids,
                    interaction=args.interaction,
                )
            else:
                result = import_text_task(
                    instruction=args.instruction,
                    task_id=args.task_id,
                    output=args.output,
                    not_in_benchmark=args.not_in_benchmark,
                    interaction=args.interaction,
                )
            _emit(payload=result, as_json=args.json)
            return 0
        elif args.cmd == "batch":
            result = _dispatch_batch(args)
            _emit(payload=result, as_json=args.json)
            if result.get("batch_state") == "INTERRUPTED":
                return 130
            return 1 if result.get("ok") is False else 0
        elif args.cmd == "assessment-worker":
            from auto_designer.experiment.assessment_worker import run_worker

            result = run_worker(
                run_id=args.run_id,
                root=args.runs_dir,
                plan_path=args.plan,
                signing_key=args.signing_key,
                secrets_file=args.secrets_file,
                follow=args.follow,
            )
            _emit(payload=result, as_json=args.json)
            return 0
        elif args.cmd == "grade":
            from auto_designer.experiment.grading import grade_run

            result = grade_run(
                run_id=args.run_id,
                root=args.runs_dir,
                plan=args.plan,
                round_no=args.round_no,
                offline=args.offline,
            )
            _emit(payload=result, as_json=args.json)
            return 1 if result.get("ok") is False else 0
        elif args.cmd == "check":
            result = runtime.check_v2(
                config_path=args.config,
                offline=args.offline,
                secrets_file=args.secrets_file,
                probe_models=args.probe_models,
                grading_plan=args.grading_plan,
                grading_worker_public_key=args.grading_worker_public_key,
            )
            # Resolved material configuration is public, provider credentials never are.
        elif args.cmd == "prepare":
            result = runtime.prepare_v2(
                config_path=args.config,
                root=args.runs_dir,
                secrets_file=args.secrets_file,
                progress=_prepare_progress,
                grading_plan=args.grading_plan,
                grading_worker_public_key=args.grading_worker_public_key,
            )
        else:
            if args.cmd == "run":
                if bool(args.run_id) == bool(args.config):
                    raise ConfigError(
                        "run requires either a prepared run ID or --config, exclusively"
                    )
                if args.config:
                    prepared = runtime.prepare_v2(
                        config_path=args.config,
                        root=args.runs_dir,
                        secrets_file=args.secrets_file,
                        progress=_prepare_progress,
                    )
                    args.run_id = prepared["run_id"]
            common = {
                "run_id": args.run_id,
                "root": args.runs_dir,
                "secrets_file": args.secrets_file,
            }
            if args.cmd in {"run", "resume"}:
                result = runtime.run_v2(**common, resume_run=args.cmd == "resume")
            elif args.cmd == "status":
                result = runtime.status_v2(**common)
            elif args.cmd == "stop":
                result = runtime.stop_v2(**common, grace_seconds=args.grace_seconds)
            elif args.cmd == "collect":
                result = runtime.collect_v2(**common)
            elif args.cmd == "destroy":
                result = runtime.destroy_v2(
                    **common, confirm=args.confirm, discard_uncollected=args.discard_uncollected
                )
            elif args.cmd == "dashboard":
                from auto_designer.experiment.dashboard import serve_dashboard

                serve_dashboard(**common, host=args.host, port=args.port)
                return 0
            elif args.cmd == "logs":
                if args.tail < 1:
                    raise ConfigError("--tail must be positive")
                previous = ""
                while True:
                    snapshot = runtime.logs_v2(**common, tail=args.tail)
                    if snapshot != previous:
                        # Keep the longest previous suffix matching the new prefix
                        # so a rotating tail does not replay all old lines.
                        old, new = (
                            previous.splitlines(keepends=True),
                            snapshot.splitlines(keepends=True),
                        )
                        overlap = next(
                            (
                                n
                                for n in range(min(len(old), len(new)), 0, -1)
                                if old[-n:] == new[:n]
                            ),
                            0,
                        )
                        print("".join(new[overlap:]), end="", flush=True)
                        previous = snapshot
                    if not args.follow:
                        return 0
                    state = runtime.status_v2(**common)
                    if (
                        state["experiment_state"] in {"COMPLETED", "STOPPED", "FAILED", "LOST"}
                        and state["observation"] != "UNKNOWN"
                    ):
                        return 0
                    time.sleep(2)
        _emit(payload=result, as_json=args.json)
        return 0
    except KeyboardInterrupt:
        # Stopping the log viewer does not stop a detached controller.
        return 130
    except (ConfigError, OSError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            message = str(exc)
        else:
            message = "Command failed; check input paths, runtime logs and provider connectivity"
        _emit(payload={"error": message}, as_json=args.json)
        return 2


def main() -> int:
    return dispatch(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
