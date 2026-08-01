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
import unittest
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

    def test_timeout_reply_is_marked_continuable(self) -> None:
        entry = importlib.import_module("entry")
        self.assertTrue(entry._TIMEOUT_REPLY.startswith("[timeout]"))
        self.assertIn("会话上下文已保留", entry._TIMEOUT_REPLY)

    def test_status_wire_out_is_user_visible_event(self) -> None:
        entry = importlib.import_module("entry")
        event = entry._wire_out("status", text="[queued] waiting")
        self.assertIn("status", event)
        self.assertIn("[queued]", json.dumps(event, ensure_ascii=False))

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
        for rel in ("HELP.md", "RUNTIME.md", ".env.example", "requirements.txt"):
            self.assertTrue((ROOT / rel).is_file(), f"{rel} should exist at harness root")
        for rel in ("README.md", "USER.md", "INTERFACE.md", "MANUAL.md"):
            self.assertFalse((ROOT / rel).exists(), f"{rel} should not be shipped in harness root")
        self.assertIn("SYNOPSIS", (ROOT / "HELP.md").read_text(encoding="utf-8"))
        self.assertIn("Runtime", (ROOT / "RUNTIME.md").read_text(encoding="utf-8"))

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
            ROOT / "RUNTIME.md",
            ROOT / "agents" / "main.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                self.assertNotIn(word, text, f"{path.relative_to(ROOT)} leaks {word!r}")


if __name__ == "__main__":
    unittest.main()
