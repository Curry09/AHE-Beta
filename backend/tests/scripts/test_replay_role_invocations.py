# Spec-0049/T5: Frozen call replay unit test (do not start Gitea / vigil / real models).
"""Replay skips implementer records and diffs structured output."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[3] / "tools/dev/replay/replay_role_invocations.py"
    spec = importlib.util.spec_from_file_location("replay_role_invocations", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_filters_role(tmp_path: Path) -> None:
    mod = _module()
    demand = tmp_path / "demand"
    demand.mkdir()
    (demand / "a.json").write_text(
        json.dumps({"role": "owner", "side": "demand", "replayable": True}),
        encoding="utf-8",
    )
    (demand / "b.json").write_text(
        json.dumps({"role": "triager", "side": "demand", "replayable": True}),
        encoding="utf-8",
    )
    rows = mod.load_invocations(run_dir=tmp_path, side="demand", role="owner")
    assert len(rows) == 1
    assert rows[0]["role"] == "owner"


def test_replay_diffs_structured_and_skips_implementer(tmp_path: Path) -> None:
    mod = _module()
    records = [
        {
            "invocation_id": "1",
            "side": "demand",
            "role": "owner",
            "replayable": True,
            "subject": {"kind": "round", "id": "1"},
            "input": {"prompt": "frozen-owner"},
            "output": {"structured": {"decisions": []}, "status": "success"},
        },
        {
            "invocation_id": "2",
            "side": "delivery",
            "role": "implementer",
            "replayable": False,
            "input": {"prompt": "do-not-run"},
            "output": {"structured": {"ok": True}, "status": "success"},
        },
    ]

    def runner(agent_def, prompt, *, store_repo, role, subject) -> str:
        assert prompt == "frozen-owner"
        assert role == "owner"
        return json.dumps({"decisions": [{"issue": 1}]})

    out = mod.replay_records(records=records, agent_def=tmp_path, repo=tmp_path, runner=runner)
    assert out["skipped"] == 1
    assert out["replayed"] == 1
    assert out["diffs"][0]["changed"] is True
    assert out["diffs"][0]["new"] == {"decisions": [{"issue": 1}]}
