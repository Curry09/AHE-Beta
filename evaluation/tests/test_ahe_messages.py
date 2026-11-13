"""Actual pinned AHE agent, signed thinking, real shell and complete feedback turn."""

import json
import os
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evaluation.harness.ahe import materialize
from evaluation.harness.stdio import HarnessStdioSession
from evaluation.preparation import freeze_harness
from evaluation.usage import collect, response_usage, total

THINKING = "REPLAY_SIGNED_THINKING_" + "x" * 14000
SIGNATURE = "fixture-provider-signed-thinking"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path == "/v1/messages"
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append(q)
        index = len(self.server.calls)
        limit = self.server.limit
        tool = index == 1 and not limit
        blocks = [{"type": "thinking", "thinking": THINKING, "signature": SIGNATURE}]
        if not limit:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": "fixture_call",
                    "name": "run_shell_command",
                    "input": {
                        "command": "printf MESSAGES_AHE_OK > proof.txt",
                        "description": "Write integration test artifact",
                        "dir_path": self.server.work,
                    },
                }
                if tool
                else {"type": "text", "text": f"MESSAGES_REPLY_{index}"}
            )
        stop = "max_tokens" if limit else "tool_use" if tool else "end_turn"
        start_usage = {
            "input_tokens": 100,
            "output_tokens": 0,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 3,
        }
        message = {
            "id": f"msg_{index}",
            "type": "message",
            "role": "assistant",
            "model": "fixture-model",
            "content": blocks,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {**start_usage, "output_tokens": 30},
        }
        events = [
            {
                "type": "message_start",
                "message": {**message, "content": [], "stop_reason": None, "usage": start_usage},
            }
        ]
        for idx, b in enumerate(blocks):
            if b["type"] == "thinking":
                events.extend(
                    [
                        {
                            "type": "content_block_start",
                            "index": idx,
                            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                        },
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {"type": "thinking_delta", "thinking": b["thinking"]},
                        },
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {"type": "signature_delta", "signature": b["signature"]},
                        },
                    ]
                )
            elif b["type"] == "tool_use":
                events.extend(
                    [
                        {
                            "type": "content_block_start",
                            "index": idx,
                            "content_block": {**b, "input": {}},
                        },
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": json.dumps(b["input"]),
                            },
                        },
                    ]
                )
            else:
                events.extend(
                    [
                        {
                            "type": "content_block_start",
                            "index": idx,
                            "content_block": {"type": "text", "text": ""},
                        },
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {"type": "text_delta", "text": b["text"]},
                        },
                    ]
                )
            events.append({"type": "content_block_stop", "index": idx})
        events.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 30},
                },
                {"type": "message_stop"},
            ]
        )
        body = (
            "".join(
                "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events
            ).encode()
            if q.get("stream")
            else json.dumps(message).encode()
        )
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream" if q.get("stream") else "application/json"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.parametrize("stream,limit", [(True, False), (False, False), (True, True)])
def test_real_messages_tool_and_thinking_replay(tmp_path, stream, limit):
    pytest.importorskip("nexau")
    source = materialize(tmp_path / "ahe")
    frozen = freeze_harness("ahe", source, tmp_path / "cache", {})
    run = tmp_path / "run"
    run.mkdir()
    with tarfile.open(frozen["archive"]) as archive:
        archive.extractall(run, filter="data")
    work = tmp_path / "work"
    work.mkdir()
    logs = tmp_path / "logs"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls = []
    server.work = str(work)
    server.limit = limit
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    options = {
        "api_type": "anthropic_chat_completion",
        "max_output_tokens": 65536,
        "reasoning_effort": "max",
        "thinking": True,
        "stream": stream,
        "timeout_seconds": 1800,
    }
    env = {
        **os.environ,
        "LLM_MODEL": "fixture-model",
        "LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}",
        "LLM_API_KEY": "offline-fixture-key",
        "HARNESS_LOG_DIR": str(logs),
        "SANDBOX_WORK_DIR": str(work),
        "HARNESS_LLM_OPTIONS_JSON": json.dumps(options),
    }
    try:
        with HarnessStdioSession(
            [sys.executable, "-u", str(run / "entry.py")],
            cwd=run,
            env=env,
            stderr_path=logs / "stderr.log",
            transcript_path=logs / "transcript.jsonl",
        ) as session:
            first = session.request("Write proof.txt and report completion.", timeout=40)
            if limit:
                assert first.failed
                assert first.events[-1]["failure_kind"] == "model_output_limit"
                assert "max_tokens" in first.text
                return
            assert not first.failed, first.text
            assert (
                first.text == "MESSAGES_REPLY_2"
                and (work / "proof.txt").read_text() == "MESSAGES_AHE_OK"
            )
            second = session.request("Feedback: confirm the file again.", timeout=20)
            assert not second.failed and second.text == "MESSAGES_REPLY_3"
        assert len(server.calls) == 3
        for q in server.calls:
            assert (
                q["max_tokens"] == 65536
                and q["reasoning_effort"] == "max"
                and q["thinking"] == {"type": "enabled"}
            )
            assert "reasoning" not in q
        q = server.calls[1]
        assistant = [m for m in q["messages"] if m["role"] == "assistant"][0]
        thinking = [b for b in assistant["content"] if b["type"] == "thinking"]
        assert thinking == [{"type": "thinking", "thinking": THINKING, "signature": SIGNATURE}]
        assert any(
            b.get("type") == "tool_result"
            for m in q["messages"]
            if m["role"] == "user"
            for b in m["content"]
            if isinstance(b, dict)
        )
        usage = collect(logs)
        assert usage["actor_tokens"] == 459 and usage["coverage"]["actor"]["usage_complete"]
        assert len(list((logs / "full-call-traces/actor").glob("*.response.body"))) == 3
        resolved = json.loads((logs / "resolved-llm-options.json").read_text())[
            "effective_llm_config"
        ]
        assert resolved["stream_idle_timeout_ms"] == 1800000 and resolved["timeout"] == 1800
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_partial_messages_usage_is_not_reported_complete(tmp_path):
    f = tmp_path / "full-call-traces/actor"
    f.mkdir(parents=True)
    (f / "one.request.body").write_text("{}")
    body = (
        "data: "
        + json.dumps(
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 20,
                    }
                },
            }
        )
        + "\n\n"
    )
    (f / "one.response.body").write_text(body)
    u = collect(tmp_path)
    assert u["actor_tokens"] == 120 and not u["coverage"]["actor"]["usage_complete"]


def test_completed_messages_usage_merges_start_and_delta():
    events = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 3,
                    "output_tokens": 0,
                }
            },
        },
        {"type": "message_delta", "usage": {"output_tokens": 30}},
        {"type": "message_stop"},
    ]
    raw = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
    u = response_usage(raw)
    assert total(u) == 153 and u["_complete"]


def test_missing_artifact_exact_paths_are_classified(tmp_path):
    from evaluation.harbor.grading import grade_issues

    verifier = tmp_path / "verifier"
    verifier.mkdir()
    (verifier / "reward.json").write_text('{"reward":0}')
    (verifier / "test-stdout.txt").write_text("candidate tests failed")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text('[{"source":"/app/output","status":"failed"}]')
    log = tmp_path / "trial.log"
    case = {"benchmark": "Harbor", "task_id": "fixture"}
    for message in [
        "FileNotFoundException: path '/app/output' does not exist",
        "FileNotFoundException: path not found: lstat /app/output: no such file or directory",
    ]:
        log.write_text(message)
        assert not grade_issues(case, {"reward": 0}, verifier)
    log.write_text(
        "FileNotFoundException: path not found: lstat /app/different: no such file or directory"
    )
    assert grade_issues(case, {"reward": 0}, verifier)
