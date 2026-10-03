"""Grouping is read-only; existing Synthesizers own design and publication."""

import json
import sys
import threading
from types import SimpleNamespace

import pytest

from auto_designer.demand.grouped_synthesizer import (
    GroupedSynthesizer,
    group_synthesizer_stage,
    validate_groups,
)
from auto_designer.demand.issue_schema import FROM_DIVERGENT, PROPOSAL, REPORT
from auto_designer.demand.synthesizer import SynthesisOutcome, Synthesizer
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.session_store import SessionStore


def tracker_with(count):
    tracker = FakeTracker()
    for index in range(count):
        tracker.create_issue(
            IssueDraft(title=f"Proposal {index}", body="summary", labels=[PROPOSAL])
        )
    return tracker


def response(groups):
    return {"raw_output": json.dumps({"groups": groups}), "finish_reason": "stop"}


def workers(tmp_path, tracker, cls=Synthesizer):
    return [
        cls(
            tracker,
            SessionStore(tmp_path / "sessions"),
            str(tmp_path),
            str(tmp_path),
            round_provider=lambda: 4,
        )
        for _ in range(2)
    ]


def grouped(tmp_path, tracker, classify, cls=Synthesizer):
    return GroupedSynthesizer(
        workers(tmp_path, tracker, cls), artifact_root=tmp_path / "grouping", classify=classify
    )


def receipt(tmp_path):
    return json.loads(next((tmp_path / "grouping").glob("*/grouping.json")).read_text())


def recovery_for_synthesizer(tmp_path):
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    triage = operation_key("triage", "complete")
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


@pytest.mark.parametrize(
    "groups",
    [
        [[1, 1], [2]],
        [[1]],
        [[1, 2, 3]],
        [[True, 2]],
        [["1", 2]],
        [[], [1, 2]],
        {"x": [1, 2]},
        None,
    ],
)
def test_invalid_groups_cannot_change_input_ownership(groups):
    with pytest.raises((ValueError, TypeError)):
        validate_groups(json.dumps({"groups": groups}), [1, 2])


def test_two_workers_keep_group_together_and_restore_trackers(tmp_path):
    tracker = tracker_with(12)
    barrier = threading.Barrier(2)
    calls = []
    classified = []

    class Worker(Synthesizer):
        def propose_once(self):
            ids = [item.number for item in self._tracker.list_open_issues()]
            if ids[0] in (1, 11):
                barrier.wait(timeout=5)
            calls.append((id(self), threading.get_ident(), ids, current_usage_context()))
            return SynthesisOutcome(proposal_numbers=[100 + min(ids)])

    def classify(cards):
        classified.append(cards)
        return response([list(range(1, 11)), [11, 12]])

    stage = grouped(tmp_path, tracker, classify, Worker)
    result = stage.propose_once()
    assert len(classified) == 1 and result.proposal_numbers == [101, 107, 111]
    assert len({thread for _, thread, _, _ in calls}) == 2
    large_group = [call for call in calls if call[2][0] <= 10]
    assert [call[2] for call in large_group] == [list(range(1, 7)), list(range(7, 11))]
    assert len({call[0] for call in large_group}) == 1
    assert all(
        context.round_no == 4 and context.agent_id in {"synthesizer-0", "synthesizer-1"}
        for _, _, _, context in calls
    )
    assert sorted(number for _, _, ids, _ in calls for number in ids) == list(range(1, 13))
    assert all(worker._tracker is tracker for worker in stage.synthesizers)


@pytest.mark.parametrize("failure", ["transport", "duplicate", "truncated", "malformed"])
def test_classifier_failure_restores_serial_id_order_without_retry(tmp_path, failure):
    calls, attempts = [], []

    class Worker(Synthesizer):
        def propose_once(self):
            calls.append(
                (threading.get_ident(), [i.number for i in self._tracker.list_open_issues()])
            )
            return SynthesisOutcome()

    def classify(cards):
        attempts.append(cards)
        if failure == "transport":
            raise TimeoutError("unavailable")
        if failure == "duplicate":
            return response([[1, 1]])
        if failure == "truncated":
            return {**response([list(range(1, 15))]), "finish_reason": "length"}
        return {"raw_output": "not JSON", "finish_reason": "stop"}

    grouped(tmp_path, tracker_with(14), classify, Worker).propose_once()
    assert len(attempts) == 1
    assert [ids for _, ids in calls] == [list(range(1, 7)), list(range(7, 13)), [13, 14]]
    assert len({thread for thread, _ in calls}) == 1
    assert receipt(tmp_path)["status"] == "fallback"


