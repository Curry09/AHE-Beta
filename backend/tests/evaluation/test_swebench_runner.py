from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.evaluation.adapters.swebench import _SWEbenchRunner


def test_evaluator_invokes_official_harness_and_records_report(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, json.dumps([{"Id": "sha256:official"}]), "")
        run_id = args[args.index("--run_id") + 1]
        report_dir = Path(args[args.index("--report_dir") + 1])
        report = report_dir / f"auto-designer.{run_id}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps({"resolved_ids": ["sympy__sympy-18199"], "schema_version": 2}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, "official done\n", "")

    monkeypatch.setattr("auto_designer.evaluation.adapters.swebench.subprocess.run", fake_run)
    dataset = tmp_path / "verified.json"
    dataset.write_text(json.dumps([{"instance_id": "sympy__sympy-18199"}]), encoding="utf-8")
    result = _SWEbenchRunner(dataset, tmp_path / "results").evaluate(
        instance_id="sympy__sympy-18199", patch="diff --git a/x b/x\n"
    )
    assert result["fresh"] is True
    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["image_digest"] == "sha256:official"
    assert result["official_report"]["schema_version"] == 2
    assert result["official_report_path"].endswith(f"auto-designer.{result['run_id']}.json")
    normalized = json.loads(Path(result["evaluation_dataset"]).read_text(encoding="utf-8"))
    assert normalized == [{"instance_id": "sympy__sympy-18199"}]
    assert any("swebench.harness.run_evaluation" in call for call in calls)


@pytest.mark.parametrize(
    "report,expected",
    [
        ({"resolved_ids": ["target"]}, ("completed", True)),
        ({"empty_patch_ids": ["target"]}, ("not_evaluated", None)),
        ({"resolved_ids": ["target"], "empty_patch_ids": ["target"]}, ("crashed", False)),
        ({"empty_patch_ids": ["target"], "error_ids": ["target"]}, ("crashed", False)),
        ({"unresolved_ids": ["target"]}, ("completed", False)),
        ({}, ("crashed", False)),
        ({"resolved_ids": ["other"]}, ("crashed", False)),
        ({"resolved_ids": ["target"], "unresolved_ids": ["target"]}, ("crashed", False)),
        ({"resolved_ids": ["target"], "error_ids": ["target"]}, ("crashed", False)),
        ({"unresolved_ids": ["target"], "incomplete_ids": ["target"]}, ("crashed", False)),
        ({"unresolved_ids": ["target"], "missing_ids": ["target"]}, ("crashed", False)),
        ({"resolved_ids": "target"}, ("crashed", False)),
        ({"resolved_ids": ["target", "target"]}, ("crashed", False)),
        (["target"], ("crashed", False)),
        ("malformed", ("crashed", False)),
    ],
)
def test_official_report_requires_unambiguous_target_classification(
    tmp_path, monkeypatch, report, expected
):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([{"instance_id": "target"}]))

    def fake_run(args, **kwargs):
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 1, "", "image absent")
        run_id = args[args.index("--run_id") + 1]
        report_dir = Path(args[args.index("--report_dir") + 1])
        (report_dir / f"auto-designer.{run_id}.json").write_text(
            "not JSON" if report == "malformed" else json.dumps(report)
        )
        return subprocess.CompletedProcess(args, 0, "done", "")

    monkeypatch.setattr("auto_designer.evaluation.adapters.swebench.subprocess.run", fake_run)
    result = _SWEbenchRunner(dataset, tmp_path / "results").evaluate(instance_id="target", patch="")
    assert (result["status"], result["passed"]) == expected


def test_official_timeout_is_separate_from_failed_task(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([{"instance_id": "target"}]))

    def fake_run(args, **kwargs):
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        raise subprocess.TimeoutExpired(args, 1, output="still working")

    monkeypatch.setattr("auto_designer.evaluation.adapters.swebench.subprocess.run", fake_run)
    result = _SWEbenchRunner(dataset, tmp_path / "results", timeout=1).evaluate(
        instance_id="target", patch=""
    )
    assert result["status"] == "timed_out" and result["passed"] is False


def test_optional_dependency_preflight_is_explicit(monkeypatch):
    monkeypatch.setattr(
        "auto_designer.evaluation.adapters.swebench.importlib.util.find_spec",
        lambda name: None,
    )
    monkeypatch.setattr(
        "auto_designer.evaluation.adapters.swebench.subprocess.run",
        lambda *a, **k: pytest.fail("noDockerwhenmissingextra"),
    )
    assert _SWEbenchRunner.preflight() == "evaluation extra is not installed"


@pytest.mark.parametrize(
    "diagnostic,expected",
    [
        ("ImportError while loading conftest '/testbed/conftest.py'.", "crashed"),
        ("________________ ERROR collecting tests/test_api.py ________________", "crashed"),
        ("ERROR collecting tests/test_api.py", "crashed"),
        ("FAILED tests/test_api.py::test_behavior - AssertionError", "completed"),
        ("PASSED tests/test_api.py::test_error_collecting_message", "completed"),
    ],
)
def test_pytest_startup_error_is_not_a_completed_failure(
    tmp_path, monkeypatch, diagnostic, expected
):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([{"instance_id": "target"}]))

    def fake_run(args, **kwargs):
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        run_id = args[args.index("--run_id") + 1]
        root = Path(args[args.index("--report_dir") + 1])
        (root / f"auto-designer.{run_id}.json").write_text(
            json.dumps({"unresolved_ids": ["target"]})
        )
        output = root / "logs/run_evaluation" / run_id / "auto-designer/target/test_output.txt"
        output.parent.mkdir(parents=True)
        output.write_text(
            "ImportError while loading conftest outside test execution\n"
            f">>>>> Start Test Output\n{diagnostic}\n>>>>> End Test Output\n"
        )
        return subprocess.CompletedProcess(args, 0, "official done", "")

    monkeypatch.setattr("auto_designer.evaluation.adapters.swebench.subprocess.run", fake_run)
    result = _SWEbenchRunner(dataset, tmp_path / "results").evaluate(
        instance_id="target", patch="nonempty"
    )
    assert result["status"] == expected
    if expected == "crashed":
        assert result["reason"] == "official_test_start_failed"
        assert result["test_start_error"] == diagnostic
    else:
        assert result["passed"] is False
