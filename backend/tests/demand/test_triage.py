# Spec-0029/T3: Triager unit test — three-valued disposition (accept/reject/needs_info); accept promotes to proposal in place.
"""stub agent (replays a fixed submit_triage return) + FakeTracker + temporary SessionStore: verify the driver correctly materializes each
disposition into three-plane labels/comments/closure; no dedup; supports passing in a pending shard. Does not run real nexau."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import requests

from ahe_beta.demand import agent_contract as ac
from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.triage import TriageOutcome, Triager, _proposal_labels, _proposal_title
from ahe_beta.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from ahe_beta.models import IssueDraft
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.tracker.gitea import GiteaError, IssueMigrationError
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore


class _StubTriager(Triager):
    """Override _run_agent: does not run real nexau; replays a fixed submit return and records the pending set fed in."""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_pending: list = []
        self.agent_calls = 0

    def _run_agent(self, *, pending: list) -> str:
        self.agent_calls += 1
        self.seen_pending = pending
        return self._canned


def _triager(tmp_path: Path, tracker: FakeTracker, canned: str) -> _StubTriager:
    store = SessionStore(tmp_path / "sessions")
    return _StubTriager(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent_def"), canned=canned
    )


def _report(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=[kind, sc.REPORT, "round-1"])
    ).number


def _submit(dispositions: list) -> str:
    """Shaped into the return form of submit_triage (the output of the stop tool binding)."""
    return json.dumps({"dispositions": dispositions}, ensure_ascii=False)


def _recovery(tmp_path: Path) -> RecoveryStore:
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    started = operation_key("round-started")
    store.begin_unit(
        round_no=1,
        stage="round_started",
        key=started,
        input_value={},
        expected_postconditions={"completed": True},
    )
    store.complete_unit(round_no=1, stage="round_started", key=started)
    store.complete_stage(round_no=1, stage="round_started")
    key = operation_key("users", "empty")
    store.begin_unit(
        round_no=1,
        stage="users",
        key=key,
        input_value={},
        expected_postconditions={"completed": True},
        dependencies=("round_started",),
    )
    store.complete_unit(round_no=1, stage="users", key=key)
    store.complete_stage(round_no=1, stage="users")
    return store


def _accept(n: int, *, kind: str = "bug", priority: str = "P1", fields: dict | None = None) -> dict:
    default_fields = {
        "root_cause": "entry.py No budget awareness",
        "boundary": "Only change general capabilities",
        "acceptance": "Delivery within budget",
    }
    return {
        "issue": n,
        "disposition": "accept",
        "kind": kind,
        "priority": priority,
        "proposal_title": "Precise task execution lacks budget awareness",
        "fields": fields if fields is not None else default_fields,
        "artifact": {
            "reported_problem": "Task execution exceeds budget",
            "user_impact": "User did not receive usable delivery",
            "scope_boundary": "General harness Execution behavior",
            "evidence": [f"report:#{n}"],
            "uncertainties": [],
            "implementation_target": "harness",
        },
    }


def test_submit_triage_yaml_matches_contract() -> None:
    """drift-guard: the input_schema of submit_triage.tool.yaml is deeply equal to dispositions_input_schema()."""
    import yaml

    from ahe_beta.demand.agent_contract import dispositions_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "triage_agent"
        / "tools"
        / "submit_triage.tool.yaml"
    )
    tool_def = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == dispositions_input_schema()
    # Three-valued enum: duplicate has been retired (cross-proposal absorption is handled by the Architect)
    enum = tool_def["input_schema"]["properties"]["dispositions"]["items"]["properties"][
        "disposition"
    ]["enum"]
    assert enum == ["accept", "reject", "needs_info"]


def test_no_pending_is_noop(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(title="Already a proposal", body="x", labels=["bug", sc.PROPOSAL])
    )
    t = _triager(tmp_path, tracker, _submit([]))
    out = t.triage_once()
    assert out.handled == 0
    assert t.agent_calls == 0  # No report → no LLM run


def test_accept_promotes_report_to_proposal(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "unidecode timeout", kind="bug")
    submitted = {"dispositions": [_accept(n)]}
    jsonschema.validate(submitted, ac.dispositions_input_schema())
    out = _triager(tmp_path, tracker, json.dumps(submitted, ensure_ascii=False)).triage_once()

    assert isinstance(out, TriageOutcome) and out.accepted == [n]
    snap = tracker.issue(n)
    assert sc.PROPOSAL in snap["labels"] and sc.FROM_TRIAGE in snap["labels"]
    assert "bug" in snap["labels"] and "P1" in snap["labels"]
    assert sc.REPORT not in snap["labels"]  # Leave the report plane
    assert "round-1" in snap["labels"]  # Attributes preserved
    assert snap["state"] == "open"
    # Proposals cannot be claimed (the Delivery Router applies an openagents handoff token, after which they enter the delivery plane)
    assert not sc.is_ready(labels=snap["labels"], state=snap["state"])
    assert sc.plane(snap["labels"]) == sc.PROPOSAL
    assert snap["body"].startswith("## Triage normalized proposal (implementation target: harness)")
    assert "entry.py No budget awareness" in snap["body"]
    assert snap["title"] == "Precise task execution lacks budget awareness"
    assert "Original user report" not in snap["body"]
    assert any(
        "Original title" in c and "unidecode timeout" in c and "x" in c for c in snap["comments"]
    )
    assert "### Root cause" in snap["body"] and "entry.py No budget awareness" in snap["body"]
    assert "### Boundary\n\nOnly change general capabilities" in snap["body"]
    assert "### Acceptance criteria\n\nDelivery within budget" in snap["body"]
    assert "### Root cause area" not in snap["body"]


@pytest.mark.parametrize(
    "fields",
    [
        {"Root cause area": "cause", "Boundary": "scope", "Acceptance": "result"},
        {
            "root_cause": "cause",
            "boundary": "scope",
            "acceptance": "result",
            "Root cause area": "old",
        },
        {"root_cause": "cause", "boundary": "scope", "acceptance": "result", "Root cause": "label"},
        {"root_cause": "cause", "boundary": "scope", "Acceptance": "old"},
        {"root_cause": "cause", "boundary": "scope", "acceptance": "result", "extra": "unknown"},
        {"root_cause": 42, "boundary": "scope", "acceptance": "result"},
        None,
        [],
        "not an object",
    ],
)
def test_driver_fallback_rejects_noncanonical_or_malformed_fields(tmp_path, fields) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "Unicode Original report")
    decision = _accept(number)
    decision["fields"] = fields

    outcome = _triager(tmp_path, tracker, _submit([decision])).triage_once()

    assert outcome.needs_info == [number] and outcome.accepted == []
    assert outcome.failed == {}
    issue = tracker.issue(number)
    assert issue["state"] == "closed" and sc.DECLINED in issue["labels"]
    assert sc.PROPOSAL not in issue["labels"]


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (
            "bug",
            {
                "root_cause": "cause",
                "boundary": "scope",
                "acceptance": "result",
                "deliverable": "feature-only field",
            },
        ),
        (
            "feature",
            {
                "boundary": "scope",
                "deliverable": "result",
                "acceptance": "check",
                "root_cause": "bug-only field",
            },
        ),
    ],
)
def test_tool_union_allows_cross_kind_keys_but_driver_rejects_them(tmp_path, kind, fields):
    tracker = FakeTracker()
    number = _report(tracker, "Cross-kind fields")
    decision = _accept(number, kind=kind, fields=fields)
    submitted = {"dispositions": [decision]}
    jsonschema.validate(submitted, ac.dispositions_input_schema())

    outcome = _triager(tmp_path, tracker, json.dumps(submitted)).triage_once()

    assert outcome.needs_info == [number] and outcome.accepted == []
    assert sc.PROPOSAL not in tracker.issue(number)["labels"]


def test_long_multibyte_proposal_title_is_bounded_without_splitting_utf8(tmp_path) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "Original report")
    disposition = _accept(number)
    model_title = "Chinese proposal" * 35
    disposition["proposal_title"] = model_title

    outcome = _triager(tmp_path, tracker, _submit([disposition])).triage_once()

    title = tracker.issue(number)["title"]
    assert title == _proposal_title(model_title)
    assert model_title.startswith(title[:-1]) and title.endswith("…")
    assert len(title.encode("utf-8")) <= 240
    assert outcome.warnings[number] == ["proposal-title-shortened"]


def test_accept_old_needs_triage_data_also_works(tmp_path) -> None:
    """Legacy data (needs-triage label) is mapped into pending via the plane; after accept it likewise promotes to proposal and the old label is cleared."""
    tracker = FakeTracker()
    n = tracker.create_issue(
        IssueDraft(title="Old data", body="x", labels=["bug", sc.NEEDS_TRIAGE, "round-2"])
    ).number
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert sc.PROPOSAL in snap["labels"] and sc.NEEDS_TRIAGE not in snap["labels"]


def test_accept_reclassifies_kind(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "Actually a requirement", kind="bug")  # sim tentatively a bug
    fields = {
        "boundary": "Only add general capabilities",
        "deliverable": "Export interface",
        "acceptance": "Supports bulk export",
    }
    out = _triager(
        tmp_path, tracker, _submit([_accept(n, kind="feature", priority="P2", fields=fields)])
    ).triage_once()
    assert out.accepted == [n]
    labels = tracker.issue(n)["labels"]
    assert "feature" in labels and "bug" not in labels  # Correct the kind


def test_accept_invalid_priority_not_labeled(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "timeout")
    _triager(tmp_path, tracker, _submit([_accept(n, priority="Urgent")])).triage_once()
    labels = tracker.issue(n)["labels"]
    assert sc.PROPOSAL in labels and not any(p in labels for p in sc.PRIORITIES)


def test_accept_missing_fields_downgrades_to_needs_info(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "Broken")
    out = _triager(
        tmp_path, tracker, _submit([_accept(n, fields={"root_cause": "Only filled this in"})])
    ).triage_once()
    assert out.needs_info == [n] and out.accepted == []
    snap = tracker.issue(n)
    assert sc.DECLINED in snap["labels"] and snap["state"] == "closed"


def test_accept_missing_normalized_title_downgrades_to_needs_info(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "Specific issue with a tested subject")
    disposition = _accept(n)
    disposition.pop("proposal_title")
    out = _triager(tmp_path, tracker, _submit([disposition])).triage_once()
    assert out.needs_info == [n] and out.accepted == []


@pytest.mark.parametrize(
    ("target", "bucket"),
    [("uncertain", "needs_info"), ("outside_harness", "rejected")],
)
def test_out_of_scope_accept_closes_report_and_recovery_unit(tmp_path, target, bucket) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "Missing input file")
    frozen_issue = tracker.list_open_issues()[0]
    disposition = _accept(number)
    disposition["artifact"]["implementation_target"] = target
    disposition["reason"] = "Ownership of the file ingestion implementation remains to be confirmed"
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([disposition]),
        recovery=recovery,
    )

    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        outcome = triager.triage_once(pending=[frozen_issue])

    assert getattr(outcome, bucket) == [number]
    assert outcome.accepted == [] and outcome.failed == {}
    assert outcome.warnings[number] == ["out-of-product-scope-normalized"]
    snap = tracker.issue(number)
    assert snap["state"] == "closed" and sc.DECLINED in snap["labels"]
    assert sc.PROPOSAL not in snap["labels"]
    assert any(
        "original disposition was accept" in comment and target in comment
        for comment in snap["comments"]
    )
    unit = recovery.unit(
        round_no=1,
        stage="triage",
        key=operation_key("triage-worker-0", "report", number),
    )
    assert unit["status"] == "completed"
    assert unit["observed_postconditions"]["bucket"] == bucket


def test_accept_invalid_kind_downgrades(tmp_path) -> None:
    tracker = FakeTracker()
    n = _report(tracker, "Strange kind")
    out = _triager(tmp_path, tracker, _submit([_accept(n, kind="rfc")])).triage_once()
    assert out.needs_info == [n]


def test_reject_and_needs_info_decline_with_reason(tmp_path) -> None:
    tracker = FakeTracker()
    a = _report(tracker, "Out of scope")
    b = _report(tracker, "Unclear")
    canned = _submit(
        [
            {
                "issue": a,
                "disposition": "reject",
                "reason": "What needs to be changed is launcher（Orchestration layer）",
            },
            {
                "issue": b,
                "disposition": "needs_info",
                "reason": "Trace contains no useful information",
            },
        ]
    )

    class PerReportTriager(_StubTriager):
        def _run_agent(self, *, pending: list) -> str:
            decisions = json.loads(self._canned)["dispositions"]
            return _submit([d for d in decisions if d["issue"] == pending[0].number])

    out = PerReportTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        canned=canned,
    ).triage_once()
    assert out.rejected == [a] and out.needs_info == [b]
    for n in (a, b):
        snap = tracker.issue(n)
        assert sc.DECLINED in snap["labels"] and snap["state"] == "closed"
        assert sc.plane(snap["labels"]) is None  # Terminal state is not on any plane
    assert any("launcher" in c for c in tracker.issue(a)["comments"])


def test_no_submit_is_noop(tmp_path) -> None:
    """Agent did not call submit (prose return) → no-op this round; the report is left as-is for the next round."""
    tracker = FakeTracker()
    n = _report(tracker, "Retain round")
    out = _triager(tmp_path, tracker, "I finished the run but did not submit").triage_once()
    assert out.handled == 0
    assert sc.REPORT in tracker.issue(n)["labels"]  # Untouched


def test_finalizer_is_bounded_and_report_histories_do_not_mix(tmp_path, monkeypatch) -> None:
    tracker = FakeTracker()
    ids = [_report(tracker, "first report"), _report(tracker, "second report")]
    calls = []

    def invoke(agent_def, message, **kwargs):
        report = kwargs["subject"]["id"]
        calls.append((report, kwargs["max_iterations"], kwargs["history"]))
        if kwargs["history"] is None:
            kwargs["on_history"]([{"role": "tool", "content": f"evidence for {report}"}])
        else:
            assert kwargs["history"] == [{"role": "tool", "content": f"evidence for {report}"}]
        return "no submit"

    monkeypatch.setattr("ahe_beta.demand.triage.run_agent_def", invoke)
    triager = Triager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
    )
    outcome = triager.triage_once()

    assert len(calls) == 4
    assert [limit for _, limit, _ in calls] == [None, 8, None, 8]
    assert [report for report, _, _ in calls] == [
        str(ids[0]),
        str(ids[0]),
        str(ids[1]),
        str(ids[1]),
    ]
    assert calls[0][2] is calls[2][2] is None
    assert outcome.handled == 0 and set(outcome.failed) == set(ids)
    assert all(sc.REPORT in tracker.issue(number)["labels"] for number in ids)


def test_core_update_failure_is_reported_and_report_remains(tmp_path: Path) -> None:
    class BrokenUpdateTracker(FakeTracker):
        def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
            raise RuntimeError("write failed")

    tracker = BrokenUpdateTracker()
    n = _report(tracker, "Specific example")
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert n in out.failed and "write failed" in out.failed[n]
    assert out.accepted == []
    snap = tracker.issue(n)
    assert (
        sc.REPORT in snap["labels"] and snap["title"] == "Specific example" and snap["body"] == "x"
    )


def test_audit_comment_failure_is_warning_but_proposal_is_created(tmp_path: Path) -> None:
    class BrokenCommentTracker(FakeTracker):
        def add_comment(self, number: int, body: str) -> None:
            raise RuntimeError("comment failed")

    tracker = BrokenCommentTracker()
    n = _report(tracker, "Specific example")
    out = _triager(tmp_path, tracker, _submit([_accept(n)])).triage_once()
    assert out.accepted == [n]
    assert out.warnings[n] == ["Original report audit comment write failed"]
    assert sc.PROPOSAL in tracker.issue(n)["labels"]


def test_out_of_batch_issue_skipped(tmp_path) -> None:
    """A disposition pointing to a issue number not in this batch → skip (prevents out-of-bounds changes)."""
    tracker = FakeTracker()
    n = _report(tracker, "Within the batch")
    out = _triager(tmp_path, tracker, _submit([_accept(999)])).triage_once()
    assert out.accepted == []
    assert out.failed == {n: "missing-report-disposition"}
    assert sc.REPORT in tracker.issue(n)["labels"]


def test_shard_pending_param_scopes_batch(tmp_path) -> None:
    """Spec-0029/T8 shard support: when a pending subset is passed in, only that subset is processed; the remaining reports are left untouched and are not fed to the agent."""
    tracker = FakeTracker()
    a = _report(tracker, "Within the slice")
    b = _report(tracker, "Outside the slice")
    backlog = tracker.list_open_issues()
    shard = [i for i in backlog if i.number == a]
    t = _triager(tmp_path, tracker, _submit([_accept(a)]))
    out = t.triage_once(pending=shard)
    assert out.accepted == [a]
    assert [i.number for i in t.seen_pending] == [a]  # Feed only this shard
    assert sc.REPORT in tracker.issue(b)["labels"]  # Leave everything outside the shard untouched


def test_proposal_labels_keep_attributes_only() -> None:
    cur = ["bug", sc.REPORT, "round-3", "misc"]
    out = _proposal_labels(cur, "feature", "P0")
    assert set(out) == {"misc", "round-3", "feature", sc.PROPOSAL, sc.FROM_TRIAGE, "P0"}


def test_recovery_replays_saved_triage_output_without_model_or_duplicate_comment(tmp_path) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "recover me")
    frozen_issue = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)

    class CrashBeforeCompletion(_StubTriager):
        crashed = False

        def _complete_recovery_item(self, **kwargs) -> None:
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after tracker apply")
            return super()._complete_recovery_item(**kwargs)

    first = CrashBeforeCompletion(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RuntimeError, match="injected"):
            first.triage_once(pending=[frozen_issue])
    assert sc.PROPOSAL in tracker.issue(number)["labels"]

    resumed = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned="must not be used",
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        outcome = resumed.triage_once(pending=[frozen_issue])
    assert outcome.accepted == [number] and outcome.failed == {}
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1
    assert "### Root cause\n\nentry.py No budget awareness" in tracker.issue(number)["body"]


@pytest.mark.parametrize(
    "fields",
    [
        {"Root cause area": "Reason", "Boundary": "Scope", "Acceptance": "Result"},
        {
            "root_cause": "Reason",
            "boundary": "Scope",
            "acceptance": "Result",
            "Acceptance": "Old key",
        },
    ],
)
def test_recovery_rejects_noncanonical_saved_fields_without_mutating_report(
    tmp_path, fields
) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "Original Unicode Report")
    frozen_issue = tracker.list_open_issues()[0]
    before = json.dumps(tracker.issue(number), sort_keys=True)
    recovery = _recovery(tmp_path)
    key = operation_key("triage-worker-0", "report", number)
    recovery.begin_unit(
        round_no=1,
        stage="triage",
        key=key,
        input_value={"report": frozen_issue.to_dict()},
        expected_postconditions={"completed": True},
        dependencies=("users",),
    )
    decision = _accept(number)
    decision["fields"] = fields
    saved_output = {"dispositions": [decision]}
    recovery.save_output(round_no=1, stage="triage", key=key, output=saved_output)

    class ResumeOnlyTriager(_StubTriager):
        def _run_agent(self, *, pending: list) -> str:
            pytest.fail("Saved output must be checked without running the model again")

    resumed = ResumeOnlyTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned="must not be used",
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            resumed.triage_once(pending=[frozen_issue])

    unit = recovery.unit(round_no=1, stage="triage", key=key)
    assert unit["status"] == "failed" and unit["error"] == "saved-submit-contract-mismatch"
    assert recovery.read_output(round_no=1, stage="triage", key=key) == saved_output
    assert json.dumps(tracker.issue(number), sort_keys=True) == before
    assert resumed.agent_calls == 0


@pytest.mark.parametrize("with_recovery", [False, True])
def test_conflicting_decisions_do_not_partially_migrate_report(tmp_path, with_recovery) -> None:
    tracker = FakeTracker()
    number = _report(tracker, "one report, two decisions")
    frozen_issue = tracker.list_open_issues()[0]
    before = json.dumps(tracker.issue(number), sort_keys=True)
    recovery = _recovery(tmp_path) if with_recovery else None
    conflicting = _accept(number)
    conflicting.update(disposition="needs_info", reason="uncertain")
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number), conflicting]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        if recovery is not None:
            with pytest.raises(RecoveryConflictError, match="remain incomplete"):
                triager.triage_once(pending=[frozen_issue])
            unit = recovery.unit(round_no=1, stage="triage", key=triager._recovery_key(number))
            assert unit["status"] == "failed"
            assert unit["output_digest"] is None
            assert unit["error"] == "invalid-report-disposition-count"
        else:
            outcome = triager.triage_once(pending=[frozen_issue])
            assert outcome.failed == {number: "invalid-report-disposition-count"}
            assert not outcome.accepted and not outcome.needs_info
    assert json.dumps(tracker.issue(number), sort_keys=True) == before


@pytest.mark.parametrize("external_edit", [False, True])
def test_recovery_reconciles_partial_proposal_only_if_content_is_ours(
    tmp_path, external_edit
) -> None:
    model_title = "Chinese proposal" * 35

    class PartialWriteTracker(FakeTracker):
        fail_once = True

        def update_issue(self, number, *, title, body, labels):
            if self.fail_once:
                self.fail_once = False
                super().update_issue(number, title=model_title[:70] + "…", body=body, labels=labels)
                raise RuntimeError("simulated server title normalization")
            return super().update_issue(number, title=title, body=body, labels=labels)

    tracker = PartialWriteTracker()
    number = _report(tracker, "Original report")
    frozen_issue = tracker.list_open_issues()[0]
    disposition = _accept(number)
    disposition["proposal_title"] = model_title
    recovery = _recovery(tmp_path)
    args = (
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
    )
    first = _StubTriager(*args, canned=_submit([disposition]), recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            first.triage_once(pending=[frozen_issue])
    assert recovery.unit(
        round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
    )["output_digest"]

    if external_edit:
        current = tracker.issue(number)
        FakeTracker.update_issue(
            tracker, number, title=current["title"], body="human edit", labels=current["labels"]
        )
    resumed = _StubTriager(*args, canned="must not be used", recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        if external_edit:
            with pytest.raises(RecoveryConflictError, match="remain incomplete"):
                resumed.triage_once(pending=[frozen_issue])
        else:
            outcome = resumed.triage_once(pending=[frozen_issue])
            assert outcome.accepted == [number]
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1
    if external_edit:
        assert tracker.issue(number)["body"] == "human edit"
    else:
        assert tracker.issue(number)["title"] == _proposal_title(model_title)


def test_recovery_retries_transient_read_without_rerunning_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class FlakyReadTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            if self.reads == 1:
                raise requests.ConnectionError("connection reset")
            return super().get_issue(number=number)

    tracker = FlakyReadTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert triager.agent_calls == 1 and tracker.reads == 2
    assert result.warnings[number] == ["tracker-write-retried"]
    assert len(tracker.issue(number)["comments"]) == 1
    assert (
        recovery.unit(
            round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
        )["status"]
        == "completed"
    )


def test_recovery_reconciles_lost_update_response_without_second_write(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class LostResponseTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            super().update_issue(number, title=title, body=body, labels=labels)
            if self.writes == 1:
                raise requests.ConnectionError("response lost after write")

    tracker = LostResponseTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert tracker.writes == 1 and triager.agent_calls == 1
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_reconciles_lost_decline_response_without_second_write(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class LostResponseTracker(FakeTracker):
        writes = 0

        def transition_issue(self, number, *, state, labels):
            self.writes += 1
            super().transition_issue(number, state=state, labels=labels)
            if self.writes == 1:
                raise requests.ConnectionError("response lost after close")

    tracker = LostResponseTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    disposition = {"issue": number, "disposition": "reject", "reason": "Out of scope"}
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([disposition]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.rejected == [number] and result.failed == {}
    assert tracker.writes == 1 and triager.agent_calls == 1
    assert tracker.issue(number)["state"] == "closed"
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_stops_after_bounded_transient_retries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class UnavailableTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            raise requests.ConnectionError("Gitea unavailable")

    tracker = UnavailableTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            triager.triage_once(pending=[frozen])
    assert tracker.reads == 3 and triager.agent_calls == 1
    assert tracker.issue(number)["title"] == "Original report"
    assert (
        recovery.unit(
            round_no=1, stage="triage", key=operation_key("triage-worker-0", "report", number)
        )["status"]
        == "failed"
    )


def test_recovery_replays_only_our_partial_migration(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class PartialMigrationTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            if self.writes == 1:
                original_labels = self.issue(number)["labels"]
                super().update_issue(number, title=title, body=body, labels=original_labels)
                raise IssueMigrationError(
                    number=number,
                    operation="update_issue",
                    primary=requests.ConnectionError("labels response lost"),
                    rollback=None,
                    observed=self.issue(number),
                )
            return super().update_issue(number, title=title, body=body, labels=labels)

    tracker = PartialMigrationTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert tracker.writes == 2 and triager.agent_calls == 1
    assert sc.PROPOSAL in tracker.issue(number)["labels"]
    assert len(tracker.issue(number)["comments"]) == 1


def test_recovery_does_not_overwrite_external_edit_after_lost_response(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class ConcurrentEditTracker(FakeTracker):
        writes = 0

        def update_issue(self, number, *, title, body, labels):
            self.writes += 1
            super().update_issue(number, title=title, body="external edit", labels=labels)
            raise requests.ConnectionError("response lost")

    tracker = ConcurrentEditTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            triager.triage_once(pending=[frozen])
    assert tracker.writes == 1
    assert tracker.issue(number)["body"] == "external edit"


def test_recovery_retries_temporary_server_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class TemporaryServerErrorTracker(FakeTracker):
        reads = 0

        def get_issue(self, *, number):
            self.reads += 1
            if self.reads == 1:
                raise GiteaError(503, f"/issues/{number}")
            return super().get_issue(number=number)

    tracker = TemporaryServerErrorTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    triager = _StubTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=_submit([_accept(number)]),
        recovery=_recovery(tmp_path),
    )
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = triager.triage_once(pending=[frozen])
    assert result.accepted == [number] and tracker.reads == 2


def test_recovery_reuses_saved_output_after_previous_tracker_outage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("ahe_beta.demand.triage.time.sleep", lambda _: None)

    class RecoveredTracker(FakeTracker):
        unavailable = True

        def get_issue(self, *, number):
            if self.unavailable:
                raise requests.ConnectionError("Gitea unavailable")
            return super().get_issue(number=number)

    tracker = RecoveredTracker()
    number = _report(tracker, "Original report")
    frozen = tracker.list_open_issues()[0]
    recovery = _recovery(tmp_path)
    args = (
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
    )
    first = _StubTriager(*args, canned=_submit([_accept(number)]), recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            first.triage_once(pending=[frozen])
    assert first.agent_calls == 1
    tracker.unavailable = False
    resumed = _StubTriager(*args, canned="model must not run again", recovery=recovery)
    with bind_usage_context(round_no=1, operation="triage-worker-0"):
        result = resumed.triage_once(pending=[frozen])
    assert result.accepted == [number] and result.failed == {}
    assert resumed.agent_calls == 0
    assert len(tracker.issue(number)["comments"]) == 1


@pytest.mark.parametrize("prerequisite", ["feedback_imported", "objective_grading"])
def test_feedback_uses_its_actual_stage_dependency(tmp_path, prerequisite):
    """Role recovery agrees with imported or independently graded feedback."""
    tracker = FakeTracker()
    number = _report(tracker, "historical report")
    triager = _triager(
        tmp_path,
        tracker,
        _submit([{"issue": number, "disposition": "reject", "reason": "duplicate"}]),
    )
    recovery = RecoveryStore.initialize(
        root=tmp_path / "bootstrap",
        identity=RecoveryIdentity("exp", "child", "config", "controller", "bootstrap"),
    )
    recovery.freeze_round(round_no=1, user_sha="seed", plan=[])
    key = operation_key("feedback-imported")
    recovery.begin_unit(round_no=1, stage=prerequisite, key=key, input_value={})
    recovery.complete_unit(round_no=1, stage=prerequisite, key=key)
    recovery.complete_stage(round_no=1, stage=prerequisite)
    triager.bind_recovery(recovery)
    triager.bind_feedback_dependency(prerequisite)
    with bind_usage_context(round_no=1, operation="continuation-bootstrap-triage"):
        result = triager.triage_once()
    assert result.rejected == [number]
    state = recovery.round_state(round_no=1)
    assert state["stages"]["triage"]["dependencies"] == [prerequisite]
    assert "users" not in state["stages"]
    triager.bind_feedback_dependency("users")
    assert triager._feedback_dependency == "users"
