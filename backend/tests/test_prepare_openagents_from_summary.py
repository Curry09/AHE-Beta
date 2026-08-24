from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prepare_openagents_from_summary import validate_summary


def test_summary_preflight_requires_contiguous_typed_issues(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    harness.mkdir()
    valid = {
        "issues": [
            {"number": 1, "title": "one", "body": "body", "labels": ["ready"]},
            {
                "number": 2,
                "title": "two",
                "body": "body",
                "labels": [],
                "state": "closed",
            },
        ]
    }
    assert [item["number"] for item in validate_summary(valid, harness)] == [1, 2]
    with pytest.raises(SystemExit, match="contiguous"):
        validate_summary({"issues": [{**valid["issues"][0], "number": 2}]}, harness)
    with pytest.raises(SystemExit, match="string labels"):
        validate_summary({"issues": [{**valid["issues"][0], "labels": [3]}]}, harness)


def test_summary_preflight_requires_existing_harness(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="does not exist"):
        validate_summary({"issues": []}, tmp_path / "missing")
