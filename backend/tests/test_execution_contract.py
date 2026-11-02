"""Evidence identity, independent axes and missing-data regressions (Spec-0084/T1)."""

import pytest

from ahe_beta.execution_contract import (
    build_execution_evidence,
    canonical_sha256,
    make_execution_contract,
    validate_execution_contract,
)
from ahe_beta.loop.metrics import Metrics
from ahe_beta.models import FeelingScore, Persona, SeedScenario, Session, Transcript
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore


def feedback(status="missing", score=None):
    return {
        "schema_version": 1,
        "task_assessment": {"status": "unfulfilled", "source": "reviewer", "evidence_refs": []},
        "experience": {
            "status": status,
            "score": score,
            "source": "reviewer",
            "reason": "no self-rating",
        },
        "attribution": {"status": "unknown", "claims": []},
        "opportunities": [],
    }


def session(**kwargs):
    return Session(Persona("p", "l", "d", "g", "s"), SeedScenario("goal"), Transcript(), **kwargs)


def contract(**overrides):
    return make_execution_contract(
        **dict(
            session_id="session-a",
            task_id="task",
            task_digest="a" * 64,
            followup_input="unavailable",
            task_budget_seconds=7200,
            budget_source="task_metadata",
            **overrides,
        )
    )


@pytest.mark.parametrize("score", [True, False, 1.0, 2.5, "3", 0, 5])
def test_self_rating_is_a_strict_integer(score):
    with pytest.raises((AssertionError, ValueError)):
        FeelingScore(score, "reason")
    with pytest.raises(ValueError):
        session(feedback=feedback("rated", score))


def test_missing_rating_never_inherits_derived_or_old_score(tmp_path):
    item = session(feeling=FeelingScore(3, "derived"), feedback=feedback(), report_plan=[])
    assert item.feeling is None
    store = SessionStore(tmp_path)
    store.save(item)
    assert store.load(item.session_id).to_dict() == item.to_dict()
    assert store.index()[0]["score"] is None
    metrics = Metrics(FakeTracker(), store)
    assert metrics.feeling_trend() == []
    assert metrics.feedback_counts()["unknown"]["missing"] == 1
    assert item.feedback["task_assessment"]["status"] == "unfulfilled"


def test_reading_old_session_does_not_rewrite_or_invent_feedback(tmp_path):
    item = session(feeling=FeelingScore(2, "old"))
    store = SessionStore(tmp_path)
    store.save(item)
    file = tmp_path / f"{item.session_id}.json"
    before = file.read_bytes()
    restored = store.load(item.session_id)
    assert "feedback" not in restored.to_dict()
    assert file.read_bytes() == before


def test_contract_digest_and_conditions_are_immutable():
    original = contract()
    changed = {**original, "followup_input": "possible"}
    with pytest.raises(ValueError, match="digest"):
        validate_execution_contract(changed)
    assert validate_execution_contract(original) == original


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "session-a/../other",
        "other/task.json",
        "session-a/evaluation/gold",
        "session-a//goal",
    ],
)
def test_public_refs_cannot_escape_authorized_session(path):
    with pytest.raises(ValueError):
        contract(public_refs=[{"kind": "goal", "path": path, "sha256": "b" * 64}])


def test_wire_canonicalization_and_summary_binding():
    declaration = contract()
    summary = dict(
        receipt_id="receipt1",
        session_id="session-a",
        contract_id=declaration["contract_id"],
        status="completed",
        passed=False,
        score=None,
        metric_definition=None,
        assessment_kind="independent",
        source_sha256="c" * 64,
    )
    wire = build_execution_evidence(issue=12, contracts=[declaration], summaries=[summary])
    digest = wire.pop("payload_sha256")
    assert digest == canonical_sha256(wire)
    summary["status"] = "unavailable"
    with pytest.raises(ValueError, match="cannot pass"):
        build_execution_evidence(issue=12, contracts=[declaration], summaries=[summary])
    summary.update(passed=None, session_id="forged")
    with pytest.raises(ValueError, match="authorized"):
        build_execution_evidence(issue=12, contracts=[declaration], summaries=[summary])


def test_no_private_fields_in_public_metric():
    declaration = contract()
    summary = dict(
        receipt_id="receipt1",
        session_id="session-a",
        contract_id=declaration["contract_id"],
        status="completed",
        passed=None,
        score=0.3,
        metric_definition={"private_report": "secret"},
        assessment_kind="independent",
        source_sha256="c" * 64,
    )
    with pytest.raises(ValueError, match="public scalar"):
        build_execution_evidence(issue=12, contracts=[declaration], summaries=[summary])
