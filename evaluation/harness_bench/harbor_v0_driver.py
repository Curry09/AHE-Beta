"""Single-turn driver uploaded by the Harbor harness-v0 adapter."""

from __future__ import annotations

import os
from pathlib import Path

from stdio import HarnessStdioSession, harness_environment


def main() -> int:
    transcript = "/logs/agent/harness-transcript.jsonl"
    stderr = "/logs/agent/harness-stderr.log"
    env = harness_environment(
        work_dir="/app",
        model=os.environ["LLM_MODEL"],
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        parent=os.environ,
    )
    session = HarnessStdioSession(
        [os.environ.get("HARNESS_PYTHON", "python3"), "-u", "/opt/hse-v0/harness/entry.py"],
        cwd="/opt/hse-v0/harness",
        env=env,
        transcript_path=transcript,
        stderr_path=stderr,
    )
    try:
        reply = session.request(
            Path("/tmp/hse-v0-instruction.md").read_text(encoding="utf-8"),
            timeout=1800,
        )
        Path("/logs/agent/harness-v0-reply.txt").write_text(
            reply.text, encoding="utf-8"
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
