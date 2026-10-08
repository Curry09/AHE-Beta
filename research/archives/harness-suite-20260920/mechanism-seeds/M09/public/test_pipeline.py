import json
import tempfile
import unittest
from pathlib import Path

from pipeline import load_rows, run_pipeline


class PipelineContract(unittest.TestCase):
    def test_loader_validates_schema(self):
        rows = load_rows(Path("daily_sales.csv"), ["name", "amount"])
        self.assertEqual(len(rows), 2)

    def test_pipeline_does_not_fake_pdf(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            for name in ("daily_sales.csv", "schedule.json"):
                (root_path / name).write_text(Path(name).read_text())
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                run_pipeline(root_path / "schedule.json", root_path)

    def test_pipeline_accepts_documented_html_replan(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            for name in ("daily_sales.csv",):
                (root_path / name).write_text(Path(name).read_text())
            config = {
                "source": "daily_sales.csv",
                "renderer": "html",
                "output_dir": "reports",
                "required_fields": ["name", "amount"],
            }
            config_path = root_path / "schedule.json"
            config_path.write_text(json.dumps(config))
            output = run_pipeline(config_path, root_path)
            self.assertEqual(output, root_path / "reports/daily_sales.html")
            self.assertIn("North", output.read_text())
