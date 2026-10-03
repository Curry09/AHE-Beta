"""Spec-0079/T3: durable feedback ordering, scope and delivery failure boundaries."""

import json
from types import SimpleNamespace

import pytest

from auto_designer.loop.feedback_pipeline import FeedbackPipeline
from auto_designer.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from auto_designer.loop.round_gate import RoundDeliveryBlocked
from auto_designer.usage import current_usage_context


def _store(tmp_path, name="ordinary"):
    store = RecoveryStore.initialize(
        root=tmp_path / name,
        identity=RecoveryIdentity("exp", "child", "config", "controller", name),
    )
    store.freeze_round(round_no=1, user_sha="seed", plan=[])
    return store


def _pipeline(store, events, **kwargs):
    def assert_descendant(*, ancestor, descendant):
        events.append(("descendant", ancestor, descendant))

    return FeedbackPipeline(
        recovery=store,
        resolve_head=lambda: "delivered",
        assert_descendant=assert_descendant,
        integrity_guard=lambda: events.append("guard"),
        **kwargs,
    )


def _complete_prerequisite(pipeline, prerequisite):
    pipeline.mark_stage(round_no=1, stage=prerequisite, input_value={"complete": True})


@pytest.mark.parametrize("prerequisite", ["users", "feedback_imported"])
def test_feedback_requires_real_prerequisite_and_preserves_seal_contract(tmp_path, prerequisite):
    store = _store(tmp_path)
    events = []
    namespace = "continuation-bootstrap" if prerequisite == "feedback_imported" else None
    pipeline = _pipeline(store, events, prerequisite=prerequisite, operation_namespace=namespace)
    with pytest.raises(RecoveryConflictError, match="dependencies"):
        pipeline.run(round_no=1, user_sha="seed")
    assert events == []
    _complete_prerequisite(pipeline, prerequisite)
    assert pipeline.run(round_no=1, user_sha="seed") == "delivered"
    assert events == ["guard", ("descendant", "seed", "delivered")]
    saved = store.round_state(round_no=1)
    assert saved["status"] == "completed"
    assert saved["admitted_issue_ids"] == []
    if prerequisite == "feedback_imported":
        assert "users" not in saved["stages"]
    seal = store.unit(
        round_no=1,
        stage="round_sealed",
        key=pipeline.operation_key(1, "round_sealed", "stage-marker"),
    )
    assert seal["input"] == {"user_sha": "seed", "sealed_sha": "delivered"}
    assert seal["observed_postconditions"] == {"completed": True}
    assert saved["stages"]["triage"]["dependencies"] == [prerequisite]
    assert pipeline.run(round_no=1, user_sha="seed") == "delivered"
    assert len(events) == 2
    with pytest.raises(RecoveryConflictError, match="SHA"):
        pipeline.run(round_no=1, user_sha="changed")


def test_bootstrap_and_ordinary_operations_cannot_deduplicate_each_other(tmp_path):
    operations = {"ordinary": [], "bootstrap": []}

    class Role:
        def __init__(self, label):
            self.label = label
            self.dependencies = []
            self.stores = []

        def bind_feedback_dependency(self, dependency):
            self.dependencies.append(dependency)

        def bind_recovery(self, store):
            self.stores.append(store)

        def propose_once(self):
            operations[self.label].append(current_usage_context().operation)

        def admit_once(self):
            operations[self.label].append(current_usage_context().operation or "owner")
            return SimpleNamespace(admitted=[])

    for label, prerequisite, namespace in [
        ("ordinary", "users", None),
        ("bootstrap", "feedback_imported", "continuation-bootstrap"),
    ]:
        store = _store(tmp_path, label)
        role = Role(label)
        pipeline = _pipeline(
            store,
            [],
            prerequisite=prerequisite,
            operation_namespace=namespace,
            divergents=[role],
            synthesizers=[role],
            owner=role,
        )
        _complete_prerequisite(pipeline, prerequisite)
        pipeline.run(round_no=1, user_sha="seed")
        assert role.dependencies == [prerequisite, prerequisite]
        assert role.stores == [store] * 6
    assert operations["ordinary"] == [
        operation_key(1, "divergent", 0),
        operation_key(1, "synthesizer", 0),
        "owner",
    ]
    assert set(operations["ordinary"]).isdisjoint(operations["bootstrap"])


def test_delivery_resume_reconciles_without_repeating_generation(tmp_path):
    store = _store(tmp_path, "bootstrap")
    events = []
    complete = False

    class Owner:
        def admit_once(self):
            events.append("owner")
            return SimpleNamespace(admitted=[17])

    def wait_delivery(*, numbers):
        assert numbers == [17]
        events.append("wait")
        raise RoundDeliveryBlocked(numbers=[17], reason="timeout")

    pipeline = _pipeline(
        store,
        events,
        owner=Owner(),
        prerequisite="feedback_imported",
        operation_namespace="continuation-bootstrap",
        wait_delivery=wait_delivery,
        fetch_issue=lambda number: {"state": "closed" if complete else "open", "labels": ["ready"]},
    )
    _complete_prerequisite(pipeline, "feedback_imported")
    with pytest.raises(RoundDeliveryBlocked, match="timeout"):
        pipeline.run(round_no=1, user_sha="seed")
    assert store.stage_status(round_no=1, stage="round_sealed") == "pending"
    assert events == ["owner", "wait"]
    complete = True
    assert pipeline.run(round_no=1, user_sha="seed") == "delivered"
    assert events == ["owner", "wait", "guard", ("descendant", "seed", "delivered")]


