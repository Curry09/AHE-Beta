# Spec-0047/T4：experiment CLI（create/plan/preflight/start/status/stop/resume/archive/destroy）。
"""Operator-facing commands with credential-free lifecycle receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from auto_designer.experiment import runtime
from auto_designer.experiment.config import experiments_root
from auto_designer.experiment.manifest import last_state, read_manifest


def _legacy_parser() -> argparse.ArgumentParser:
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


def _legacy_dispatch(argv: list[str] | None = None) -> int:
    parser = _legacy_parser()
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
        _emit(
            payload={
                "infrastructure_running": True,
                "experiment_controller_started": False,
                "state": "PROVISIONED",
                "compose_project": ctx.compose_project,
            },
            as_json=args.json,
        )
        return 0
    if cmd == "status":
        from auto_designer.experiment.config import experiment_paths

        paths = experiment_paths(experiment_id=experiment_id, root=root)
        payload = {
            "experiment_id": experiment_id,
            "state": "INFRASTRUCTURE_ONLY"
            if last_state(path=paths["journal"]) == "RUNNING"
            else last_state(path=paths["journal"]),
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


# Spec-0069/T5: one public controller CLI; the v1 surface is a migration bridge.
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
    for name in ("create", "plan", "preflight", "start", "archive"):
        item = sub.add_parser(
            name, help="Legacy v1 infrastructure command; use check/prepare/run for v2"
        )
        if name == "create":
            item.add_argument("--config", type=Path, required=True)
        else:
            item.add_argument("run_id")
    return parser


def dispatch(argv: list[str] | None = None) -> int:
    import time

    from auto_designer.experiment.config import ConfigError

    parser = build_parser()
    args = parser.parse_args(argv)
    legacy = args.cmd in {"create", "plan", "preflight", "start", "archive"}
    if args.cmd in {"status", "stop", "resume", "destroy"} and args.runs_dir is None:
        candidate = runtime.runs_root_v2() / args.run_id / "manifest.json"
        legacy_candidate = experiments_root() / args.run_id / "manifest.json"
        legacy = not candidate.is_file() and legacy_candidate.is_file()
    try:
        if legacy:
            print(
                "Legacy v1 command: start provisions infrastructure only. For a complete experiment use check → prepare → run.",
                file=sys.stderr,
            )
            if args.runs_dir:
                raise ConfigError(
                    "Legacy commands use AUTO_DESIGNER_EXPERIMENTS_ROOT, not --runs-dir"
                )
            filtered = list(argv if argv is not None else sys.argv[1:])
            return _legacy_dispatch(filtered)
        if args.cmd == "check":
            result = runtime.check_v2(
                config_path=args.config,
                offline=args.offline,
                secrets_file=args.secrets_file,
                probe_models=args.probe_models,
            )
            # Resolved material configuration is public, provider credentials never are.
        elif args.cmd == "prepare":
            result = runtime.prepare_v2(
                config_path=args.config,
                root=args.runs_dir,
                secrets_file=args.secrets_file,
                progress=_prepare_progress,
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
