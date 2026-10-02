import unittest

from sync import apply_messages


class Smoke(unittest.TestCase):
    def test_simple_insert(self):
        result = apply_messages([{"id": "a", "version": 1, "value": "x"}])
        self.assertEqual(result["a"]["value"], "x")