def test_singletons_pm_and_reports_remain_unchanged(tmp_path):
    tracker = tracker_with(2)
    tracker.create_issue(IssueDraft(title="PM", body="pm", labels=[PROPOSAL, FROM_DIVERGENT]))
    tracker.create_issue(IssueDraft(title="Report", body="raw", labels=[REPORT]))
    before = tracker.list_open_issues()

    def classify(cards):
        assert [card["id"] for card in cards] == [1, 2]
        assert set(cards[0]) == {"id", "title", "summary"}
        return response([[1], [2]])

    class NoSynthesis(Synthesizer):
        def propose_once(self):
            pytest.fail("singleton must remain for Owner")

    assert grouped(tmp_path, tracker, classify, NoSynthesis).propose_once().count == 0
    assert tracker.list_open_issues() == before


@pytest.mark.parametrize("count", [0, 1])
def test_no_classification_call_when_synthesis_is_impossible(tmp_path, count):
    def never(cards):
        pytest.fail("not enough input for synthesis")

    stage = grouped(tmp_path, tracker_with(count), never)
    assert stage.propose_once().count == 0 and receipt(tmp_path)["status"] == "skipped"


def test_grouping_only_reads_the_active_round(tmp_path):
    tracker = FakeTracker()
    for number, round_name in (
        ("current-a", "round-4"),
        ("old", "round-3"),
        ("current-b", "round-4"),
    ):
        tracker.create_issue(
            IssueDraft(title=number, body="summary", labels=[PROPOSAL, round_name])
        )
    calls = []

    class Worker(Synthesizer):
        def propose_once(self):
            ids = [item.number for item in self._tracker.list_open_issues()]
            calls.append(ids)
            return SynthesisOutcome()

    def classify(cards):
        assert [card["id"] for card in cards] == [1, 3]
        return response([[1, 3]])

    grouped(tmp_path, tracker, classify, Worker).propose_once()
    assert calls == [[1, 3]]


def test_grouping_includes_pending_diagnostic_gaps_across_rounds(tmp_path):
    tracker = FakeTracker()
    for title, labels in (
        ("current", [PROPOSAL, "round-4"]),
        ("old ordinary", [PROPOSAL, "round-3"]),
        ("unlabelled gap", [PROPOSAL, "observation-gap"]),
        ("old gap", [PROPOSAL, "observation-gap", "round-3"]),
        ("future gap", [PROPOSAL, "observation-gap", "round-5"]),
        ("PM diagnostic gap", [PROPOSAL, "observation-gap", FROM_DIVERGENT]),
        ("PM product", [PROPOSAL, FROM_DIVERGENT]),
    ):
        tracker.create_issue(IssueDraft(title=title, body="summary", labels=labels))

    class Worker(Synthesizer):
        def propose_once(self):
            return SynthesisOutcome()

    def classify(cards):
        assert [card["id"] for card in cards] == [1, 3, 4, 6]
        return response([[1, 3, 4, 6]])

    grouped(tmp_path, tracker, classify, Worker).propose_once()
    assert [card["id"] for card in receipt(tmp_path)["input"]] == [1, 3, 4, 6]


def test_delivery_gap_ingestion_precedes_synthesizer_snapshot(tmp_path, monkeypatch):
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="current", body="summary", labels=[PROPOSAL, "round-4"]))
    calls = []

    def ingest(*, store, tracker):
        calls.append(1)
        tracker.create_issue(
            IssueDraft(title="delivery gap", body="summary", labels=[PROPOSAL, "observation-gap"])
        )
        return []

    monkeypatch.setattr("auto_designer.observations.delivery_gaps.ingest_delivery_gaps", ingest)

    class Worker(Synthesizer):
        def propose_once(self):
            return SynthesisOutcome()

    stage = grouped(tmp_path, tracker, lambda cards: response([[1, 2]]), Worker)
    stage.propose_once()
    assert calls == [1]
    assert [card["id"] for card in receipt(tmp_path)["input"]] == [1, 2]


