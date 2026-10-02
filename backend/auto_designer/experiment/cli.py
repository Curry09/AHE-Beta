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
    dashboard = sub.add_parser("dashboard", help="View one local run or collected E2B snapshot")
    dashboard.add_argument("run_id")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    dashboard.add_argument("--secrets-file", type=Path, default=argparse.SUPPRESS)
    return parser


def dispatch(argv: list[str] | None = None) -> int:
    import time

    from auto_designer.experiment.config import ConfigError

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
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
