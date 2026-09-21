import csv
import io
import unittest

from clients import billing, dashboard
from exporter import export_rows


def parse(text):
    return list(csv.DictReader(io.StringIO(text)))


class ExportContract(unittest.TestCase):
    def setUp(self):
        self.rows = [{"tenant_id": "a", "customer_id": "C-42", "email": "a@example.invalid"}]

    def test_legacy_bytes(self):
        self.assertEqual(
            billing.render(self.rows),
            "tenant_id,customer_id,email\r\na,C-42,a@example.invalid\r\n",
        )

    def test_alias_and_escaping(self):
        self.assertEqual(
            parse(export_rows([{"tenant_id": "b", "account_id": "x,y", "email": "e"}]))[0],
            {"tenant_id": "b", "customer_id": "x,y", "email": "e"},
        )

    def test_dashboard_privacy_and_stability(self):
        first = dashboard.render(self.rows, "one")
        self.assertNotIn("C-42", first)
        self.assertNotIn("a@example.invalid", first)
        self.assertEqual(first, dashboard.render(self.rows, "one"))
        original = parse(first)[0]["customer_id"]
        self.assertTrue(original)
        self.assertNotEqual(original, parse(dashboard.render(self.rows, "two"))[0]["customer_id"])
        other = [dict(self.rows[0], tenant_id="b")]
        self.assertNotEqual(original, parse(dashboard.render(other, "one"))[0]["customer_id"])
        alias = [{"tenant_id": "a", "account_id": "C-42", "email": "changed"}]
        self.assertEqual(original, parse(dashboard.render(alias, "one"))[0]["customer_id"])

    def test_blank_salt(self):
        with self.assertRaises(ValueError):
            export_rows(self.rows, anonymize=True, salt="")
