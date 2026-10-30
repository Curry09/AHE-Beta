from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evaluation.adapters.harness_v0.llm_user_simulator import _content_text
from evaluation.adapters.harness_v0.stdio import HarnessProtocolError, HarnessStdioSession

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


def test_user_simulator_content_normalization() -> None:
    assert _content_text(" verify this ") == "verify this"
    assert _content_text([{"type": "text", "text": "one"}, {"text": "two"}]) == "one\ntwo"
    assert _content_text(None) == ""


@pytest.mark.parametrize("payload", [{"reply": "done"}, {"error": "failed"}])
def test_stdio_session_rejects_untyped_events(tmp_path, payload):
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import json,sys\nfor raw in sys.stdin:\n    print("
        + repr(json.dumps(payload))
        + ",flush=True)\n"
    )
    with HarnessStdioSession([sys.executable, "-u", str(fake)], cwd=tmp_path) as session:
        with pytest.raises(HarnessProtocolError, match="type"):
            session.request("one", timeout=2)
