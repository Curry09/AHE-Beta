# Spec-0029/T4: architect generator unit test (stub nexau agent + FakeTracker + temporary SessionStore).
"""Verify architect driver: output lands on proposal plane + from-architect (not claimable);
covers is Architect's absorption decision (filtered to open report/proposal); input = ready + proposal index pending admission + user experience + runtime;
skip missing fields; submit not called is no-op; drift-guard (submit_rfcs yaml == rfc_input_schema)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.architect import (
    Architect,
    SynthesisOutcome,
    _parse_covers,
)
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


class _StubArchitect(Architect):
    """Override _run_agent: do not run real nexau, replay fixed submit returns, and record the signals fed in."""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_ready: list = []
        self.seen_proposals: list = []
        self.seen_trend: list = []
        self.seen_runtime: str = ""
        self.agent_calls = 0

    def _run_agent(self, *, ready: list, proposals: list, trend: list, runtime: str) -> str:
        self.agent_calls += 1
        self.seen_ready = ready
        self.seen_proposals = proposals
        self.seen_trend = trend
        self.seen_runtime = runtime
        return self._canned


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


@pytest.mark.parametrize("payload", [json.dumps({"proposals": []}), None])
def test_valid_submit_does_not_trigger_recovery(tmp_path, monkeypatch, payload) -> None:
    architect = _architect(tmp_path, FakeTracker(), payload or _rfc_canned())
    calls = []
    original = architect._run_agent

    def invoke(**kwargs):
        calls.append(architect._force_submit_prompt)
        return original(**kwargs)

    monkeypatch.setattr(architect, "_run_agent", invoke)
    architect.propose_once()
    assert calls == [False]


@pytest.mark.parametrize("recovered", [True, False])
def test_missing_submit_has_one_recovery_with_same_inputs(tmp_path, monkeypatch, recovered) -> None:
    architect = _architect(tmp_path, FakeTracker(), _rfc_canned())
    replies = iter(
        ["Analysis not yet submitted", _rfc_canned() if recovered else "Still not submitted"]
    )
    calls = []

    def invoke(**kwargs):
        calls.append((architect._force_submit_prompt, kwargs))
        return next(replies)

    monkeypatch.setattr(architect, "_run_agent", invoke)
    outcome = architect.propose_once()
    assert outcome.count == int(recovered)
    assert [flag for flag, _ in calls] == [False, True]
    assert calls[0][1] == calls[1][1]
    assert architect._force_submit_prompt is False


def test_recovery_error_restores_normal_prompt(tmp_path, monkeypatch) -> None:
    architect = _architect(tmp_path, FakeTracker(), _rfc_canned())

    def invoke(**kwargs):
        if architect._force_submit_prompt:
            raise RuntimeError("backend unavailable")
        return "Submission tool not called"

    monkeypatch.setattr(architect, "_run_agent", invoke)
    with pytest.raises(RuntimeError, match="backend unavailable"):
        architect.propose_once()
    assert architect._force_submit_prompt is False


def _seed_session(store: SessionStore, *, score: int, reason: str = "r") -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason=reason),
        )
    )


def _architect(
    tmp_path: Path,
    tracker: FakeTracker,
    canned: str,
    *,
    round_provider=None,
    recovery=None,
) -> _StubArchitect:
    # A synthesis fixture needs an actual cross-proposal set.
    if '"proposals": []' not in canned and "Prose" not in canned and canned:
        while (
            len(
                [
                    i
                    for i in tracker.list_open_issues()
                    if sc.plane(i.labels) in (sc.PROPOSAL, sc.READY)
                ]
            )
            < 2
        ):
            _proposal(tracker, "Supporting source")
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store, score=2, reason="Waiting too long")
    _seed_session(store, score=1, reason="Two timeouts with no results")
    return _StubArchitect(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        canned=canned,
        round_provider=round_provider,
        recovery=recovery,
    )


def _architect_recovery(tmp_path: Path) -> RecoveryStore:
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    triage = operation_key("triage-complete")
    store.begin_unit(
        round_no=1,
        stage="triage",
        key=triage,
        input_value={},
        expected_postconditions={"completed": True},
    )
    store.complete_unit(round_no=1, stage="triage", key=triage)
    store.complete_stage(round_no=1, stage="triage")
    return store


def _synthesis_artifact() -> dict:
    return {
        "source_proposals": [1, 2],
        "relationship": "The two proposals reflect stages of the same experience tension",
        "common_tension": "Long tasks lack predictable feedback boundaries",
        "structural_direction": "Unify progress reporting and intermediate delivery mechanisms",
        "expected_leverage": "Reduce both uncertainty while waiting and rework after failure",
        "solution_level": "structural_mechanism",
        "abstraction_rationale": "Describe only the mechanism shared across proposals",
    }


def _submit(proposals: list) -> str:
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


def _rfc_canned(
    covers: object = None, *, title: str = "Structure：Budget aware", fields: dict | None = None
) -> str:
    item: dict = {"title": title, **(fields if fields is not None else _synthesis_artifact())}
    if covers is not None:
        item["covers"] = covers
    return _submit([item])


def _proposal(tracker: FakeTracker, title: str) -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE])
    ).number


def test_submit_rfcs_yaml_matches_contract() -> None:
    """drift-guard: input_schema of submit_rfcs.tool.yaml is deeply equal to rfc_input_schema()."""
    import yaml

    from ahe_beta.demand.agent_contract import synthesis_input_schema

    yaml_path = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "architect"
        / "tools"
        / "submit_rfcs.tool.yaml"
    )
    tool_def = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == synthesis_input_schema()


def test_structural_proposal_lands_unclaimable(tmp_path) -> None:
    tracker = FakeTracker()
    _proposal(tracker, "timeout 1")
    architect = _architect(tmp_path, tracker, _rfc_canned())

    outcome = architect.propose_once()

    assert isinstance(outcome, SynthesisOutcome) and outcome.count == 1
    rfc = tracker.issue(outcome.proposal_numbers[0])
    assert sc.PROPOSAL in rfc["labels"] and sc.FROM_ARCHITECT in rfc["labels"]
    assert sc.plane(rfc["labels"]) == sc.PROPOSAL  # Not claimable; awaiting Owner admission
    assert not sc.is_ready(labels=rfc["labels"], state="open")
    assert "## Structural relationship" in rfc["body"]
    assert "## Structural direction" in rfc["body"]


def test_structural_proposal_carries_live_round_label(tmp_path) -> None:
    tracker = FakeTracker()
    outcome = _architect(tmp_path, tracker, _rfc_canned(), round_provider=lambda: 4).propose_once()

    assert "round-4" in tracker.issue(outcome.proposal_numbers[0])["labels"]


def test_structural_proposal_does_not_guess_invalid_round(tmp_path) -> None:
    for value in (None, 0, -1, True):
        tracker = FakeTracker()
        outcome = _architect(
            tmp_path, tracker, _rfc_canned(), round_provider=lambda value=value: value
        ).propose_once()
        labels = tracker.issue(outcome.proposal_numbers[0])["labels"]
        assert not any(label.startswith("round-") for label in labels)


def test_inputs_are_ready_plus_proposal_index(tmp_path) -> None:
    """Input = ready work queue + pending admission proposal index (report/terminal states not fed)."""
    tracker = FakeTracker()
    p = _proposal(tracker, "Proposal newly promoted this round")
    r = tracker.create_issue(
        IssueDraft(title="ready Items", body="x", labels=["bug", sc.READY])
    ).number
    tracker.create_issue(IssueDraft(title="raw report", body="x", labels=[sc.REPORT]))
    architect = _architect(tmp_path, tracker, _submit([]))
    architect.propose_once()
    assert [i.number for i in architect.seen_ready] == [r]
    assert [i.number for i in architect.seen_proposals] == [p]
    assert architect.seen_trend
    # 0059: No longer inject runtime aggregation by default with coupled legacy artifact fields.
    assert architect.seen_runtime == ""


def test_inputs_are_limited_to_the_active_round(tmp_path) -> None:
    tracker = FakeTracker()
    current = tracker.create_issue(
        IssueDraft(title="current", body="x", labels=[sc.PROPOSAL, sc.FROM_TRIAGE, "round-4"])
    ).number
    tracker.create_issue(IssueDraft(title="old", body="x", labels=[sc.READY, "round-3"]))
    architect = _architect(tmp_path, tracker, _submit([]), round_provider=lambda: 4)

    architect.propose_once()

    assert [item.number for item in architect.seen_ready] == []
    assert [item.number for item in architect.seen_proposals] == [current]


def test_covers_line_written_and_sources_are_merged(tmp_path) -> None:
    """covers resides in body, merged and closed by Architect driver when absorbed source is absorbed."""
    tracker = FakeTracker()
    t1 = _proposal(tracker, "Symptom 1")
    t2 = _proposal(tracker, "Symptom 2")
    outcome = _architect(tmp_path, tracker, _rfc_canned([t1, t2])).propose_once()

    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{t1} #{t2}" in body  # Machine-readable line
    assert outcome.merged_numbers == [t1, t2]
    assert outcome.failed_merges == {}
    for n in (t1, t2):
        snap = tracker.issue(n)
        assert sc.MERGED in snap["labels"]
        assert snap["state"] == "closed" and sc.plane(snap["labels"]) is None
        assert f"merged-into: #{outcome.proposal_numbers[0]}" in "\n".join(snap["comments"])


def test_sources_omitted_from_covers_stay_open(tmp_path) -> None:
    tracker = FakeTracker()
    covered = _proposal(tracker, "Absorbed")
    independent = _proposal(tracker, "Independent delivery")
    outcome = _architect(tmp_path, tracker, _rfc_canned([covered])).propose_once()

    assert outcome.merged_numbers == [covered]
    assert tracker.issue(covered)["state"] == "closed"
    assert tracker.issue(independent)["state"] == "open"
    assert sc.plane(tracker.issue(independent)["labels"]) == sc.PROPOSAL


def test_cover_merge_failure_isolated_and_reported(tmp_path) -> None:
    class BrokenTransitionTracker(FakeTracker):
        def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
            raise RuntimeError(f"cannot transition #{number}")

    tracker = BrokenTransitionTracker()
    source = _proposal(tracker, "Source pending absorption")
    outcome = _architect(tmp_path, tracker, _rfc_canned([source])).propose_once()

    target = outcome.proposal_numbers[0]
    assert outcome.merged_numbers == []
    assert source in outcome.failed_merges
    assert tracker.issue(target)["state"] == "open"
    assert tracker.issue(source)["state"] == "open"


def test_covers_filtered_to_open_report_or_proposal(tmp_path) -> None:
    """covers points to ready item / non-existent number → silently removed (merge is meaningful only for report/proposal)."""
    tracker = FakeTracker()
    ok = _proposal(tracker, "Proposals that can be covered")
    ready_n = tracker.create_issue(IssueDraft(title="ready", body="x", labels=[sc.READY])).number
    outcome = _architect(tmp_path, tracker, _rfc_canned([ok, ready_n, 999])).propose_once()
    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{ok}" in body
    assert f"#{ready_n}" not in body.split("covers:")[1]


def test_covers_absent_no_line(tmp_path) -> None:
    tracker = FakeTracker()
    _proposal(tracker, "t")
    outcome = _architect(tmp_path, tracker, _rfc_canned(None)).propose_once()
    assert "covers:" not in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_synthesis_renders_explicit_sources(tmp_path) -> None:
    tracker = FakeTracker()
    fields = _synthesis_artifact()
    outcome = _architect(tmp_path, tracker, _rfc_canned(fields=fields)).propose_once()
    assert outcome.count == 1
    assert "## Source proposals" in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_incomplete_fields_skipped(tmp_path) -> None:
    tracker = FakeTracker()
    canned = _submit([{"title": "Half finished product", "source_proposals": [1]}])
    outcome = _architect(tmp_path, tracker, canned).propose_once()
    assert outcome.count == 0


def test_empty_or_no_submit_yields_no_proposal(tmp_path) -> None:
    tracker = FakeTracker()
    for canned in (_submit([]), "Prose not tuned submit", ""):
        outcome = _architect(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0


def test_synthesis_requires_cross_proposal_sources(tmp_path) -> None:
    tracker = FakeTracker()
    outcome = _architect(
        tmp_path,
        tracker,
        _submit([{"title": "Single source", **{**_synthesis_artifact(), "source_proposals": [1]}}]),
    ).propose_once()
    assert outcome.count == 0


def test_parse_covers_field_shapes() -> None:
    """covers permissive input, strict output: deduplicate, remove bool/negative/string."""
    assert _parse_covers([5, 5, 6, True, -1, 0, "8"]) == (5, 6)
    assert _parse_covers("nope") == ()


def test_recovery_replays_architect_output_and_reconciles_proposal_create(tmp_path) -> None:
    class CrashAfterCreateTracker(FakeTracker):
        crashed = False

        def create_issue_once(self, draft, *, operation_key):
            ref = super().create_issue_once(draft, operation_key=operation_key)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after proposal create")
            return ref

    tracker = CrashAfterCreateTracker()
    recovery = _architect_recovery(tmp_path)
    architect = _architect(
        tmp_path,
        tracker,
        _rfc_canned(),
        round_provider=lambda: 1,
        recovery=recovery,
    )
    with bind_usage_context(round_no=1, operation="architect-worker-0"):
        with pytest.raises(RuntimeError, match="injected"):
            architect.propose_once()
    with bind_usage_context(round_no=1, operation="architect-worker-0"):
        outcome = architect.propose_once()
    assert architect.agent_calls == 1
    assert outcome.count == 1
    assert (
        len([issue for issue in tracker.list_open_issues() if sc.FROM_ARCHITECT in issue.labels])
        == 1
    )
