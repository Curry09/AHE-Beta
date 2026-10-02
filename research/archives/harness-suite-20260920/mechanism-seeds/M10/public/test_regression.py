import unittest

from sync import apply_messages


class Regression(unittest.TestCase):
    def test_out_of_order_does_not_rewind(self):
        result = apply_messages(
            [
                {"id": "a", "version": 2, "value": "new"},
                {"id": "a", "version": 1, "value": "old"},
            ]
        )
        self.assertEqual(result["a"], {"version": 2, "value": "new"})

    def test_duplicate_is_idempotent(self):
        message = {"id": "a", "version": 2, "value": "new"}
        self.assertEqual(apply_messages([message, message]), {"a": {"version": 2, "value": "new"}})

    def test_delete_obeys_version(self):
        result = apply_messages(
            [
                {"id": "a", "version": 2, "value": "new"},
                {"id": "a", "version": 1, "deleted": True},
                {"id": "b", "version": 1, "value": "old"},
                {"id": "b", "version": 2, "deleted": True},
            ]
        )
        self.assertIn("a", result)
        self.assertNotIn("b", result)
