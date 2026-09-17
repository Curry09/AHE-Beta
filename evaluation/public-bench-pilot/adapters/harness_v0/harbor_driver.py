#!/usr/bin/env python3
"""Run a two-turn harness-v0 session inside one Harbor task environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stdio import HarnessStdioSession, harness_environment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--harness-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--instruction-file", required=True)
    parser.add_argument("--followup-file")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--stderr", required=True)
    parser.add_argument("--timeout", type=float, default=360.0)
    args = parser.parse_args()

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
    try:
        first = session.request(instruction, timeout=args.timeout)
        replies.append({"turn": 0, "text": first.text, "elapsed_seconds": first.elapsed_seconds})
        if followup:
            second = session.request(followup, timeout=args.timeout)
            replies.append(
                {"turn": 1, "text": second.text, "elapsed_seconds": second.elapsed_seconds}
            )
    finally:
        session.close()
    print(json.dumps({"replies": replies}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
