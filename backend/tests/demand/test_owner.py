"""Delivery Router unit tests: lossless handoff, exact deduplication, Architect covers are not re-processed by Owner, missed items fail open."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.owner import AdmitOutcome, Owner
from ahe_beta.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore


class _StubOwner(Owner):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.agent_calls = 0
        self.seen_review: list = []

    def _run_agent(self, *, proposals: list, ready: list, trend: list) -> str:
        self.agent_calls += 1
        self.seen_review = proposals
        return self._canned


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _owner(tmp_path: Path, tracker: FakeTracker, canned: str, **kw) -> _StubOwner:
    store = SessionStore(tmp_path / "sessions")
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=2, reason="Slow"),
        )
    )
    return _StubOwner(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned=canned, **kw
    )


def _triage_proposal(tracker: FakeTracker, title: str, *, prio: str = "P2") -> int:
    return tracker.create_issue(
        IssueDraft(
            title=title,
            body="Verbatim user report",
            labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE, prio],
        )
    ).number


def _architect_proposal(tracker: FakeTracker, title: str, covers: list[int] | None = None) -> int:
    body = "### Problem\n\nx"
    line = sc.format_covers_line(covers or [])
    if line:
        body = f"{body}\n\n{line}"
    return tracker.create_issue(
        IssueDraft(title=title, body=body, labels=[sc.PROPOSAL, sc.FROM_ARCHITECT])
    ).number


def _submit(decisions: list) -> str:
    for decision in decisions:
        decision.setdefault("handoff_summary", "Hand off to OpenAgents Planning")
        decision.setdefault("preserved_capabilities", ["Retain original capability"])
        decision.setdefault("acceptance_groups", ["Independently verify the original goal"])
    return json.dumps({"decisions": decisions}, ensure_ascii=False)


def _owner_recovery(
    tmp_path: Path, *, architect_proposals: list[int] | None = None
) -> RecoveryStore:
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    for stage in ("divergent", "architect"):
        key = operation_key(stage, "complete")
        store.begin_unit(
            round_no=1,
            stage=stage,
            key=key,
            input_value={},
            expected_postconditions={"completed": True},
        )
        store.complete_unit(
            round_no=1,
            stage=stage,
            key=key,
            observed_postconditions={
                "completed": True,
                **({"proposal_numbers": architect_proposals} if stage == "architect" else {}),
            },
        )
        store.complete_stage(round_no=1, stage=stage)
    return store


def test_submit_admission_yaml_matches_contract() -> None:
    """drift-guard: the input_schema of submit_admission.tool.yaml is deep-equal to admission_input_schema()."""
    import yaml

    from ahe_beta.demand.agent_contract import admission_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "owner"
        / "tools"
        / "submit_admission.tool.yaml"
    )
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["input_schema"] == admission_input_schema()


def test_owner_agent_exposes_only_admission_tool() -> None:
    """Owner evaluates supplied artifacts and cannot reopen source/session investigation."""
    import yaml

    path = Path(__file__).resolve().parents[2] / "agent_defs" / "owner" / "agent.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [tool["name"] for tool in config["tools"]] == [
        "submit_observation_gap",
        "submit_admission",
    ]
    assert config["stop_tools"] == ["submit_admission"]


def test_no_proposals_is_noop(tmp_path: Path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="ready Items", body="x", labels=[sc.READY]))
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert isinstance(out, AdmitOutcome) and out.admitted == []
    assert o.agent_calls == 0


def test_clean_triage_singleton_requires_explicit_model_admission(tmp_path: Path) -> None:
    tracker = FakeTracker()
    n = _triage_proposal(tracker, "unidecode Installation timeout")
    o = _owner(tmp_path, tracker, _submit([{"issue": n, "decision": "admit"}]))
    out = o.admit_once()
    assert out.admitted == [n] and out.mechanical == []
    assert o.agent_calls == 1
    assert [i.number for i in o.seen_review] == [n]
    snap = tracker.issue(n)
    assert sc.is_ready(labels=snap["labels"], state=snap["state"])
    # handoff token persisted to the store
    assert sc.OPENAGENTS in snap["labels"] and sc.PROPOSAL not in snap["labels"]
    assert "P2" in snap["labels"]  # the suggested priority carries over as the final value
    assert snap["comments"]
    assert all("<!-- openagents:agent=ahe-beta -->" in body for body in snap["comments"])


def test_similar_but_nonidentical_proposals_are_preserved(tmp_path: Path) -> None:
    """Similar titles do not constitute an exact duplicate; a wrong merge is reverted by the driver back into independent handoffs."""
    tracker = FakeTracker()
    a = _triage_proposal(tracker, "Clicking the export button does nothing")
    b = _triage_proposal(tracker, "Clicking the export button produces no response")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": a, "decision": "admit"}, {"issue": b, "decision": "merge", "into": a}]),
    )
    out = o.admit_once()
    assert o.agent_calls == 1
    assert {i.number for i in o.seen_review} == {a, b}
    assert out.admitted == [a, b] and out.merged == []
    assert b in out.invalid
    assert sc.is_ready(labels=tracker.issue(b)["labels"], state="open")


def test_exact_duplicate_can_merge(tmp_path: Path) -> None:
    tracker = FakeTracker()
    a = _triage_proposal(tracker, "Exactly the same")
    b = _triage_proposal(tracker, "Exactly the same")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": a, "decision": "admit"}, {"issue": b, "decision": "merge", "into": a}]),
    )
    out = o.admit_once()
    assert out.admitted == [a] and out.merged == [b]
    assert sc.MERGED in tracker.issue(b)["labels"]


@pytest.mark.parametrize("bad_overlap", [None, "invalid", [999], [True]])
def test_cross_route_overlap_preserves_independent_handoffs(tmp_path, bad_overlap):
    tracker = FakeTracker()
    pm = tracker.create_issue(
        IssueDraft(
            "Users can correct course at any time",
            "product outcome",
            [sc.PROPOSAL, sc.FROM_DIVERGENT],
        )
    ).number
    architect = _architect_proposal(tracker, "Control the lifecycle")
    rows = [
        {
            "issue": pm,
            "decision": "admit",
            "delivery_overlaps": [architect],
            "handoff_summary": "Shared control implementation，but PM Independently verify that users can correct course promptly",
        },
        {"issue": architect, "decision": "admit", "delivery_overlaps": bad_overlap},
    ]
    owner = _owner(tmp_path, tracker, _submit(rows))
    out = owner.admit_once()
    assert set(out.admitted) == {pm, architect}
    assert not out.merged and not out.failed
    assert architect in out.invalid
    assert any(
        f"Delivery overlaps (association, not merging): #{architect}" in c
        for c in tracker.issue(pm)["comments"]
    )
    assert "product outcome" == tracker.issue(pm)["body"]


def test_overlap_can_reference_ready_but_not_self_or_report(tmp_path):
    tracker = FakeTracker()
    pm = _triage_proposal(tracker, "new")
    ready = tracker.create_issue(IssueDraft("existing", "x", [sc.READY])).number
    report = tracker.create_issue(IssueDraft("raw", "x", [sc.REPORT])).number
    owner = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": pm, "decision": "admit", "delivery_overlaps": [pm, ready, report]},
            ]
        ),
    )
    out = owner.admit_once()
    assert out.admitted == [pm] and pm in out.invalid
    comments = tracker.issue(pm)["comments"]
    assert any(f"Delivery overlaps (association, not merging): #{ready}" in c for c in comments)
    assert all(f"#{report}" not in c for c in comments)


def test_review_admit_with_priority_override(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _architect_proposal(tracker, "Structure：Budget aware")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit", "priority": "P0"}]))
    out = o.admit_once()
    assert out.admitted == [s]
    labels = tracker.issue(s)["labels"]
    # Spec-0032/T3: admit stamps the delivery-plane handoff token openagents (once discovered, vigil stamps ready itself), not ready directly.
    assert sc.OPENAGENTS in labels and sc.READY not in labels and "P0" in labels
    # the read side is still in the READY plane (funnel/backpressure/frontend conventions unchanged)
    assert sc.plane(labels) == sc.READY


def test_explicit_incomplete_hold_and_unlisted_default_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    bad = _architect_proposal(tracker, "Overfit proposal")
    quiet = _architect_proposal(tracker, "Unmentioned proposal")
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [{"issue": bad, "decision": "hold", "reason": "Missing observable acceptance result"}]
        ),
    )
    out = o.admit_once()
    assert out.held == [bad] and quiet in out.admitted
    assert sc.PROPOSAL in tracker.issue(bad)["labels"]
    assert sc.is_ready(labels=tracker.issue(quiet)["labels"], state="open")


def test_invalid_explicit_decision_is_held_not_default_admitted(tmp_path: Path) -> None:
    tracker = FakeTracker()
    proposal = _architect_proposal(tracker, "Missing hold Reason")
    o = _owner(tmp_path, tracker, _submit([{"issue": proposal, "decision": "hold"}]))

    out = o.admit_once()

    assert out.held == [proposal]
    assert proposal in out.invalid
    assert sc.PROPOSAL in tracker.issue(proposal)["labels"]


def test_owner_does_not_process_architect_covers(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p1 = _triage_proposal(tracker, "Symptom A：State loss")
    p2 = _triage_proposal(tracker, "Urgent fix B：Crash and unexpected exit", prio="P0")
    s = _architect_proposal(tracker, "Structure：State contract refactoring", covers=[p1, p2])
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": s, "decision": "admit"}, {"issue": p2, "decision": "admit"}]),
    )
    out = o.admit_once()
    assert set(out.admitted) == {p1, p2, s}
    # Architect already handles covers during creation; Owner does not re-process them
    assert out.merged == []
    assert all(sc.is_ready(labels=tracker.issue(n)["labels"], state="open") for n in (p1, p2, s))


def test_covers_untouched_when_structural_held(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p1 = _triage_proposal(tracker, "Symptom A：Handoff breakdown")
    s = _architect_proposal(tracker, "Structure：Handoff refactoring", covers=[p1])
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": s, "decision": "hold", "reason": "Missing acceptance interface"},
                {"issue": p1, "decision": "hold", "reason": "Missing reproduction steps"},
            ]
        ),
    )
    out = o.admit_once()
    assert s in out.held and p1 in out.held and out.merged == []
    assert sc.PROPOSAL in tracker.issue(p1)["labels"]  # Owner does not consume covers


def test_invalid_merge_target_is_preserved_as_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _architect_proposal(tracker, "Parallel work on a nonexistent ticket")
    o = _owner(tmp_path, tracker, _submit([{"issue": p, "decision": "merge", "into": 999}]))
    out = o.admit_once()
    assert p in out.admitted and p in out.invalid and out.merged == []


def test_merge_target_cannot_be_held_proposal(tmp_path: Path) -> None:
    tracker = FakeTracker()
    source = _architect_proposal(tracker, "Pending merge")
    held = _architect_proposal(tracker, "Deferred goal")
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": source, "decision": "merge", "into": held},
                {"issue": held, "decision": "hold", "reason": "Missing acceptance interface"},
            ]
        ),
    )
    out = o.admit_once()
    assert source in out.admitted and source in out.invalid
    assert held in out.held
    assert sc.is_ready(labels=tracker.issue(source)["labels"], state="open")


def test_owner_core_write_failure_is_reported(tmp_path: Path) -> None:
    class BrokenSetLabelsTracker(FakeTracker):
        def set_labels(self, number: int, labels: list[str]) -> None:
            raise RuntimeError("set labels failed")

    tracker = BrokenSetLabelsTracker()
    p = _architect_proposal(tracker, "Write failure during handoff")
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert p in out.failed and p in out.held
    assert sc.PROPOSAL in tracker.issue(p)["labels"]


def test_review_disabled_mechanically_handoffs_every_proposal(tmp_path: Path) -> None:
    """review=False (roster owner=0): purely mechanical handoff; everything admitted with zero LLM."""
    tracker = FakeTracker()
    clean = _triage_proposal(tracker, "Clean single case")
    s = _architect_proposal(tracker, "Structural proposal")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit"}]), review=False)
    out = o.admit_once()
    assert set(out.admitted) == {clean, s} and out.mechanical == []
    assert out.held == []
    assert o.agent_calls == 0


def test_recovery_owner_only_admits_pm_and_architect_processed_proposals(tmp_path: Path) -> None:
    tracker = FakeTracker()

    def create(title: str, labels: list[str]) -> int:
        return tracker.create_issue(IssueDraft(title=title, body="summary", labels=labels)).number

    pm = create("PM", [sc.PROPOSAL, sc.FROM_DIVERGENT])
    architect_proposal = create("Architect", [sc.PROPOSAL, sc.FROM_ARCHITECT])
    triage = create("retained triage", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    gap = create("retained gap", [sc.PROPOSAL, sc.OBSERVATION_GAP])
    merged = create("merged source", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    late_gap = create("late gap", [sc.PROPOSAL, sc.OBSERVATION_GAP])
    stray = create("unseen triage", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    recovery = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    recovery.freeze_round(round_no=1, user_sha="user", plan=[])
    pm_key = operation_key("pm", "output")
    recovery.begin_unit(round_no=1, stage="divergent", key=pm_key, input_value={})
    recovery.complete_unit(
        round_no=1,
        stage="divergent",
        key=pm_key,
        observed_postconditions={"proposal_numbers": [pm]},
    )
    recovery.complete_stage(round_no=1, stage="divergent")
    architect_key = operation_key("architect", "grouping")
    seen = [i.to_dict() for i in tracker.list_open_issues() if i.number in {triage, gap, merged}]
    recovery.begin_unit(
        round_no=1, stage="architect", key=architect_key, input_value={"issues": seen}
    )
    recovery.complete_unit(round_no=1, stage="architect", key=architect_key)
    worker_key = operation_key("architect", "batch")
    recovery.begin_unit(round_no=1, stage="architect", key=worker_key, input_value={})
    recovery.complete_unit(
        round_no=1,
        stage="architect",
        key=worker_key,
        observed_postconditions={
            "merged_numbers": [merged],
            "proposal_numbers": [architect_proposal],
        },
    )
    recovery.complete_stage(round_no=1, stage="architect")

    owner = _owner(tmp_path, tracker, _submit([]), review=False, recovery=recovery)
    with bind_usage_context(round_no=1, operation="owner-stage"):
        outcome = owner.admit_once()
    assert set(outcome.admitted) == {pm, architect_proposal, triage, gap}
    assert owner.agent_calls == 0
    for number in (merged, late_gap, stray):
        assert sc.PROPOSAL in tracker.issue(number)["labels"]


def test_review_prompt_is_handoff_only(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _triage_proposal(tracker, "Failure in a specific task")
    o = _owner(tmp_path, tracker, _submit([]))
    issue = tracker.list_open_issues()[0]
    msg = o._review_message(proposals=[issue], ready=[], trend=[])
    assert "Delivery Router" in msg
    assert "handoff without losing information" in msg
    assert "Do not review upstream solutions" in msg
    assert "Architect already handled `covers` sources" in msg
    assert "must verify using repository tools" not in msg
    assert f"#{p}" in msg


def test_owner_receives_normalized_body_for_every_proposal_source(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = tracker.create_issue(
        IssueDraft(
            title="Exploration scope runs out of control under precise instructions",
            body=(
                "## Triage normalized proposal (implementation target: harness)\n\n"
                "### Root cause\n\nagents/main.md Unbounded exploration despite precise instructions\n\n"
                "### Boundary\n\nChange only the generic parts harness Behavior"
            ),
            labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE, "P2"],
        )
    ).number
    issue = tracker.list_open_issues()[0]
    rendered = Owner._format_index([issue], store=None)
    assert "agents/main.md Unbounded exploration despite precise instructions" in rendered
    assert "Change only the generic parts harness Behavior" in rendered
    assert f"#{p}" in rendered


def test_no_submit_defaults_to_direct_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _architect_proposal(tracker, "Structural proposal")
    o = _owner(tmp_path, tracker, "Prose not tuned submit")
    out = o.admit_once()
    assert s in out.admitted and out.held == []


def test_recovery_replays_owner_decisions_after_partial_admission(tmp_path: Path) -> None:
    class CrashAfterLabelsTracker(FakeTracker):
        crashed = False
        label_writes = 0

        def set_labels(self, number: int, labels: list[str]) -> None:
            self.label_writes += 1
            super().set_labels(number, labels)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after admission labels")

    tracker = CrashAfterLabelsTracker()
    proposal = _architect_proposal(tracker, "resume owner")
    recovery = _owner_recovery(tmp_path, architect_proposals=[proposal])
    owner = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": proposal, "decision": "admit"}]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="owner-stage"):
        with pytest.raises(
            RecoveryConflictError,
            match=f"#{proposal}: RuntimeError: injected after admission labels",
        ):
            owner.admit_once()
    failed = recovery.unit(
        round_no=1,
        stage="owner",
        key=operation_key("owner-stage", "decisions"),
    )
    assert f"#{proposal}: RuntimeError: injected after admission labels" in failed["error"]
    tracker.set_labels(proposal, [sc.OPENAGENTS, sc.READY, "openagents-dispatching"])
    with bind_usage_context(round_no=1, operation="owner-stage"):
        outcome = owner.admit_once()
    assert outcome.admitted == [proposal]
    assert owner.agent_calls == 1
    assert len(tracker.issue(proposal)["comments"]) == 2
    assert tracker.label_writes == 2
    assert tracker.issue(proposal)["labels"] == [sc.OPENAGENTS, sc.READY, "openagents-dispatching"]
