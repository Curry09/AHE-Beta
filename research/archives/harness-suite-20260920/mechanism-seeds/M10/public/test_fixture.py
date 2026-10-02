import json
import unittest
from pathlib import Path

from sync import apply_messages


class FixtureRegression(unittest.TestCase):
    def test_replay_fixture(self):
        messages = json.loads(Path("messages.json").read_text())
        self.assertEqual(
            apply_messages(messages),
            {"invoice-7": {"version": 2, "value": "paid"}},
        )
