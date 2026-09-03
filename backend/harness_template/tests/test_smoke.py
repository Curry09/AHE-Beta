"""harness self-tests: entry surface, /help, and self-contained docs.

These tests belong to the harness product itself. They should stay deterministic and cheap:
no live model endpoint, no user-project fixtures, and no external services.
Run from the harness repository root with:

    python3 -m unittest discover -s tests -p 'test_*.py'
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import queue
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HarnessSmokeTest(unittest.TestCase):
    def test_entry_imports_and_exposes_core_surface(self) -> None:
        entry = importlib.import_module("entry")
        for name in (
            "main",
            "_reply",
            "_run_supervised",
            "_setup_workspace",
            "_build_agent",
            "_snapshot_history",
            "_restore_history",
            "_slash_command",
        ):
            self.assertTrue(
                callable(getattr(entry, name, None)), f"entry.{name} should be callable"
            )

    def test_slash_help_replies_and_keeps_session_open(self) -> None:
        entry = importlib.import_module("entry")
        reply = entry._slash_command("/help")
        self.assertIsNotNone(reply)
        text, should_exit = reply
        self.assertFalse(should_exit)
        self.assertIn("SYNOPSIS", text)
        self.assertIn("COMMANDS", text)
        self.assertIn("/help", text)
        self.assertIn("/exit", text)
        self.assertIn("SANDBOX_WORK_DIR", text)

    def test_slash_exit_quit_are_in_band_dispatch(self) -> None:
        entry = importlib.import_module("entry")
        for raw in ("/exit", "/quit", "/EXIT", "  /Quit  now"):
            reply = entry._slash_command(raw)
            self.assertIsNotNone(reply)
            text, should_exit = reply
            self.assertTrue(text.startswith("[exited]"))
            self.assertTrue(should_exit)
        self.assertIsNone(entry._slash_command("please fix the bug"))
        self.assertIsNone(entry._slash_command("/unknown"))
        self.assertIsNone(entry._slash_command(""))

    def test_interrupt_reply_is_marked(self) -> None:
        entry = importlib.import_module("entry")
        self.assertTrue(entry._INTERRUPT_REPLY.startswith("[interrupted]"))

    def test_supervisor_waits_without_a_wall_clock_deadline(self) -> None:
        entry = importlib.import_module("entry")

        release = threading.Event()

        class SlowAgent:
            def run(self, *, message):
                self.assert_message = message
                release.wait()
                return "finished"

        box = {}
        worker = threading.Thread(
            target=lambda: box.setdefault("out", entry._run_supervised(SlowAgent(), "work", None))
        )
        worker.start()
        time.sleep(0.05)
        self.assertTrue(worker.is_alive(), "slow agent must keep running until completion/interrupt")
        release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(box["out"], "finished")

    def test_status_wire_out_is_user_visible_event(self) -> None:
        entry = importlib.import_module("entry")
        event = entry._wire_out("status", text="[queued] waiting")
        self.assertIn("status", event)
        self.assertIn("[queued]", json.dumps(event, ensure_ascii=False))

    def test_llm_span_emits_machine_usage_without_response_content(self) -> None:
        entry = importlib.import_module("entry")
        from nexau import Span, SpanType

        collector = entry._make_step_collector()
        collector.set_session_id("agent-1")
        span = Span(id="", name="OpenAI chat", type=SpanType.LLM)
        stdout = io.StringIO()
        old_protocol = entry._OUTPUT_PROTOCOL
        entry._OUTPUT_PROTOCOL = entry._V1
        try:
            with contextlib.redirect_stdout(stdout):
                collector.end_span(span, outputs={
                    "id": "req-1", "model": "m",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                              "total_tokens": 14},
                    "choices": [{"message": {"content": "secret answer"}}],
                })
        finally:
            entry._OUTPUT_PROTOCOL = old_protocol
        event = json.loads(stdout.getvalue())
        self.assertEqual(event["type"], "usage")
        self.assertEqual(event["total_tokens"], 14)
        self.assertEqual(event["agent_run_id"], "agent-1")
        self.assertNotIn("secret answer", stdout.getvalue())

    def test_each_llm_span_emits_one_usage_event_including_unavailable(self) -> None:
        entry = importlib.import_module("entry")
        from nexau import Span, SpanType

        collector = entry._make_step_collector()
        stdout = io.StringIO()
        old_protocol = entry._OUTPUT_PROTOCOL
        entry._OUTPUT_PROTOCOL = entry._V1
        try:
            with contextlib.redirect_stdout(stdout):
                collector.end_span(
                    Span(id="one", name="first call", type=SpanType.LLM),
                    outputs={"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}},
                )
                collector.end_span(
                    Span(id="two", name="retry", type=SpanType.LLM),
                    outputs={},
                    error=RuntimeError("provider failed"),
                )
        finally:
            entry._OUTPUT_PROTOCOL = old_protocol

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([event["type"] for event in events], ["usage", "usage"])
        self.assertEqual(events[0]["total_tokens"], 7)
        self.assertEqual(events[0]["usage_source"], "reported")
        self.assertEqual(events[1]["usage_source"], "unavailable")
        self.assertFalse(events[1]["success"])

    def test_concurrent_llm_usage_frames_remain_independent_json_lines(self) -> None:
        entry = importlib.import_module("entry")
        from nexau import Span, SpanType

        collector = entry._make_step_collector()
        stdout = io.StringIO()
        old_protocol = entry._OUTPUT_PROTOCOL
        entry._OUTPUT_PROTOCOL = entry._V1

        def emit(index: int) -> None:
            collector.end_span(
                Span(id=str(index), name=f"call-{index}", type=SpanType.LLM),
                outputs={"usage": {"input_tokens": index, "output_tokens": 1}},
            )

        try:
            with contextlib.redirect_stdout(stdout), ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(emit, range(20)))
        finally:
            entry._OUTPUT_PROTOCOL = old_protocol

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(events), 20)
        self.assertTrue(all(event["type"] == "usage" for event in events))
        self.assertEqual(sorted(event["total_tokens"] for event in events), list(range(1, 21)))

    def test_busy_message_emits_queued_status_and_marks_queue_item(self) -> None:
        entry = importlib.import_module("entry")
        msg_q: queue.Queue = queue.Queue()
        ctrl_q: queue.Queue = queue.Queue()
        busy = threading.Event()
        busy.set()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps({"type": "message", "text": "second"}) + "\n")
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                entry._stdin_reader(msg_q, ctrl_q, busy)
        finally:
            sys.stdin = old_stdin
        item = msg_q.get_nowait()
        self.assertEqual(item["text"], "second")
        self.assertTrue(item["queued"])
        out = stdout.getvalue()
        self.assertIn("queued", out)
        self.assertIn("previous request", out)

    def test_product_docs_present_and_split_by_audience(self) -> None:
        for rel in ("HELP.md", "META_SPEC.md", ".env.example", "requirements.txt"):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} should exist at harness root")
        for rel in ("README.md", "USER.md", "INTERFACE.md", "MANUAL.md"):
            self.assertFalse((ROOT / rel).exists(), f"{rel} should not be shipped in harness root")
        self.assertIn("SYNOPSIS", (ROOT / "HELP.md").read_text(encoding="utf-8"))
        self.assertIn("Meta-Spec", (ROOT / "META_SPEC.md").read_text(encoding="utf-8"))

    def test_scripts_present_with_shebang(self) -> None:
        for rel in ("scripts/run.sh", "scripts/smoke.sh", "scripts/check.sh"):
            path = ROOT / rel
            self.assertTrue(path.is_file(), f"{rel} should exist")
            self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash"))

    def test_product_text_avoids_integration_specific_concepts(self) -> None:
        forbidden = [
            "per" + "sona",
            "feel" + "ing",
            "tri" + "age",
            "sim" + "_trace",
            "user " + "sim" + "ulator",
            "issue " + "tracker",
        ]
        paths = [
            ROOT / "HELP.md",
            ROOT / "META_SPEC.md",
            ROOT / "agents" / "main.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                self.assertNotIn(word, text, f"{path.relative_to(ROOT)} leaks {word!r}")


if __name__ == "__main__":
    unittest.main()
