from __future__ import annotations

from pathlib import Path

import pytest
from tools.dev.delivery.prepare_openagents_from_summary import validate_summary


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


def test_summary_git_failure_withholds_sensitive_output_and_argv(tmp_path, monkeypatch, capsys):
    import base64
    import json
    import subprocess
    import sys
    from types import SimpleNamespace

    from tools.dev import delivery
    from tools.dev.delivery import prepare_openagents_from_summary as module

    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "entry.py").write_text("pass\n")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"issues": []}))
    token = "private-token-value"
    encoded = base64.b64encode(f"selected-owner:{token}".encode()).decode()
    provider = {"GITEA_URL": "https://selected.example", "OWNER": "selected-owner", "TOKEN": token}
    monkeypatch.setattr(module, "run_inputs", lambda *args: ({}, {}, provider))
    monkeypatch.setattr(
        module.requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=404)
    )
    monkeypatch.setattr(
        module.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare",
            "--run-dir",
            str(tmp_path / "selected-run"),
            "--summary",
            str(summary),
            "--harness-repo",
            str(harness),
            "--target-repo",
            "target",
            "--manifest",
            str(tmp_path / "output.json"),
        ],
    )
    calls = []

    def reject_push(command, **kwargs):
        calls.append((command, kwargs))
        assert token not in " ".join(command)
        assert encoded not in " ".join(command)
        assert kwargs["capture_output"] is True
        if "push" in command:
            return subprocess.CompletedProcess(
                command, 128, stdout=token.encode(), stderr=encoded.encode()
            )
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(delivery.subprocess, "run", reject_push)
    with pytest.raises(SystemExit, match="exit 128") as error:
        module.main()
    remotes = [command[-1] for command, _ in calls if "remote" in command]
    assert remotes == ["https://selected.example/selected-owner/target.git"]
    captured = capsys.readouterr()
    rendered = str(error.value) + captured.out + captured.err
    assert token not in rendered
    assert encoded not in rendered
    assert not (tmp_path / "output.json").exists()
