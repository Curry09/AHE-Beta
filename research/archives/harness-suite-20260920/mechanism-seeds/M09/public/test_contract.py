import tempfile
import unittest
from pathlib import Path

from report import build_report


class ReportContract(unittest.TestCase):
    def test_unavailable_pdf_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                build_report([{"name": "A", "amount": 3}], Path(root) / "out.pdf")

    def test_offline_html_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "out.html"
            build_report([{"name": "A", "amount": 3}], output, renderer="html")
            self.assertIn("A", output.read_text())
            self.assertIn("3", output.read_text())
