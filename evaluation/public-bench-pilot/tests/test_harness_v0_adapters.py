from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from adapters.harness_v0.llm_user_simulator import _content_text
from adapters.harness_v0.stdio import HarnessProtocolError, HarnessStdioSession

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


def test_tau_marker_regex_accepts_one_json_object() -> None:
    pytest.importorskip("tau2")
    from adapters.harness_v0.tau3 import _CALL_PATTERN, HarnessV0TauAgent
    from tau2.environment.tool import as_tool

    match = _CALL_PATTERN.search(
        '<TAU3_TOOL_CALL>{"name":"lookup","arguments":{"id":7}}</TAU3_TOOL_CALL>'
    )
    assert match is not None
    assert json.loads(match.group(1))["arguments"] == {"id": 7}

    def lookup(id: int) -> str:
        """Look up one record.

        Args:
            id: Record identifier.
        """
        return str(id)

    agent = HarnessV0TauAgent(
        tools=[as_tool(lookup)],
        domain_policy="Use lookup when needed.",
        llm="openrouter/z-ai/glm-5.2",
        api_key="not-used-by-this-unit-test",
    )
    call = agent._parse_tool_call(match.group(0))
    assert call is not None
    assert call.name == "lookup"
    assert call.arguments == {"id": 7}


def test_tau_marker_rejects_unknown_tool() -> None:
    pytest.importorskip("tau2")
    from adapters.harness_v0.tau3 import HarnessV0TauAgent

    agent = HarnessV0TauAgent(
        tools=[],
        domain_policy="",
        llm="openrouter/z-ai/glm-5.2",
        api_key="not-used-by-this-unit-test",
    )
    with pytest.raises(ValueError, match="unknown"):
        agent._parse_tool_call('<TAU3_TOOL_CALL>{"name":"missing","arguments":{}}</TAU3_TOOL_CALL>')
