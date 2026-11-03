# Spec-0049/T6: Delivery layer call JSON and OpenAgents written contract.
"""Lock the v1 invocation schema shared with OpenAgents run_agent."""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED = (
    "schema_version",
    "invocation_id",
    "run_id",
    "round",
    "side",
    "role",
    "subject",
    "replayable",
    "input",
    "output",
    "env",
)
INPUT_KEYS = ("prompt", "context", "placeholders")
OUTPUT_KEYS = ("structured", "status", "error")
FORBIDDEN = ("protocol_output", "transcript", "GITEA_TOKEN", "ANTHROPIC_API_KEY")


def test_golden_delivery_fixture_matches_v1_contract() -> None:
    path = Path(__file__).parent / "fixtures" / "delivery_invocation.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED:
        assert key in data
    assert data["schema_version"] == 1
    assert data["side"] in ("demand", "delivery")
    assert isinstance(data["subject"], dict)
    assert "kind" in data["subject"] and "id" in data["subject"]
    for key in INPUT_KEYS:
        assert key in data["input"]
    for key in OUTPUT_KEYS:
        assert key in data["output"]
    blob = json.dumps(data)
    for token in FORBIDDEN:
        assert token not in blob
