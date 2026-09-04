from __future__ import annotations

import pytest

from auto_designer.designer.role_contract import (
    render_pm_artifact,
    render_synthesis_artifact,
    validate_owner,
    validate_pm,
    validate_synthesis,
    validate_triage,
)


def test_triage_contract_isolated_report_and_product_boundary() -> None:
    valid = {
        "issue": 7,
        "disposition": "accept",
        "artifact": {"implementation_target": "harness"},
    }
    assert validate_triage(valid, report_number=7) == []
    assert validate_triage({**valid, "issue": 8}, report_number=7)[0].code == "foreign-source"
    assert validate_triage({"issue": 7, "disposition": "accept"}, report_number=7)[0].code == "missing-artifact"
    outside = {**valid, "artifact": {"implementation_target": "external-project"}}
    assert validate_triage(outside, report_number=7)[0].code == "out-of-product-scope"


def test_pm_contract_requires_product_level_known_session_evidence() -> None:
    valid = {
        "solution_level": "product_capability",
        "evidence_sessions": ["session-1"],
    }
    assert validate_pm(valid, known_sessions={"session-1"}) == []
    assert validate_pm({**valid, "solution_level": "implementation"}, known_sessions={"session-1"})[0].code == "wrong-abstraction"
    assert validate_pm({**valid, "evidence_sessions": []}, known_sessions={"session-1"})[0].code == "missing-evidence"
    assert validate_pm({**valid, "evidence_sessions": [{}]}, known_sessions={"session-1"})[0].code == "invalid-evidence"
    assert validate_pm(valid, known_sessions={"session-2"})[0].code == "foreign-source"


def test_synthesis_contract_requires_two_distinct_visible_issue_numbers() -> None:
    valid = {
        "solution_level": "structural_mechanism",
        "source_proposals": [1, 2],
    }
    assert validate_synthesis(valid, visible_proposals={1, 2}) == []
    assert validate_synthesis({**valid, "solution_level": "implementation"}, visible_proposals={1, 2})[0].code == "wrong-abstraction"
    assert validate_synthesis({**valid, "source_proposals": [1, 1]}, visible_proposals={1, 2})[0].code == "not-cross-proposal"
    assert validate_synthesis({**valid, "source_proposals": [1, {}]}, visible_proposals={1, 2})[0].code == "invalid-source"
    assert validate_synthesis(valid, visible_proposals={1, 3})[0].code == "foreign-source"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"issue": 9}, "decision-out-of-batch"),
        ({"decision": "merge"}, "missing-merge-target"),
        ({"decision": "hold"}, "missing-hold-gap"),
    ],
)
def test_owner_contract_only_guards_routing_integrity(change, code) -> None:
    valid = {
        "issue": 1,
        "decision": "admit",
    }
    candidate = {**valid, **change}
    assert validate_owner(candidate, review_batch={1})[0].code == code
    assert validate_owner(valid, review_batch={1}) == []


def test_role_renderers_preserve_structured_evidence_and_relationships() -> None:
    pm = render_pm_artifact(
        {
            "user_goal": "goal",
            "observed_behaviors": ["behavior"],
            "experience_tension": "tension",
            "product_opportunity": "opportunity",
            "desired_outcome": "outcome",
            "evidence_sessions": ["session-1"],
            "related_proposals": [3],
        }
    )
    synthesis = render_synthesis_artifact(
        {
            "source_proposals": [1, 2],
            "relationship": "relationship",
            "common_tension": "tension",
            "structural_direction": "direction",
            "expected_leverage": "leverage",
        }
    )
    assert "session-1" in pm and "#3" in pm
    assert "#1, #2" in synthesis and "relationship" in synthesis
