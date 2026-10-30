"""File relay for sequential requests to one persistent, unchanged Harness."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from budget_protocol import TaskBudget
from stdio import HarnessStdioSession, harness_environment


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False))
    temp.replace(path)


def main():
    root = Path(os.environ.get("SIM_RELAY_ROOT", "/opt/frozen-harness/interaction"))
    logs = Path(os.environ.get("SIM_LOG_ROOT", "/logs/agent"))
    root.mkdir(parents=True, exist_ok=True)
    env = harness_environment(
        work_dir=os.environ["SANDBOX_WORK_DIR"],
        model=os.environ["LLM_MODEL"],
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        parent=os.environ,
    )
    mode = os.environ.get("HARNESS_FORWARD_TIME_ADAPTATION", "1")
    if mode not in {"0", "1"}:
        raise ValueError("Invalid time adaptation mode")
    forward_time_adaptation = mode == "1"
    env.pop("HARNESS_FORWARD_TIME_ADAPTATION", None)
    if not forward_time_adaptation:
        env.pop("HARNESS_EXECUTION_CONTRACT", None)
        env.pop("HARNESS_TASK_DEADLINE_UNIX", None)
    session = HarnessStdioSession(
        [
            sys.executable,
            "-E",
            "-s",
            "-u",
            os.environ.get("SIM_ENTRY", "/opt/frozen-harness/source/entry.py"),
        ],
        cwd=os.environ.get("SIM_SOURCE", "/opt/frozen-harness/source"),
        env=env,
        transcript_path=logs / "harness-transcript.jsonl",
        stderr_path=logs / "harness-stderr.log",
    )
    started = time.monotonic()
    budget = TaskBudget.from_environment(os.environ)
    deadline = budget.deadline
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(15):
            print(
                f"[transport] simulated-user relay alive {int(time.monotonic() - started)}s",
                flush=True,
            )

    threading.Thread(target=heartbeat, daemon=True).start()
    record = {
        "normal_reply": False,
        "event_count": 0,
        "reply_characters": 0,
        "request_count": 0,
        "termination_reason": None,
    }
    atomic_json(root / "ready.json", {"ready": True})
    try:
        n = 0
        while time.monotonic() < deadline:
            if (root / "stop.json").exists():
                break
            message = root / f"request-{n}.json"
            if not message.exists():
                time.sleep(0.1)
                continue
            value = json.loads(message.read_text())
            conditions = budget.frame() if forward_time_adaptation else None
            with (logs / "budget-dispatch.jsonl").open("a") as evidence:
                evidence.write(
                    json.dumps(
                        {
                            **(conditions or {}),
                            "time_adaptation": forward_time_adaptation,
                            "execution_conditions_forwarded": forward_time_adaptation,
                            "controller_remaining_seconds": budget.remaining(),
                        }
                    )
                    + "\n"
                )
            reply = session.request(
                value["text"],
                timeout=max(0.01, budget.remaining()),
                execution_conditions=conditions,
            )
            response = {
                "text": reply.text,
                "failed": reply.failed,
                "timed_out": reply.timed_out,
                "elapsed_seconds": reply.elapsed_seconds,
            }
            atomic_json(root / f"reply-{n}.json", response)
            (logs / "harness-reply.txt").write_text(reply.text)
            record["request_count"] += 1
            record["event_count"] += len(reply.events)
            record["reply_characters"] += len(reply.text)
            record["normal_reply"] = not reply.failed
            if reply.failed:
                record["termination_reason"] = (
                    "TimeoutError"
                    if budget.remaining() <= 0
                    else "HarnessSelfTimeout"
                    if reply.timed_out
                    else "HarnessExecutionError"
                )
                break
            n += 1
        else:
            record["termination_reason"] = "TimeoutError"
    except TimeoutError:
        if budget.remaining() > 0.1:
            raise
        record["termination_reason"] = "TimeoutError"
        record["deadline_reached"] = True
    except Exception as error:
        record["termination_reason"] = type(error).__name__
        atomic_json(root / "error.json", {"error": type(error).__name__})
        raise
    finally:
        stopped.set()
        session.close()
        record["elapsed_seconds"] = time.monotonic() - started
        atomic_json(logs / "harness-driver-result.json", record)
        atomic_json(root / "closed.json", record)


if __name__ == "__main__":
    main()
