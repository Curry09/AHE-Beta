import json
from pathlib import Path

import pytest
import yaml

from ahe_beta.observations.delivery_gaps import MARKER, ingest_delivery_gaps
from ahe_beta.observations.gaps import (
    GapService,
    bind_gaps,
    gap_schema,
    submit_observation_gap,
)
from ahe_beta.observations.grants import authorized_sessions, grant
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore


def request(**changes):
    return {
        "request_id": "cancel-ownership",
        "scope": "harness",
        "session_ids": ["s1"],
        "related_issues": [],
        "question": "Which request resumed after cancel?",
        "checked": "v1 READING and activity window",
        "unknowns": "old or new request",
        "impact": "Cannot verify cancellation ownership",
        "desired_capability": "Distinguish ownership",
        "verification": "Controlled overlapping old/new requests",
        **changes,
    }


def service(tmp_path, tracker=None, role="triager"):
    return GapService(
        store=SessionStore(tmp_path / "sessions"),
        tracker=tracker or FakeTracker(),
        role=role,
        subject="round1",
        sessions={"s1"},
        issues={1},
    )


def test_submission_does_not_stop_role_and_is_scoped(tmp_path):
    svc = service(tmp_path)
    with bind_gaps(svc):
        result = submit_observation_gap(**request())
        assert result["status"] == "submitted"
        assert (
            submit_observation_gap(**request(session_ids=["other"]))["error"]
            == "outside_evidence_scope"
        )
        assert submit_observation_gap(**request())["issue"] == result["issue"]
        assert authorized_sessions(store=svc.store, issue=result["issue"]) == {"s1"}
    assert svc.submit(request())["error"] == "invocation_closed"
    assert submit_observation_gap(**request())["error"] == "no_authorized_invocation"
    assert len(svc.tracker.list_open_issues()) == 1


def test_gap_created_in_round_has_round_label(tmp_path):
    svc = service(tmp_path)
    with bind_usage_context(round_no=2):
        result = svc.submit(request())
    assert svc.tracker.issue(result["issue"])["labels"] == [
        "proposal",
        "observation-gap",
        "round-2",
    ]


def test_framework_failures_never_create_harness_proposals(tmp_path):
    svc = service(tmp_path)
    assert svc.submit(request(scope="framework"))["status"] == "infrastructure_diagnostic"
    svc.retry_pending()
    assert not svc.tracker.list_open_issues()


def test_pm_origin_preserved_and_conflicts_rejected(tmp_path):
    svc = service(tmp_path, role="divergent")
    result = svc.submit(request())
    assert "from-divergent" in svc.tracker.issue(result["issue"])["labels"]
    assert svc.submit(request(question="a different question"))["error"] == "request_id_conflict"
    assert "openagents" not in svc.tracker.issue(result["issue"])["labels"]


@pytest.mark.parametrize("role", ["owner", "delivery-developer"])
def test_pm_lineage_cannot_leak_back_through_followup_gaps(tmp_path, role):
    svc = service(tmp_path, role=role)
    from ahe_beta.models import IssueDraft

    source = svc.tracker.create_issue(
        IssueDraft(title="PM", body="opportunity", labels=["from-divergent"])
    )
    grant(store=svc.store, issue=source.number, sessions={"s1"}, pm_origin=True)
    result = svc.submit(request(related_issues=[source.number], session_ids=[]))
    assert "from-divergent" in svc.tracker.issue(result["issue"])["labels"]


def test_restart_and_ambiguous_remote_response_do_not_duplicate_closed_issue(tmp_path, monkeypatch):
    tracker = FakeTracker()
    original = tracker.create_issue

    def ambiguous(draft):
        issue = original(draft)
        tracker.set_state(issue.number, "closed", "already addressed")
        raise OSError("lost HTTP response")

    monkeypatch.setattr(tracker, "create_issue", ambiguous)
    svc = service(tmp_path, tracker)
    assert svc.submit(request())["status"] == "pending"
    monkeypatch.setattr(tracker, "create_issue", original)
    restarted = service(tmp_path, tracker)
    restarted.retry_pending()
    assert restarted.submit(request())["issue"] == 1
    assert tracker._counter == 1


@pytest.mark.parametrize("role", ["triage_agent", "divergent_pm", "architect", "owner"])
def test_nonterminal_tool_schemas_do_not_drift(role):
    root = Path(__file__).resolve().parents[2] / "agent_defs" / role
    tool = yaml.safe_load((root / "tools/submit_observation_gap.tool.yaml").read_text())
    config = yaml.safe_load((root / "agent.yaml").read_text())
    assert tool["input_schema"] == gap_schema()
    assert "submit_observation_gap" not in config["stop_tools"]


def test_delivery_ingestion_requires_authenticated_author_and_issue_scope(tmp_path):
    svc = service(tmp_path)
    tracker = svc.tracker
    from ahe_beta.models import IssueDraft

    ref = tracker.create_issue(IssueDraft(title="original", body="context", labels=["openagents"]))
    grant(store=svc.store, issue=ref.number, sessions={"s1"})
    payload = {
        "issue": ref.number,
        "role": "reviewer",
        "request": request(related_issues=[ref.number]),
    }
    body = f"<!-- openagents:agent=observation-runner -->\n<!-- {MARKER} {json.dumps(payload)} -->"
    tracker.authenticated_login = lambda: "automation"
    tracker.list_comments = lambda **kw: [{"author": "human", "body": body}]
    assert ingest_delivery_gaps(store=svc.store, tracker=tracker) == []
    tracker.list_comments = lambda **kw: (
        [{"author": "automation", "body": body}] if kw["number"] == ref.number else []
    )
    result = ingest_delivery_gaps(store=svc.store, tracker=tracker)
    assert result[0]["status"] == "submitted"
    assert tracker.issue(result[0]["issue"])["labels"] == ["proposal", "observation-gap"]
    ingest_delivery_gaps(store=svc.store, tracker=tracker)
    assert len(tracker.list_open_issues()) == 2
