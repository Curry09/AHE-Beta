# Spec-0029/T5: divergent = unit tests of the discovery-track generator (stub agent, no real LLM).
"""Verify divergent: consumes session evidence (user experience index) + no-repeat reference (compact index), produces proposal+from-divergent
(not claimable); hard cap of 3 per round; skips entries with incomplete fields; drift-guard (submit_divergent yaml == pm_input_schema).
The old gate three-path tests were deleted along with the retirement of gate_once — see test_owner.py for admission adjudication tests (Spec-0029/T6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.divergent import Divergent, DivergentOutcome
from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore, operation_key
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


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _seed_session(store: SessionStore, *, score: int = 3) -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason="timeout then ask status"),
        )
    )


def _pm_artifact() -> dict:
    return {
        "user_goal": "Maintain continuous awareness of long running task progress",
        "observed_behaviors": ["Repeatedly ask for status after timeout"],
        "experience_tension": "The system is working but the user cannot tell whether it is still worth waiting",
        "product_opportunity": "Provide continuous、Understandable progress feedback",
        "desired_outcome": "The user does not need follow up questions to regain certainty",
        "evidence_sessions": ["SESSION_ID"],
        "solution_level": "product_capability",
        "abstraction_rationale": "Describe only user perceptible capabilities and results",
    }


def _submit(proposals: list) -> str:
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


class _StubDivergent(Divergent):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_trend: list = []
        self.seen_reference: list = []
        self.agent_calls = 0

    def _run_agent(self, *, trend: list, reference: list) -> str:
        self.agent_calls += 1
        self.seen_trend = trend
        self.seen_reference = reference
        return self._canned


def _divergent(tmp_path: Path, tracker: FakeTracker, canned: str, **kw) -> _StubDivergent:
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store)
    canned = canned.replace("SESSION_ID", str(store.index()[0]["session_id"]))
    return _StubDivergent(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned=canned, **kw
    )


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
    users = operation_key("users")
    store.begin_unit(
        round_no=1,
        stage="users",
        key=users,
        input_value={},
        expected_postconditions={"completed": True},
        dependencies=("round_started",),
    )
    store.complete_unit(round_no=1, stage="users", key=users)
    store.complete_stage(round_no=1, stage="users")
    return store


def test_submit_divergent_yaml_matches_contract() -> None:
    """drift-guard: input_schema of submit_divergent.tool.yaml = pm_input_schema() (same PM artifact shape)."""
    import yaml

    from ahe_beta.demand.agent_contract import pm_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "divergent_pm"
        / "tools"
        / "submit_divergent.tool.yaml"
    )
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["input_schema"] == pm_input_schema()


def test_divergent_creates_unclaimable_proposal(tmp_path: Path) -> None:
    tracker = FakeTracker()
    canned = _submit([{"title": "Productize status handoff", **_pm_artifact()}])
    d = _divergent(tmp_path, tracker, canned, round_provider=lambda: 2)
    out = d.propose_once()
    assert isinstance(out, DivergentOutcome) and out.count == 1
    issues = tracker.list_open_issues()
    assert len(issues) == 1
    labels = issues[0].labels
    assert sc.PROPOSAL in labels and sc.FROM_DIVERGENT in labels
    assert "round-2" in labels
    assert sc.plane(labels) == sc.PROPOSAL
    assert not sc.is_ready(labels=labels, state="open")  # Not claimable; awaiting Owner admission


def test_divergent_inputs_are_session_first(tmp_path: Path) -> None:
    """Input = user experience index + no-repeat reference (open proposals/ready); does not consume triaged backlog/runtime_agg."""
    tracker = FakeTracker()
    ref1 = tracker.create_issue(
        IssueDraft(title="Existing proposals", body="x", labels=[sc.PROPOSAL, sc.FROM_TRIAGE])
    ).number
    ref2 = tracker.create_issue(IssueDraft(title="ready Items", body="x", labels=[sc.READY])).number
    # Not used as a reference
    tracker.create_issue(IssueDraft(title="raw report", body="x", labels=[sc.REPORT]))
    d = _divergent(tmp_path, tracker, _submit([]))
    d.propose_once()
    assert len(d.seen_trend) == 1  # The user experience index is fed in
    # references contain only proposal/ready
    assert {i.number for i in d.seen_reference} == {ref1, ref2}


def test_divergent_dedupe_reference_is_compact() -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="Exploration scope runs out of control under precise instructions",
            body="### Root cause\n\nagents/main.md Exploration scope is not constrained for precise tasks",
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE],
        )
    )
    rendered = Divergent._format_issues(tracker.list_open_issues())
    assert "Exploration scope runs out of control under precise instructions" in rendered
    assert "agents/main.md Exploration scope is not constrained for precise tasks" not in rendered


def test_divergent_caps_at_three(tmp_path: Path) -> None:
    tracker = FakeTracker()
    many = [{"title": f"Candidate{i}", **_pm_artifact()} for i in range(5)]
    out = _divergent(tmp_path, tracker, _submit(many)).propose_once()
    assert out.count == 3  # hard cap per round


def test_divergent_incomplete_fields_skipped(tmp_path: Path) -> None:
    tracker = FakeTracker()
    out = _divergent(
        tmp_path,
        tracker,
        _submit([{"title": "Half finished product", "user_goal": "Only filled this in"}]),
    ).propose_once()
    assert out.count == 0
    assert tracker.list_open_issues() == []


def test_divergent_no_submit_is_noop(tmp_path: Path) -> None:
    tracker = FakeTracker()
    out = _divergent(tmp_path, tracker, "Prose，Did not tune it submit").propose_once()
    assert out.count == 0


def test_recovery_reuses_output_and_reconciles_created_proposal(tmp_path: Path) -> None:
    class CrashAfterCreateTracker(FakeTracker):
        crashed = False

        def create_issue_once(self, draft, *, operation_key):
            ref = super().create_issue_once(draft, operation_key=operation_key)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after issue create")
            return ref

    tracker = CrashAfterCreateTracker()
    recovery = _recovery(tmp_path)
    divergent = _divergent(
        tmp_path,
        tracker,
        _submit([{"title": "Productize status handoff", **_pm_artifact()}]),
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="divergent-worker-0"):
        with pytest.raises(RuntimeError, match="injected"):
            divergent.propose_once()
    with bind_usage_context(round_no=1, operation="divergent-worker-0"):
        outcome = divergent.propose_once()
    assert divergent.agent_calls == 1
    assert outcome.count == 1
    assert len(tracker.list_open_issues()) == 1


@pytest.mark.parametrize("prerequisite", ["feedback_imported", "objective_grading"])
def test_feedback_uses_its_actual_stage_dependency(tmp_path, prerequisite):
    """PM binds the actual prerequisite instead of inventing user completion."""
    tracker = FakeTracker()
    recovery = RecoveryStore.initialize(
        root=tmp_path / "bootstrap",
        identity=RecoveryIdentity("exp", "child", "config", "controller", "bootstrap"),
    )
    recovery.freeze_round(round_no=1, user_sha="seed", plan=[])
    key = operation_key("feedback-imported")
    recovery.begin_unit(round_no=1, stage=prerequisite, key=key, input_value={})
    recovery.complete_unit(round_no=1, stage=prerequisite, key=key)
    recovery.complete_stage(round_no=1, stage=prerequisite)
    divergent = _divergent(tmp_path, tracker, _submit([]), recovery=recovery)
    divergent.bind_feedback_dependency(prerequisite)
    with bind_usage_context(round_no=1, operation="continuation-bootstrap-divergent"):
        result = divergent.propose_once()
    assert result.proposal_numbers == []
    state = recovery.round_state(round_no=1)
    assert state["stages"]["divergent"]["dependencies"] == [prerequisite]
    assert "users" not in state["stages"]
    divergent.bind_feedback_dependency("users")
    assert divergent._feedback_dependency == "users"
