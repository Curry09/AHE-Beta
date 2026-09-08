"""Exercise the seed's recorder without an LLM or platform monkeypatch."""

import importlib.util
import json
import time
from pathlib import Path


def observer_type():
    path = Path(__file__).resolve().parents[1] / "observability.py"
    spec = importlib.util.spec_from_file_location("seed_observability_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Observer


def test_seed_records_metadata_and_preserves_process_restarts(tmp_path):
    cls = observer_type()
    for _ in range(2):
        recorder = cls(str(tmp_path))
        recorder.event("attempt_started", attempt_id="test")
        recorder.event("attempt_failed", attempt_id="test", error_type="TimeoutError")
        recorder.close()
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    logs = list(tmp_path.glob("runtime-*.jsonl"))
    assert len(logs) == 2
    for log in logs:
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        assert rows[0]["event"] == "process_started"
        assert rows[-1]["event"] == "process_stopped"
        assert rows[2]["error_type"] == "TimeoutError"


def test_budget_drops_are_explicit_and_calls_do_not_wait_for_disk(tmp_path):
    recorder = observer_type()(str(tmp_path), max_bytes=256)
    began = time.monotonic()
    for _ in range(3000):
        recorder.event("span_started", span_id="s" * 100)
    assert time.monotonic() - began < 2
    recorder.close()
    assert recorder.dropped > 0
    assert recorder.path.stat().st_size <= 256
    assert json.loads((tmp_path / "manifest.json").read_text())["status"] == "partial"


def test_observation_setup_failure_does_not_raise(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("file")
    recorder = observer_type()(str(target))
    recorder.event("attempt_started")
    recorder.close()
    assert recorder.error and not recorder.enabled
