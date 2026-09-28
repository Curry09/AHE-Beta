"""Portable in-sandbox driver for direct or heartbeat-supervised trials."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from .harness.adapters import get_adapter
from .harness.session import HarnessSession
from .interactions.direct import DirectInteraction
from .interactions.simulated_user import (
    OpenAICompatibleUserPolicy,
    SimulatedUserInteraction,
)

DEFAULT_PERSONA = """You are a demanding but fair user of an autonomous task agent.
Judge only the public task, visible progress, and assistant replies. While work is
running, wait when concrete progress is visible; send a concise correction when the
agent is drifting; interrupt only when continuing is clearly harmful. After a reply,
accept only when it credibly satisfies the task, otherwise ask for a concrete fix or
verification. Never refer to hidden tests, gold answers, or grader criteria."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--harness-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--mode", choices=("direct", "simulated_user"), required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=90.0)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--max-heartbeats", type=int)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--persona-file")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--user-trace")
    args = parser.parse_args(argv)

    task = Path(args.instruction_file).read_text(encoding="utf-8")
    env = {
        **os.environ,
        "SANDBOX_WORK_DIR": args.work_dir,
        "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
        "PYTHONUNBUFFERED": "1",
    }
    session = HarnessSession(
        [args.python, "-u", str(Path(args.harness_dir) / "entry.py")],
        cwd=args.harness_dir,
        env=env,
        adapter=get_adapter(args.adapter),
        transcript_path=args.transcript,
        stderr_path=args.stderr,
    )
    policy = None
    try:
        if args.mode == "direct":
            interaction = DirectInteraction()
        else:
            persona = (
                Path(args.persona_file).read_text(encoding="utf-8")
                if args.persona_file
                else DEFAULT_PERSONA
            )
            policy = OpenAICompatibleUserPolicy(
                model=os.environ["USER_SIMULATOR_MODEL"],
                api_key=os.environ["LLM_API_KEY"],
                base_url=os.environ["LLM_BASE_URL"],
                persona=persona,
                seed=args.seed,
            )
            interaction = SimulatedUserInteraction(
                policy,
                heartbeat_seconds=args.heartbeat_seconds,
                max_turns=args.max_turns,
                max_heartbeats=args.max_heartbeats,
            )
        result = interaction.run(session, task, args.timeout)
        payload = {
            "end_reason": result.end_reason,
            "elapsed_seconds": result.elapsed_seconds,
            "normal_final_reply": result.normal_final_reply,
            "replies": [
                {
                    **asdict(reply),
                    "terminal_kind": reply.terminal_kind.value,
                    "events": [dict(event.payload) for event in reply.events],
                }
                for reply in result.replies
            ],
            "user_actions": result.user_actions,
            "progress": result.progress,
        }
        Path(args.result).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if policy is not None and args.user_trace:
            Path(args.user_trace).write_text(
                json.dumps(policy.calls, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 0
    finally:
        session.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
