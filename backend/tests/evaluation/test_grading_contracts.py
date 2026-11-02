"""Cross-adapter failure/acceptance contracts (Spec-0083/T1)."""

from __future__ import annotations

import pytest

from ahe_beta.evaluation.acceptance import derive_acceptance_assessment
from ahe_beta.evaluation.contracts import GradingRequest
from ahe_beta.evaluation.registry import get_adapter
from ahe_beta.evaluation.results import ExecutionEvidence, GradingResult


def test_requests_freeze_nested_operator_configuration():
    config = {"argv": ["python", "/grader/script.py"], "nested": {"test": 1}}
    request = GradingRequest("custom", 1, "t", "digest", "session", config=config)
    config["nested"]["test"] = 2
    assert request.config["nested"]["test"] == 1
    with pytest.raises(TypeError):
        request.config["nested"]["test"] = 3


@pytest.mark.parametrize(
    "name,version", [("other", 1), ("custom", 2), ("custom", True), ("custom", 1.0)]
)
def test_registry_rejects_unknown_adapters_and_contracts(name, version):
    with pytest.raises(ValueError):
        get_adapter(name, version)


@pytest.mark.parametrize(
    "status",
    ["unavailable", "crashed", "timed_out", "not_evaluated", "missing_artifact", "ungradable"],
)
def test_infrastructure_and_missing_evidence_are_not_technical_failures(status):
    result = GradingResult("swebench", 1, status, passed=False, raw_report={"passed": False})
    assert result.passed is None
    assert result.to_dict()["raw_report"]["passed"] is False


@pytest.mark.parametrize(
    "contract",
    [
        "fresh_official_instance",
        "agent_stopped_task_environment",
        "trusted_recorded_measurement",
        "isolated_custom_verifier",
    ],
)
def test_acceptance_checks_adapter_contract_not_universal_fresh(contract):
    result = GradingResult(
        "custom",
        1,
        "completed",
        passed=True,
        execution=ExecutionEvidence(contract, True, "sha256:" + "a" * 64),
    )
    session = {
        "user_outcome": {
            "interaction_mode": "direct",
            "status": "completed",
            "review_verdict": "accept",
            "review_status": "completed",
        }
    }
    assert derive_acceptance_assessment(session=session, result=result) == "unverified_accept"


def test_continuous_score_without_binary_rule_is_unverified_acceptance():
    result = GradingResult("nl2repo", 1, "completed", score=0.8)
    session = {"sim_trace": {"end_reason": "accepted"}}
    assert derive_acceptance_assessment(session=session, result=result) == "unverified_accept"


@pytest.mark.parametrize(
    "invalid", [{"evaluation_status": "invalid"}, {"interaction_status": "protocol_unrecoverable"}]
)
def test_invalid_original_interaction_cannot_upgrade_acceptance(invalid):
    session = {"sim_trace": {"end_reason": "accepted", **invalid}}
    result = GradingResult(
        "swebench",
        1,
        "completed",
        passed=True,
        execution=ExecutionEvidence("fresh_official_instance", True, "sha256:" + "a" * 64),
    )
    assert derive_acceptance_assessment(session=session, result=result) == "unverified_accept"


def test_failed_direct_review_cannot_become_valid_accept():
    session = {
        "user_outcome": {
            "interaction_mode": "direct",
            "review_verdict": "accept",
            "review_status": "infrastructure_failure",
        }
    }
    result = GradingResult("custom", 1, "completed", passed=True)
    assert derive_acceptance_assessment(session=session, result=result) == "not_applicable"


def test_known_request_failure_remains_false_accept_for_valid_direct_review():
    session = {
        "user_outcome": {
            "interaction_mode": "direct",
            "status": "infrastructure_failure",
            "review_verdict": "accept",
            "review_status": "completed",
        },
        "request_outcomes": [{"status": "crashed"}],
    }
    assert (
        derive_acceptance_assessment(
            session=session, result=GradingResult("custom", 1, "unavailable")
        )
        == "unverified_accept"
    )


@pytest.mark.parametrize("passed,expected", [(True, "valid_accept"), (False, "false_accept")])
def test_canonical_acceptance_uses_task_assessment_even_if_rating_missing(passed, expected):
    session = {
        "feedback": {"task_assessment": {"status": "fulfilled"}},
        "user_outcome": {"interaction_mode": "direct", "review_status": "completed"},
        "sim_trace": {"evaluation_status": "invalid"},
    }
    result = GradingResult(
        "custom",
        1,
        "completed",
        passed=passed,
        execution=ExecutionEvidence("isolated_custom_verifier", True, "sha256:" + "a" * 64),
    )
    assert derive_acceptance_assessment(session=session, result=result) == expected
