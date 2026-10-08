"""Public examples and original acceptance remain usable (Spec-0083/T6)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from auto_designer.evaluation.acceptance import derive_acceptance_assessment
from auto_designer.experiment.cli import build_parser
from auto_designer.models import FeelingScore, Persona, SeedScenario, Session, Transcript

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["swebench", "mixed-benchmarks", "custom"])
def test_public_grading_templates_use_current_plan_schema(name):
    schema = json.loads(
        (ROOT / "backend/auto_designer/experiment/schemas/grading-plan-v1.json").read_text()
    )
    document = json.loads((ROOT / "examples/grading" / f"{name}.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    selected = []
    for grader in document["graders"]:
        selected.extend(grader["task_ids"])
        assert set(grader["inputs"].values()) <= document["materials"].keys()
    assert len(selected) == len(set(selected))


def test_documented_plan_command_and_time_budget_parse_without_legacy_flags():
    parsed = build_parser().parse_args(
        [
            "--runs-dir",
            "retained-runs",
            "--json",
            "grade",
            "collected-run",
            "--plan",
            "private.json",
            "--round",
            "6",
            "--offline",
        ]
    )
    assert parsed.plan == Path("private.json") and parsed.round_no == 6 and parsed.offline
    # A global override would make the plan's declared conditions ambiguous.
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(
            ["grade", "collected-run", "--plan", "private.json", "--timeout-seconds", "1"]
        )
    assert error.value.code == 2


def test_new_assessment_does_not_rewrite_original_legacy_session_evaluation():
    original = Session(
        persona=Persona("expert", "advanced", "python", "fix task", "direct"),
        scenario=SeedScenario("Fix task"),
        transcript=Transcript(),
        feeling=FeelingScore(4, "Accepted"),
        user_outcome={
            "interaction_mode": "direct",
            "review_verdict": "accept",
            "review_status": "completed",
        },
        accept_validity="not_applicable",
        objective_evaluation=None,
    )
    original_bytes = json.dumps(original.to_dict(), sort_keys=True)
    result = {
        "status": "completed",
        "passed": True,
        "execution": {
            "contract": "isolated_custom_verifier",
            "verified": True,
            "image_digest": "sha256:" + "a" * 64,
        },
    }
    assert derive_acceptance_assessment(session=original.to_dict(), result=result) == "valid_accept"
    assert json.dumps(original.to_dict(), sort_keys=True) == original_bytes
    assert "evaluation_artifacts" not in original.workspace_evidence
    restored = Session.from_dict(json.loads(original_bytes))
    assert restored.accept_validity == "not_applicable" and restored.objective_evaluation is None