def test_integrity_failure_never_writes_seal(tmp_path):
    store = _store(tmp_path)

    def guard():
        raise RuntimeError("modified controller")

    pipeline = FeedbackPipeline(
        recovery=store,
        resolve_head=lambda: "delivered",
        assert_descendant=lambda **kwargs: None,
        integrity_guard=guard,
    )
    _complete_prerequisite(pipeline, "users")
    with pytest.raises(RuntimeError, match="modified"):
        pipeline.run(round_no=1, user_sha="seed")
    assert store.stage_status(round_no=1, stage="round_sealed") == "pending"
    assert store.round_state(round_no=1)["status"] != "completed"


def test_bootstrap_requires_explicit_namespace(tmp_path):
    with pytest.raises(ValueError, match="namespace"):
        FeedbackPipeline(
            recovery=_store(tmp_path),
            resolve_head=lambda: "seed",
            assert_descendant=lambda **kwargs: None,
            prerequisite="feedback_imported",
        )


def test_reused_roles_resume_ordinary_ledger_after_bootstrap(tmp_path):
    """Construction order cannot make ordinary roles persist into bootstrap state."""
    visited = []

    class Divergent:
        def bind_recovery(self, store):
            self.store = store

        def bind_feedback_dependency(self, prerequisite):
            self.prerequisite = prerequisite

        def propose_once(self):
            visited.append((self.store.snapshot()["identity"]["plan_hash"], self.prerequisite))

    role = Divergent()
    ordinary = _pipeline(_store(tmp_path, "ordinary"), [], divergents=[role])
    bootstrap = _pipeline(
        _store(tmp_path, "bootstrap"),
        [],
        divergents=[role],
        prerequisite="feedback_imported",
        operation_namespace="continuation-bootstrap",
    )
    _complete_prerequisite(bootstrap, "feedback_imported")
    _complete_prerequisite(ordinary, "users")
    bootstrap.run(round_no=1, user_sha="seed")
    ordinary.run(round_no=1, user_sha="seed")
    assert visited == [("bootstrap", "feedback_imported"), ("ordinary", "users")]


@pytest.mark.parametrize("prerequisite", ["users", "feedback_imported"])
@pytest.mark.parametrize("failure_reporting", ["exception", "outcome"])
def test_real_triager_saved_output_retries_failed_side_effect(
    tmp_path, prerequisite, failure_reporting
):
    """A failed inner item cannot leave its outer worker falsely completed."""
    from auto_designer.demand.triage import TriageOutcome, Triager
    from auto_designer.models import IssueDraft
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore

    tracker = FakeTracker()
    number = tracker.create_issue(
        IssueDraft(title="Task stalled", body="No progress", labels=["report", "round-1"])
    ).number
    calls = {"model": 0, "apply": 0}

    class ModelTriager(Triager):
        def triage_once(self, **kwargs):
            try:
                return super().triage_once(**kwargs)
            except RecoveryConflictError as exc:
                if failure_reporting == "exception":
                    raise
                return TriageOutcome(failed={number: str(exc)})

        def _run_agent(self, *, pending):
            calls["model"] += 1
            return json.dumps(
                {
                    "dispositions": [
                        {
                            "issue": pending[0].number,
                            "disposition": "reject",
                            "reason": "outside product scope",
                        }
                    ]
                }
            )

        def _apply_with_retry(self, *args, **kwargs):
            calls["apply"] += 1
            if calls["apply"] == 1:
                raise RuntimeError("tracker response lost")
            return super()._apply_with_retry(*args, **kwargs)

    store = _store(tmp_path, prerequisite)
    triager = ModelTriager(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path / "harness"),
        str(tmp_path / "definitions"),
    )
    pipeline = _pipeline(
        store,
        [],
        triagers=[triager],
        prerequisite=prerequisite,
        operation_namespace="continuation-bootstrap"
        if prerequisite == "feedback_imported"
        else None,
    )
    _complete_prerequisite(pipeline, prerequisite)
    with pytest.raises(RoundDeliveryBlocked, match="triage-incomplete"):
        pipeline.run(round_no=1, user_sha="seed")
    worker = store.unit(round_no=1, stage="triage", key=pipeline.operation_key(1, "triage", 0))
    assert worker["status"] == "failed"
    items = store.round_state(round_no=1)["stages"]["triage"]["units"].values()
    assert any(item.get("output_digest") for item in items)
    assert store.stage_status(round_no=1, stage="round_sealed") == "pending"
    assert pipeline.run(round_no=1, user_sha="seed") == "delivered"
    assert calls == {"model": 1, "apply": 2}
    assert tracker.issue(number)["state"] == "closed"
