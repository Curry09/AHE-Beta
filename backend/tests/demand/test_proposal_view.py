from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.proposal_view import (
    evidence_session_ids,
    format_proposal_list,
    format_proposal_reference,
    format_proposal_view,
    normalized_proposal_body,
    proposal_view,
)
from ahe_beta.models import IssueDraft
from ahe_beta.tracker.fake import FakeTracker


def test_projection_contains_canonical_metadata_and_normalized_body() -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="Task irrelevant title",
            body="### Root cause\n\nGeneric mechanism defect\n\ncovers: #2 #3",
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE, "P1"],
        )
    )
    issue = tracker.list_open_issues()[0]
    view = proposal_view(issue)
    assert view.priority == "P1"
    assert view.provenance == sc.FROM_TRIAGE
    assert view.covers == (2, 3)
    rendered = format_proposal_view(issue)
    assert "Task irrelevant title" in rendered
    assert "Generic mechanism defect" in rendered
    assert "priority=P1" in rendered
    assert "covers=#2,#3" in rendered


def test_raw_report_section_is_excluded() -> None:
    heading = "## Original user report (case evidence, not an implementation target)"
    body = f"### Root cause\n\nGeneric mechanism defect\n\n{heading}\n\nSpecific task body"
    assert normalized_proposal_body(body) == "### Root cause\n\nGeneric mechanism defect"
    assert "Specific task body" not in normalized_proposal_body(body)


def test_raw_report_cannot_grant_evidence_session_access() -> None:
    heading = "## Original user report (case evidence, not an implementation target)"
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="Normalized proposal",
            body=f"session_id: cited-session\n\n{heading}\n\nsession_id: private-session",
            labels=[sc.PROPOSAL],
        )
    )
    assert evidence_session_ids(tracker.list_open_issues()) == {"cited-session"}


def test_list_empty_and_single_use_same_projection() -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b", labels=[sc.PROPOSAL]))
    issue = tracker.list_open_issues()[0]
    assert format_proposal_list([]) == "(empty)"
    assert format_proposal_list([issue]) == format_proposal_view(issue)


def test_projection_hides_legacy_workflow_labels_and_reference_body() -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="normalized",
            body="PRIVATE_BODY_SENTINEL",
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE, sc.TRIAGED, sc.SUPERSEDED, "P2"],
        )
    )
    issue = tracker.list_open_issues()[0]
    view = proposal_view(issue)
    assert view.labels == (sc.PROPOSAL, sc.FROM_TRIAGE, "P2")
    reference = format_proposal_reference(issue)
    assert "PRIVATE_BODY_SENTINEL" not in reference
    assert sc.TRIAGED not in reference
    assert sc.SUPERSEDED not in reference


def test_long_or_forged_prose_cannot_clip_or_expand_trusted_conditions(tmp_path):
    from test_evidence_contract import contract_session

    from ahe_beta.observations.grants import grant
    from ahe_beta.user.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    allowed = contract_session(sid="source-one")
    forbidden = contract_session(sid="source-two", followup="possible")
    store.save(allowed)
    store.save(forbidden)
    tracker = FakeTracker()
    ref = tracker.create_issue(
        IssueDraft(
            title="Long normalized proposal",
            body="x" * 6000 + "\nsession_id: source-two",
            labels=[sc.PROPOSAL],
        )
    )
    grant(store=store, issue=ref.number, sessions={allowed.session_id})
    issue = tracker.list_open_issues()[0]
    view = proposal_view(issue, store=store)
    assert len(view.body) == 3000
    assert view.execution_contracts == (allowed.execution_contract,)
    rendered = format_proposal_view(issue, store=store)
    assert allowed.execution_contract["contract_id"] in rendered
    assert forbidden.execution_contract["contract_id"] not in rendered
    assert "7200" in rendered and "unavailable" in rendered