def test_single_synthesizer_includes_triage_and_delivery_gaps(tmp_path, monkeypatch):
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="current", body="summary", labels=[PROPOSAL, "round-4"]))
    tracker.create_issue(
        IssueDraft(title="triage gap", body="summary", labels=[PROPOSAL, "observation-gap"])
    )
    tracker.create_issue(
        IssueDraft(title="old ordinary", body="summary", labels=[PROPOSAL, "round-3"])
    )
    seen = []

    def ingest(*, store, tracker):
        tracker.create_issue(
            IssueDraft(title="delivery gap", body="summary", labels=[PROPOSAL, "observation-gap"])
        )
        return []

    def run_agent(self, *, ready, proposals, trend, runtime):
        seen.extend(item.number for item in proposals)
        return '{"proposals": []}'

    monkeypatch.setattr("auto_designer.observations.delivery_gaps.ingest_delivery_gaps", ingest)
    monkeypatch.setattr(Synthesizer, "_run_agent", run_agent)
    synthesizer = Synthesizer(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path),
        str(tmp_path),
        round_provider=lambda: 4,
    )
    synthesizer.propose_once()
    assert seen == [1, 2, 4]


def test_actual_synthesizer_rejects_cross_group_sources(tmp_path, monkeypatch):
    tracker = tracker_with(4)
    barrier = threading.Barrier(2)

    def generate(self, *, proposals, **kwargs):
        ids = [item.number for item in proposals]
        barrier.wait(timeout=5)
        artifact = dict(
            title="Cross-scope attempt",
            source_proposals=[ids[0], 4 if ids[0] == 1 else 1],
            solution_level="structural_mechanism",
            covers=[1, 2, 3, 4],
        )
        return json.dumps({"proposals": [artifact]})

    monkeypatch.setattr(Synthesizer, "_run_agent", generate)
    result = grouped(tmp_path, tracker, lambda cards: response([[1, 2], [3, 4]])).propose_once()
    assert result.count == 0 and len(result.rejected_proposals) == 2
    assert all(item["reasons"] == ["foreign-source"] for item in result.rejected_proposals)
    assert [item.number for item in tracker.list_open_issues()] == [1, 2, 3, 4]


def test_actual_synthesizer_only_closes_owned_sources(tmp_path, monkeypatch):
    tracker = tracker_with(3)

    def generate(self, **kwargs):
        return json.dumps(
            {
                "proposals": [
                    dict(
                        title="Shared mechanism",
                        source_proposals=[1, 2],
                        solution_level="structural_mechanism",
                        covers=[1, 2, 3],
                        relationship="shared",
                        common_tension="same",
                        structural_direction="mechanism",
                        expected_leverage="both sources",
                    )
                ]
            }
        )

    monkeypatch.setattr(Synthesizer, "_run_agent", generate)
    result = grouped(tmp_path, tracker, lambda cards: response([[1, 2], [3]])).propose_once()
    assert result.proposal_numbers == [4] and result.merged_numbers == [1, 2]
    assert tracker.issue(3)["state"] == "open"


def test_batch_failure_restores_scope_and_other_groups_continue(tmp_path):
    calls = []
    tracker = tracker_with(4)

    class Worker(Synthesizer):
        def propose_once(self):
            ids = [item.number for item in self._tracker.list_open_issues()]
            calls.append(ids)
            if 1 in ids:
                raise RuntimeError("agent failed")
            return SynthesisOutcome(proposal_numbers=[100])

    stage = grouped(tmp_path, tracker, lambda cards: response([[1, 2], [3, 4]]), Worker)
    result = stage.propose_once()
    assert sorted(calls) == [[1, 2], [3, 4]] and result.proposal_numbers == [100]
    assert all(worker._tracker is tracker for worker in stage.synthesizers)
    records = [
        json.loads(path.read_text()) for path in (tmp_path / "grouping").glob("*/group-*.json")
    ]
    assert sorted(record["status"] for record in records) == ["completed", "failed"]


