from auto_designer.designer import issue_schema as sc
from auto_designer.designer.proposal_view import (
    format_proposal_list,
    format_proposal_reference,
    format_proposal_view,
    normalized_proposal_body,
    proposal_view,
)
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker


def test_projection_contains_canonical_metadata_and_normalized_body() -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="任务无关标题",
            body="### 根因区域\n\n通用机制缺陷\n\ncovers: #2 #3",
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE, "P1"],
        )
    )
    issue = tracker.list_open_issues()[0]
    view = proposal_view(issue)
    assert view.priority == "P1"
    assert view.provenance == sc.FROM_TRIAGE
    assert view.covers == (2, 3)
    rendered = format_proposal_view(issue)
    assert "任务无关标题" in rendered
    assert "通用机制缺陷" in rendered
    assert "priority=P1" in rendered
    assert "covers=#2,#3" in rendered


def test_legacy_raw_report_section_is_excluded() -> None:
    body = (
        "### 根因区域\n\n通用机制缺陷\n\n"
        "## 原始用户报告（案例证据，非实现对象）\n\n具体任务正文"
    )
    assert normalized_proposal_body(body) == "### 根因区域\n\n通用机制缺陷"
    assert "具体任务正文" not in normalized_proposal_body(body)


def test_list_empty_and_single_use_same_projection() -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b", labels=[sc.PROPOSAL]))
    issue = tracker.list_open_issues()[0]
    assert format_proposal_list([]) == "（空）"
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
