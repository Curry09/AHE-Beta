"""One direct request to an unchanged frozen Harness, inside the task sandbox."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from budget_protocol import TaskBudget
from stdio import HarnessProtocolError, HarnessStdioSession, harness_environment


def main() -> int:
    env = harness_environment(
        work_dir=os.environ["SANDBOX_WORK_DIR"],
        model=os.environ["LLM_MODEL"],
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        parent=os.environ,
    )
    forward_time = os.environ.get("HARNESS_FORWARD_TIME_ADAPTATION", "0") == "1"
    env.pop("HARNESS_FORWARD_TIME_ADAPTATION", None)
    if not forward_time:
        env.pop("HARNESS_EXECUTION_CONTRACT", None)
        env.pop("HARNESS_TASK_DEADLINE_UNIX", None)
    session = HarnessStdioSession(
        # Ignore task Python import settings for our interpreter only. Keep
        # those variables in env so archived shell tools retain the task setup.
        [sys.executable, "-E", "-s", "-u", "/opt/frozen-harness/source/entry.py"],
        cwd="/opt/frozen-harness/source",
        env=env,
        transcript_path="/logs/agent/harness-transcript.jsonl",
        stderr_path="/logs/agent/harness-stderr.log",
    )
    stopped = threading.Event()
    started = time.monotonic()
    budget = TaskBudget.from_environment(os.environ)

    def transport_heartbeat() -> None:
        # Harness events stay in its transcript. The outer SDK exec stream
        # otherwise remains silent for an entire model turn, making it prone
        # to idle proxy disconnects. This never enters the model conversation.
        while not stopped.wait(15):
            try:
                print(
                    f"[transport] driver alive {int(time.monotonic() - started)}s",
                    flush=True,
                )
            except BrokenPipeError:
                return

    heartbeat = threading.Thread(target=transport_heartbeat, daemon=True)
    heartbeat.start()
    try:
        reply = session.request(
            Path("/opt/frozen-harness/instruction.md").read_text(encoding="utf-8"),
            timeout=max(0.01, budget.remaining()),
            execution_conditions=budget.frame() if forward_time else None,
        )
        Path("/logs/agent/harness-reply.txt").write_text(reply.text, encoding="utf-8")
        Path("/logs/agent/harness-driver-result.json").write_text(
            json.dumps(
                {
                    "elapsed_seconds": reply.elapsed_seconds,
                    "event_count": len(reply.events),
                    "reply_characters": len(reply.text),
                    "normal_reply": not reply.failed,
                    "termination_reason": "HarnessSelfTimeout"
                    if reply.timed_out
                    else "ModelOutputLimit"
                    if any(
                        e.get("type") == "reply" and e.get("failure_kind") == "model_output_limit"
                        for e in reply.events
                    )
                    else "HarnessExecutionError"
                    if reply.failed
                    else None,
                }
            ),
            encoding="utf-8",
        )
    except (TimeoutError, HarnessProtocolError) as error:
        Path("/logs/agent/harness-driver-result.json").write_text(
            json.dumps(
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "termination_reason": type(error).__name__,
                }
            ),
            encoding="utf-8",
        )
        if not isinstance(error, TimeoutError) or budget.remaining() > 0.1:
            raise
    finally:
        stopped.set()
        heartbeat.join(timeout=1)
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