def test_unwritable_telemetry_does_not_discard_work(tmp_path):
    (tmp_path / "grouping").write_text("not a directory")
    calls = []

    class Worker(Synthesizer):
        def propose_once(self):
            calls.append(True)
            return SynthesisOutcome(proposal_numbers=[10])

    result = grouped(
        tmp_path, tracker_with(2), lambda cards: response([[1, 2]]), Worker
    ).propose_once()
    assert calls == [True] and result.proposal_numbers == [10]


def test_recovery_reuses_grouping_receipt_after_batch_failure(tmp_path):
    tracker = tracker_with(2)
    classify_calls: list[list[dict]] = []
    worker_calls = 0

    class Worker(Synthesizer):
        def propose_once(self):
            nonlocal worker_calls
            worker_calls += 1
            if worker_calls == 1:
                raise RuntimeError("injected batch failure")
            return SynthesisOutcome()

    worker = Worker(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path),
        str(tmp_path),
        round_provider=lambda: 1,
    )

    def classify(cards):
        classify_calls.append(cards)
        return response([[1, 2]])

    stage = GroupedSynthesizer([worker], artifact_root=tmp_path / "grouping", classify=classify)
    stage.bind_recovery(recovery_for_synthesizer(tmp_path))
    with bind_usage_context(round_no=1, operation="synthesizer-stage"):
        with pytest.raises(RecoveryConflictError, match="batches remain incomplete"):
            stage.propose_once()
    with bind_usage_context(round_no=1, operation="synthesizer-stage"):
        stage.propose_once()
    assert len(classify_calls) == 1
    assert worker_calls == 2
    assert len(list((tmp_path / "grouping").glob("*/grouping.json"))) == 1


@pytest.mark.parametrize("logical_round", [None, 1])
def test_grouped_recovery_preserves_logical_filter_and_replays_saved_design(
    tmp_path, logical_round
):
    tracker = tracker_with(2)
    source_round = "round-5" if logical_round is None else "round-1"
    for number in (1, 2):
        tracker.update_issue(
            number, title=f"Proposal {number}", body="summary", labels=[PROPOSAL, source_round]
        )
    calls = {"grouping": 0, "model": 0, "failed_merge": 0}
    contexts = []

    class Worker(Synthesizer):
        def _run_agent(self, **kwargs):
            calls["model"] += 1
            contexts.append((current_usage_context().round_no, self._round_provider()))
            assert [item.number for item in kwargs["proposals"]] == [1, 2]
            return json.dumps(
                {
                    "proposals": [
                        dict(
                            title="Shared mechanism",
                            source_proposals=[1, 2],
                            solution_level="structural_mechanism",
                            covers=[1, 2],
                            relationship="shared",
                            common_tension="same",
                            structural_direction="mechanism",
                            expected_leverage="both sources",
                        )
                    ]
                }
            )

        def _merge_covered(self, source, **kwargs):
            if source.number == 1 and calls["failed_merge"] == 0:
                calls["failed_merge"] += 1
                raise RuntimeError("merge response unavailable after saved design")
            return super()._merge_covered(source, **kwargs)

    def classify(cards):
        calls["grouping"] += 1
        assert current_usage_context().round_no == 1
        assert [card["id"] for card in cards] == [1, 2]
        return response([[1, 2]])

    worker = Worker(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path),
        str(tmp_path),
        round_provider=lambda: logical_round,
    )
    stage = GroupedSynthesizer([worker], artifact_root=tmp_path / "grouping", classify=classify)
    recovery = recovery_for_synthesizer(tmp_path)
    stage.bind_recovery(recovery)
    namespace = "continuation-bootstrap" if logical_round is None else "ordinary"
    with bind_usage_context(round_no=1, operation=operation_key(namespace, "synthesizer")):
        with pytest.raises(RecoveryConflictError, match="batches remain incomplete"):
            stage.propose_once()
        units = recovery.round_state(round_no=1)["stages"]["synthesizer"]["units"].values()
        assert any(item.get("status") == "failed" and item.get("output_digest") for item in units)
        result = stage.propose_once()
    assert calls == {"grouping": 1, "model": 1, "failed_merge": 1}
    assert contexts == [(1, logical_round)]
    assert result.proposal_numbers == [3] and sorted(result.merged_numbers) == [1, 2]
    assert tracker.issue(1)["state"] == tracker.issue(2)["state"] == "closed"
    assert len(tracker.list_open_issues()) == 1
    round_labels = {label for label in tracker.issue(3)["labels"] if label.startswith("round-")}
    assert round_labels == (set() if logical_round is None else {"round-1"})
    assert set(recovery.snapshot()["rounds"]) == {"1"}


