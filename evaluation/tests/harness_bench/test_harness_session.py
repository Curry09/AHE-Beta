from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluation.harness_bench.harness.adapters import FROZEN_V0
from evaluation.harness_bench.harness.protocol import TerminalKind
from evaluation.harness_bench.harness.session import HarnessSession

FAKE = r"""
import json, sys
for raw in sys.stdin:
    item = json.loads(raw)
    if item.get("type") == "shutdown":
        break
    if item.get("type") == "interrupt":
        print(json.dumps({"type":"reply","text":"[interrupted] stopped"}), flush=True)
        continue
    print(json.dumps({"type":"progress","kind":"tool","text":"working"}), flush=True)
    text = item["text"]
    reply = "[timeout] stopped" if text == "timeout" else "reply:" + text
    print(json.dumps({"type":"reply","request_id":item.get("request_id"),"text":reply}), flush=True)
"""


def test_session_distinguishes_progress_normal_and_self_timeout(tmp_path: Path) -> None:
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE, encoding="utf-8")
    session = HarnessSession(
        [sys.executable, "-u", str(fake)],
        cwd=tmp_path,
        adapter=FROZEN_V0,
        transcript_path=tmp_path / "trace.jsonl",
    )
    try:
        session.write_message("hello")
        kind, normal = session.poll(5)
        session.write_message("timeout")
        _, timed_out = session.poll(5)
    finally:
        session.shutdown()

    assert kind == "reply"
    assert normal.terminal_kind is TerminalKind.NORMAL
    assert timed_out.terminal_kind is TerminalKind.SELF_TIMEOUT
    assert normal.request_id
    assert session.last_progress[0]["text"] == "working"
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert sum(row["direction"] == "controller" for row in rows) == 3


def test_session_interrupt_uses_the_same_typed_contract(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE)
    transcript = tmp_path / "trace.jsonl"
    with_session = HarnessSession(
        [sys.executable, "-u", str(fake)],
        cwd=tmp_path,
        adapter=FROZEN_V0,
        transcript_path=transcript,
    )
    try:
        reply = with_session.interrupt(timeout=2)
        assert reply is not None
        assert reply.terminal_kind == TerminalKind.INTERRUPTED
    finally:
        with_session.close()
    events = [json.loads(line) for line in transcript.read_text().splitlines()]
    sent = [event["payload"] for event in events if event["direction"] == "controller"]
    assert sent[0] == {"type": "interrupt"}
