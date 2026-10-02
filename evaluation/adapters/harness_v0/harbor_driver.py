#!/usr/bin/env python3
"""Run a two-turn harness-v0 session inside one Harbor task environment."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from llm_user_simulator import generate_followup
from stdio import HarnessStdioSession, harness_environment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--harness-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--followup-file")
    parser.add_argument("--llm-user-simulator", action="store_true")
    parser.add_argument("--user-simulator-output")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="total trial wall-clock budget shared by every conversation turn",
    )
    args = parser.parse_args()
    if args.followup_file and args.llm_user_simulator:
        parser.error("--followup-file and --llm-user-simulator are mutually exclusive")
    if args.llm_user_simulator and not args.user_simulator_output:
        parser.error("--llm-user-simulator requires --user-simulator-output")

    instruction = Path(args.instruction_file).read_text(encoding="utf-8")
    followup = ""
    if args.followup_file:
        followup = Path(args.followup_file).read_text(encoding="utf-8").strip()
    env = harness_environment(work_dir=args.work_dir, parent=os.environ)
    session = HarnessStdioSession(
        [args.python, "-u", str(Path(args.harness_dir) / "entry.py")],
        cwd=args.harness_dir,
        env=env,
        transcript_path=args.transcript,
        stderr_path=args.stderr,
    )
    replies = []
    deadline = time.monotonic() + args.timeout

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError(f"trial exhausted its total {args.timeout:.1f}s agent budget")
        return seconds

    try:
        first = session.request(instruction, timeout=remaining())
        replies.append({"turn": 0, "text": first.text, "elapsed_seconds": first.elapsed_seconds})
        if args.llm_user_simulator:
            audit = generate_followup(
                instruction=instruction,
                agent_reply=first.text,
                model=os.environ["USER_SIMULATOR_MODEL"],
                api_key=os.environ["LLM_API_KEY"],
                base_url=os.environ["LLM_BASE_URL"],
            )
            Path(args.user_simulator_output).write_text(
                json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            followup = audit["followup"]
        if followup:
            second = session.request(followup, timeout=remaining())
            replies.append(
                {"turn": 1, "text": second.text, "elapsed_seconds": second.elapsed_seconds}
            )
    finally:
        session.close()
    print(json.dumps({"replies": replies}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