def test_entry_point_switch_preserves_workers_and_disabled_roster(tmp_path, monkeypatch):
    existing = workers(tmp_path, tracker_with(0))
    monkeypatch.delenv("SYNTHESIZER_GROUPING", raising=False)
    assert group_synthesizer_stage(existing, artifact_root=tmp_path) is existing
    monkeypatch.setenv("SYNTHESIZER_GROUPING", "1")
    assert group_synthesizer_stage([], artifact_root=tmp_path) == []
    result = group_synthesizer_stage(existing, artifact_root=tmp_path)
    assert len(result) == 1 and result[0].synthesizers == existing


def test_orchestrator_waits_for_all_16_triagers_then_both_synthesizers(tmp_path, monkeypatch):
    tracker = tracker_with(0)
    triage_barrier, design_barrier = threading.Barrier(16), threading.Barrier(2)
    lock = threading.Lock()
    triaged, designed, admissions, classified = [], [], [], []

    class Triager:
        def triage_once(self, *, shard):
            triage_barrier.wait(timeout=5)
            with lock:
                for _ in range(2):
                    tracker.create_issue(
                        IssueDraft(title=str(shard), body="summary", labels=[PROPOSAL])
                    )
                triaged.append(shard)

    class Worker(Synthesizer):
        def propose_once(self):
            ids = [item.number for item in self._tracker.list_open_issues()]
            if ids[0] in (1, 17):
                design_barrier.wait(timeout=5)
            designed.append(ids)
            return SynthesisOutcome()

    def classify(cards):
        assert len(triaged) == 16 and len(cards) == 32
        classified.append(cards)
        return response([list(range(1, 17)), list(range(17, 33))])

    def admit():
        assert len(designed) == 6
        admissions.append(True)
        return SimpleNamespace(admitted=[])

    stage = grouped(tmp_path, tracker, classify, Worker)
    orch = Orchestrator(
        launcher=None,
        harness_repo=str(tmp_path),
        fixed_set=[],
        run_session_fn=lambda *a: None,
        initial_ref="main",
        triagers=[Triager() for _ in range(16)],
        synthesizers=[stage],
        owner=SimpleNamespace(admit_once=admit),
    )
    monkeypatch.setattr(orch, "_resolve_head", lambda **kw: "head")
    assert orch.run_round("main") == "head"
    assert len(classified) == 1 and admissions == [True]
    assert sorted(number for batch in designed for number in batch) == list(range(1, 33))


def test_grouping_records_usage_and_never_enables_sdk_retries(tmp_path, monkeypatch):

    from auto_designer.demand.grouped_synthesizer import classify_once
    from auto_designer.usage import UsageStore, bind_usage_context

    usage_path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("AUTO_DESIGNER_USAGE_PATH", str(usage_path))
    for suffix, value in {
        "MODEL": "test",
        "API_KEY": "secret",
        "BASE_URL": "http://example.invalid",
    }.items():
        monkeypatch.setenv("DEMAND_LLM_" + suffix, value)

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0 and kwargs["timeout"] == 300
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            assert kwargs["max_tokens"] == 16384 and "tools" not in kwargs
            return SimpleNamespace(
                id="req",
                model="test",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"groups":[[1,2]]}'), finish_reason="stop"
                    )
                ],
                usage=SimpleNamespace(
                    model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 20}
                ),
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    with bind_usage_context(round_no=4, role="synthesizer", agent_id="synthesizer-grouping"):
        result = classify_once([{"id": 1}, {"id": 2}])
    assert validate_groups(result["raw_output"], [1, 2]) == [[1, 2]]
    event = UsageStore(usage_path).events()[0]
    assert (event["round_no"], event["operation"], event["output_tokens"]) == (
        4,
        "proposal_grouping",
        20,
    )
