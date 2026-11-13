"""Real pinned NexAU + real shell, local HTTP fixtures; no paid APIs or E2B."""

import json
import os
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from evaluation.configuration import Configuration, ConfigurationError
from evaluation.harness.ahe import materialize, verify_source
from evaluation.harness.ahe_entry import configure
from evaluation.harness.stdio import HarnessStdioSession
from evaluation.preparation import freeze_harness
from evaluation.usage import collect


def test_protocol_and_budget_validation(tmp_path):
    raw = {
        "version": 1,
        "harnesses": ["ahe"],
        "actor": {"base_url": "https://fixture.invalid/v1", "api_type": "openai_responses"},
    }
    c = Configuration.from_mapping(raw, tmp_path / "evaluation.yaml")
    assert c.data["actor"]["api_type"] == "openai_responses"
    raw["execution"] = {"time_adaptation": True}
    with pytest.raises(ConfigurationError, match="remaining-time"):
        Configuration.from_mapping(raw, tmp_path / "evaluation.yaml")
    raw["execution"] = {}
    raw["harnesses"] = ["v0"]
    with pytest.raises(ConfigurationError, match="only"):
        Configuration.from_mapping(raw, tmp_path / "evaluation.yaml")


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        state = self.server.state
        state["calls"].append({"path": self.path, "body": payload})
        index = len(state["calls"])
        if state["fail"]:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"fixture API rejected request","type":"invalid_request_error"}}'
            )
            return
        tool = index == 1
        args = json.dumps(
            {
                "command": "printf AHE_TOOL_OK > proof.txt",
                "description": "Write a local test artifact",
                "dir_path": state["work"],
            }
        )
        if self.path.endswith("/responses"):
            call = {
                "id": "fc_fixture",
                "type": "function_call",
                "name": "run_shell_command",
                "call_id": "call_fixture",
                "arguments": args,
                "status": "completed",
            }
            message = {
                "id": f"msg_{index}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": f"AHE_REPLY_{index}", "annotations": []}
                ],
            }
            reasoning = {
                "id": f"rs_{index}",
                "type": "reasoning",
                "summary": [
                    {"type": "summary_text", "text": "FULL_FIXTURE_REASONING_" + "x" * 12000}
                ],
            }
            response = {
                "id": f"resp_{index}",
                "object": "response",
                "created_at": 1,
                "model": "fixture-model",
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "output": [reasoning, call if tool else message],
                "parallel_tool_calls": True,
                "tools": [],
                "tool_choice": "auto",
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 20},
                    "output_tokens": 30,
                    "output_tokens_details": {"reasoning_tokens": 10},
                    "total_tokens": 130,
                },
            }
            events = [
                {
                    "type": "response.created",
                    "response": {**response, "output": [], "status": "in_progress"},
                }
            ]
            for oi, item in enumerate(response["output"]):
                events.extend(
                    [
                        {"type": "response.output_item.added", "output_index": oi, "item": item},
                        {"type": "response.output_item.done", "output_index": oi, "item": item},
                    ]
                )
            events.append({"type": "response.completed", "response": response})
            for i, event in enumerate(events):
                event["sequence_number"] = i
            body = (
                "".join(
                    "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events
                ).encode()
                if payload.get("stream")
                else json.dumps(response).encode()
            )
        else:
            msg = {
                "role": "assistant",
                "content": None if tool else f"AHE_REPLY_{index}",
                "reasoning_content": "FULL_FIXTURE_REASONING_" + "x" * 12000,
            }
            if tool:
                msg["tool_calls"] = [
                    {
                        "id": "call_fixture",
                        "type": "function",
                        "function": {"name": "run_shell_command", "arguments": args},
                    }
                ]
            body = json.dumps(
                {
                    "id": f"chat_{index}",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "fixture-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": msg,
                            "finish_reason": "tool_calls" if tool else "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 30,
                        "total_tokens": 130,
                        "prompt_tokens_details": {"cached_tokens": 20},
                        "completion_tokens_details": {"reasoning_tokens": 10},
                    },
                }
            ).encode()
        self.send_response(200)
        self.send_header(
            "Content-Type", "text/event-stream" if payload.get("stream") else "application/json"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.parametrize(
    "api,stream,fail",
    [
        ("native", "native", False),
        ("openai_responses", False, False),
        ("openai_chat_completion", False, False),
        ("native", "native", True),
    ],
)
def test_real_agent_tool_feedback_and_capture(tmp_path, api, stream, fail):
    pytest.importorskip("nexau")
    source = materialize(tmp_path / "ahe")
    before = {p: (source / p).read_bytes() for p in verify_source(source)["upstream_files"]}
    frozen = freeze_harness("ahe", source, tmp_path / "cache", {})
    run = tmp_path / "run"
    run.mkdir()
    with tarfile.open(frozen["archive"]) as archive:
        archive.extractall(run, filter="data")
    work = tmp_path / "task"
    work.mkdir()
    logs = tmp_path / "logs"
    state = {"calls": [], "work": str(work), "fail": fail}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    options = {
        "max_output_tokens": 65536,
        "reasoning_effort": "max",
        "stream": stream,
        "thinking": True,
        "timeout_seconds": 1800,
        "api_type": api,
    }
    env = {
        **os.environ,
        "LLM_MODEL": "fixture-model",
        "LLM_API_KEY": "offline-fixture-secret-key",
        "LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "HARNESS_LOG_DIR": str(logs),
        "SANDBOX_WORK_DIR": str(work),
        "HARNESS_LLM_OPTIONS_JSON": json.dumps(options),
    }
    try:
        with HarnessStdioSession(
            [sys.executable, "-u", str(run / "entry.py")],
            cwd=run,
            env=env,
            transcript_path=logs / "harness-transcript.jsonl",
            stderr_path=logs / "stderr.log",
        ) as session:
            first = session.request(
                "Write proof.txt in the task directory, then report completion.", timeout=45
            )
            if fail:
                assert first.failed
                assert state["calls"]
                return
            assert not first.failed, first.text
            assert first.text == "AHE_REPLY_2"
            assert (work / "proof.txt").read_text() == "AHE_TOOL_OK"
            followup = session.request("Feedback: confirm the artifact you just wrote.", timeout=30)
            assert not followup.failed and followup.text == "AHE_REPLY_3"
        assert len(state["calls"]) == 3
        final_payload = state["calls"][-1]["body"]
        assert "AHE_REPLY_2" in json.dumps(final_payload)
        assert "Feedback: confirm" in json.dumps(final_payload)
        for call in state["calls"]:
            body = call["body"]
            assert body.get("max_tokens", body.get("max_output_tokens")) == 65536
            if api != "openai_chat_completion":
                assert call["path"] == "/v1/responses"
                assert body["reasoning"]["effort"] == "max"
                assert "reasoning_effort" not in body and "thinking" not in body
            else:
                assert body["reasoning_effort"] == "max"
                assert "reasoning" not in body and body["thinking"] == {"type": "enabled"}
        trace = logs / "full-call-traces/actor"
        assert len(list(trace.glob("*.response.body"))) == 3
        assert any(
            b"FULL_FIXTURE_REASONING_" + b"x" * 12000 in p.read_bytes()
            for p in trace.glob("*.response.body")
        )
        events = [json.loads(line) for line in (trace / "events.jsonl").read_text().splitlines()]
        assert any(
            e["event"] == "tool_started" and e["inputs"]["command"].startswith("printf AHE_TOOL_OK")
            for e in events
        )
        assert any(e["event"] == "tool_finished" for e in events)
        assert collect(logs)["actor_tokens"] == 390  # includes cache/reasoning exactly once
        assert collect(logs)["coverage"]["actor"]["usage_complete"]
        resolved = json.loads((logs / "resolved-llm-options.json").read_text())
        assert resolved["effective_llm_config"]["stream_idle_timeout_ms"] == 1800000
        assert "offline-fixture-secret-key" not in "".join(
            p.read_text(errors="replace") for p in logs.rglob("*") if p.is_file()
        )
        assert (logs / "ahe-native-spans.json").exists()
        assert before == {p: (source / p).read_bytes() for p in before}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_timeout_is_not_an_independent_120_second_limit(monkeypatch):
    pytest.importorskip("nexau")
    from nexau.archs.llm.llm_config import LLMConfig

    monkeypatch.setenv("LLM_MODEL", "fixture-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1/v1")
    monkeypatch.setenv("LLM_API_KEY", "fixture")
    from evaluation.harness.ahe import ARTIFACT

    raw = yaml.safe_load((ARTIFACT / "code_agent.yaml").read_text())
    options = {
        "max_output_tokens": 65536,
        "timeout_seconds": 1800,
        "reasoning_effort": "max",
        "stream": "native",
    }
    generated = configure(raw, options)
    llm = generated["llm_config"]
    assert llm["stream"] is True
    llm["api_key"] = "fixture"
    timeout = LLMConfig(**llm).to_client_kwargs()["timeout"]
    assert timeout.read == 1800 and timeout.write == 1800 and timeout.connect == 15
