"""Frozen Harness stdio protocol tests."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.harness.stdio import HarnessProtocolError, HarnessStdioSession, reply_timed_out

FAKE_HARNESS = r"""
import json
import sys

turn = 0
for raw in sys.stdin:
    obj = json.loads(raw)
    turn += 1
    print(json.dumps({"type": "usage", "success": True, "error": None}), flush=True)
    print(json.dumps({"type": "progress", "kind": "tool", "text": f"turn-{turn}"}), flush=True)
    print(json.dumps({"type": "reply", "text": f"reply:{obj['text']}:{turn}"}), flush=True)
"""


def test_stdio_session_keeps_one_process_across_turns(tmp_path: Path) -> None:
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE_HARNESS, encoding="utf-8")
    transcript = tmp_path / "trace.jsonl"
    session = HarnessStdioSession(
        [sys.executable, "-u", str(fake)],
        cwd=tmp_path,
        transcript_path=transcript,
        stderr_path=tmp_path / "stderr.log",
    )
    try:
        first = session.request("one", timeout=5)
        pid = session.pid
        second = session.request("two", timeout=5)
        assert session.pid == pid
    finally:
        session.close()
    assert first.text == "reply:one:1"
    assert second.text == "reply:two:2"
    assert [event["type"] for event in first.events] == ["usage", "progress", "reply"]
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert [row["direction"] for row in rows].count("controller") == 2


def test_stdio_session_reports_early_exit(tmp_path: Path) -> None:
    fake = tmp_path / "exit.py"
    fake.write_text("pass\n", encoding="utf-8")
    session = HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path)
    with pytest.raises(HarnessProtocolError):
        session.request("hello", timeout=5)
    session.close()


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "reply", "text": "Model unavailable", "status": "crashed"},
        {"type": "reply", "text": "[harness error] Unexpected OpenAI response type"},
        {"reply": "[harness error] stream did not receive any valid chunks"},
    ],
)
def test_zero_exit_error_reply_is_retained_as_failure(tmp_path, frame):
    fake = tmp_path / "failure.py"
    fake.write_text(
        "import sys\nsys.stdin.readline()\nprint(" + repr(json.dumps(frame)) + ", flush=True)\n"
    )
    with HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path) as session:
        reply = session.request("Do the task", timeout=5)
    assert reply.failed
    assert reply.text == frame.get("text", frame.get("reply"))


def test_normal_reply_quoting_error_marker_is_preserved(tmp_path):
    fake = tmp_path / "normal.py"
    frame = {"type": "reply", "text": "The previous [harness error] is fixed."}
    fake.write_text(
        "import sys\nsys.stdin.readline()\nprint(" + repr(json.dumps(frame)) + ", flush=True)\n"
    )
    with HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path) as session:
        reply = session.request("Summarize", timeout=5)
    assert not reply.failed


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "reply", "text": "[timeout] Single-call watchdog stopped this turn."},
        {"reply": "[timeout] The internal budget was exhausted."},
        {"type": "reply", "status": "timed_out", "text": "Internal deadline reached."},
        {
            "type": "reply",
            "text": "[harness error] empty reply",
            "receipt": {
                "unit_closes": [
                    {"kind": "llm_call", "close_kind": "unit_timeout", "duration_ms": 300000}
                ]
                * 4
            },
        },
    ],
)
def test_internal_watchdog_timeout_is_not_a_normal_reply(tmp_path, frame):
    fake = tmp_path / "timeout.py"
    fake.write_text(
        "import sys\nsys.stdin.readline()\nprint(" + repr(json.dumps(frame)) + ", flush=True)\n"
    )
    with HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path) as session:
        reply = session.request("Do the task", timeout=5)
    assert reply.timed_out and reply.failed
    assert reply.text == frame.get("text", frame.get("reply"))


@pytest.mark.parametrize(
    "frame",
    [
        {"text": "I fixed the previous [timeout] condition."},
        {"text": "[harness error] timeout reading a task file"},
        {"text": "[harness error] failed", "receipt": {"unit_closes": []}},
        {
            "text": "Completed after a retry",
            "receipt": {"unit_closes": [{"kind": "llm_call", "close_kind": "unit_timeout"}]},
        },
        {
            "text": "[harness error] failed",
            "receipt": {
                "unit_closes": [
                    {"kind": "llm_call", "close_kind": "unit_timeout"},
                    {"kind": "llm_call", "close_kind": "error"},
                ]
            },
        },
    ],
)
def test_timeout_words_or_prior_retry_do_not_establish_internal_timeout(frame):
    assert not reply_timed_out(frame)


@pytest.fixture
def window_timeout_frame():
    closes = [
        {"unit_id": "u1", "kind": "llm_call", "close_kind": "completed"},
        {"unit_id": "u2", "kind": "command", "close_kind": "completed"},
        {"unit_id": "u3", "kind": "llm_call", "close_kind": "unit_timeout"},
    ]
    attribution = {"unit": {"closes": closes}}
    return deepcopy(
        {
            "type": "reply",
            "text": "I still need the calculation tool; let me install it.",
            "window_id": "w_00000001",
            "attribution": attribution,
            "receipt": {"unit_closes": closes, "attribution": attribution},
        }
    )


def test_final_typed_watchdog_close_overrides_stale_assistant_reply(tmp_path, window_timeout_frame):
    fake = tmp_path / "stale.py"
    frame = window_timeout_frame
    fake.write_text(
        "import sys\nsys.stdin.readline()\nprint(" + repr(json.dumps(frame)) + ", flush=True)\n"
    )
    with HarnessStdioSession([sys.executable, str(fake)], cwd=tmp_path) as session:
        reply = session.request("Complete the task", timeout=5)
    assert reply.timed_out and reply.failed
    assert reply.text == frame["text"]


@pytest.mark.parametrize(
    "change",
    [
        "recovered",
        "command_timeout",
        "missing_mirror",
        "conflicting_mirror",
        "duplicate_unit",
        "unknown_kind",
        "error_close",
        "explicit_status",
        "no_window",
    ],
)
def test_incomplete_or_recovered_unit_receipts_do_not_override_reply(window_timeout_frame, change):
    frame = window_timeout_frame
    closes = frame["receipt"]["unit_closes"]
    if change == "recovered":
        closes.append({"unit_id": "u4", "kind": "llm_call", "close_kind": "completed"})
    elif change == "command_timeout":
        closes[-1]["kind"] = "command"
    elif change == "missing_mirror":
        del frame["attribution"]
    elif change == "conflicting_mirror":
        frame["attribution"] = {"unit": {"closes": []}}
    elif change == "duplicate_unit":
        closes[-1]["unit_id"] = "u1"
    elif change == "unknown_kind":
        closes[0]["kind"] = "unknown"
    elif change == "error_close":
        closes[0]["close_kind"] = "error"
    elif change == "explicit_status":
        frame["status"] = "completed"
    elif change == "no_window":
        del frame["window_id"]
    assert not reply_timed_out(frame)
