import argparse
import json
import os
import sys
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from evaluation.harness.stdio import HarnessStdioSession
from evaluation.preparation import freeze_harness


class Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(request)
        schema = next(
            t["function"]["parameters"]
            for t in request["tools"]
            if t["function"]["name"] == "complete_task"
        )
        arguments = {"result": "OFFLINE_FIXTURE_COMPLETED"}
        for key in schema.get("required", []):
            if key == "result":
                continue
            kind = schema["properties"][key].get("type")
            arguments[key] = (
                []
                if kind == "array"
                else {}
                if kind == "object"
                else False
                if kind == "boolean"
                else ""
            )
        full = {
            "id": "local-fixture",
            "object": "chat.completion",
            "created": 1,
            "model": "fixture-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": "full fixture reasoning " * 1000,
                        "tool_calls": [
                            {
                                "id": "fixture-tool",
                                "type": "function",
                                "function": {
                                    "name": "complete_task",
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        if request.get("stream"):
            message = full["choices"][0]["message"]
            chunk = {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "reasoning_content": message["reasoning_content"],
                            "tool_calls": [{"index": 0, **message["tool_calls"][0]}],
                        },
                        "finish_reason": None,
                    }
                ],
            }
            end = {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "usage": full["usage"],
            }
            body = (
                "data: "
                + json.dumps(chunk)
                + "\n\ndata: "
                + json.dumps(end)
                + "\n\ndata: [DONE]\n\n"
            ).encode()
            content_type = "text/event-stream"
        else:
            body = json.dumps(full).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


parser = argparse.ArgumentParser(
    description="Offline adapter smoke test; no E2B or external model calls"
)
parser.add_argument("--harness-root", type=Path, default=Path("../harnesses"))
parser.add_argument("--stream", choices=["native", "false"], default="native")
args = parser.parse_args()
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
results = []
try:
    with tempfile.TemporaryDirectory(prefix="framework-smoke-") as temp:
        root = Path(temp)
        for name in ["v0", "u8", "u8-direct", "u16", "u32"]:
            archive = freeze_harness(name, args.harness_root / name, root / "cache", {})
            source = root / name
            source.mkdir()
            with tarfile.open(archive["archive"]) as t:
                t.extractall(source, filter="data")
            work = root / (name + "-work")
            work.mkdir()
            logs = root / (name + "-logs")
            logs.mkdir()
            env = {
                **os.environ,
                "LLM_MODEL": "fixture-model",
                "LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                "LLM_API_KEY": "offline-fixture-key",
                "SANDBOX_WORK_DIR": str(work),
                "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
                "HARNESS_LOG_DIR": str(logs),
                "HARNESS_OBSERVATION_DIR": str(logs / "observations"),
                "HARNESS_LLM_OPTIONS_JSON": json.dumps(
                    {
                        "max_output_tokens": 65536,
                        "timeout_seconds": 90,
                        "reasoning_effort": "max",
                        "stream": "native" if args.stream == "native" else False,
                        "thinking": True,
                    }
                ),
            }
            with HarnessStdioSession(
                [sys.executable, "-u", str(source / "entry.py")],
                cwd=source,
                env=env,
                transcript_path=logs / "harness-transcript.jsonl",
                stderr_path=logs / "stderr.log",
            ) as s:
                try:
                    reply = s.request(
                        "Return OFFLINE_FIXTURE_COMPLETED using complete_task. Do not invoke shell tools.",
                        timeout=40,
                    )
                except Exception as e:
                    print(
                        name,
                        type(e).__name__,
                        (logs / "stderr.log").read_text()[-6000:],
                    )
                    raise
            traces = logs / "full-call-traces/actor"
            responses = list(traces.glob("*.response.body"))
            events = [
                json.loads(line) for line in (traces / "events.jsonl").read_text().splitlines()
            ]
            tool_events = [e for e in events if e["event"].startswith("tool_")]
            assert "OFFLINE_FIXTURE_COMPLETED" in reply.text, (name, reply.text)
            assert responses and all(
                "full fixture reasoning " * 1000 in p.read_text() for p in responses
            )
            assert any(e["event"] == "tool_started" for e in tool_events), (
                name,
                events,
            )
            assert any(e["event"] == "tool_finished" for e in tool_events), (
                name,
                events,
            )
            assert all(
                q["max_tokens"] == 65536 and q["reasoning_effort"] == "max" for q in Handler.calls
            )
            results.append(
                {
                    "harness": name,
                    "reply": reply.text[:80],
                    "captured_responses": len(responses),
                    "tool_events": len(tool_events),
                    "stream_mode": args.stream,
                }
            )
            print(json.dumps(results[-1]), flush=True)
finally:
    server.shutdown()
Path("offline-smoke-" + args.stream + ".json").write_text(
    json.dumps(
        {"provider": "local fixture; no external model calls", "results": results},
        indent=2,
    )
    + "\n"
)
