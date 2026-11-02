"""Spec-0064/T1: durable recovery ledger and reconciliation protocol."""

from __future__ import annotations

import json

import pytest

from ahe_beta.loop.recovery import (
    EVENT_FILE,
    STATE_FILE,
    RecoveryConflictError,
    RecoveryCorruptError,
    RecoveryIdentity,
    RecoveryIdentityError,
    RecoveryStateMissing,
    RecoveryStore,
    StaleRevisionError,
    UnsafeRecoveryDataError,
    digest_value,
    operation_key,
)


def _identity(**overrides: str) -> RecoveryIdentity:
    values = {
        "experiment_id": "exp-1",
        "run_id": "run-1",
        "config_hash": "config-a",
        "controller_sha": "controller-a",
        "plan_hash": "plan-a",
    }
    values.update(overrides)
    return RecoveryIdentity(**values)


def _store(tmp_path) -> RecoveryStore:
    store = RecoveryStore.initialize(root=tmp_path, identity=_identity())
    store.freeze_round(round_no=1, user_sha="user-a", plan=[{"persona": "p1", "seed": "s1"}])
    return store


def _begin(store: RecoveryStore, *, expected=None) -> str:
    key = operation_key("exp-1", 1, "users", "p1", "s1")
    store.begin_unit(
        round_no=1,
        stage="users",
        key=key,
        input_value={"persona": "p1", "seed": "s1"},
        expected_postconditions=expected,
    )
    return key


def test_initialize_freeze_and_reopen(tmp_path) -> None:
    store = _store(tmp_path)
    reopened = RecoveryStore.open(root=tmp_path, identity=_identity())
    assert reopened.snapshot() == store.snapshot()
    assert reopened.snapshot()["rounds"]["1"]["plan_hash"] == digest_value(
        [{"persona": "p1", "seed": "s1"}]
    )
    events = [json.loads(line) for line in (tmp_path / EVENT_FILE).read_text().splitlines()]
    assert [event["event"] for event in events] == ["initialized", "round_frozen"]


def test_resume_requires_existing_state_and_exact_identity(tmp_path) -> None:
    with pytest.raises(RecoveryStateMissing, match="explicit migration"):
        RecoveryStore.open(root=tmp_path, identity=_identity())
    RecoveryStore.initialize(root=tmp_path, identity=_identity())
    with pytest.raises(RecoveryIdentityError):
        RecoveryStore.open(root=tmp_path, identity=_identity(config_hash="changed"))


def test_output_first_then_external_reconciliation_survives_restart(tmp_path) -> None:
    store = _store(tmp_path)
    key = _begin(store, expected={"session_id": "session-1", "indexed": True})
    store.save_output(round_no=1, stage="users", key=key, output={"feeling": "slow"})

    # Simulate a process death after the external store committed but before the
    # recovery completion marker was written.
    resumed = RecoveryStore.open(root=tmp_path, identity=_identity())
    assert resumed.read_output(round_no=1, stage="users", key=key) == {"feeling": "slow"}
    assert resumed.reconcile_unit(
        round_no=1,
        stage="users",
        key=key,
        observed_postconditions={"session_id": "session-1", "indexed": True, "extra": "ok"},
    )
    assert resumed.unit(round_no=1, stage="users", key=key)["status"] == "completed"
    resumed.complete_stage(round_no=1, stage="users")


def test_retry_only_increments_incomplete_unit_attempt(tmp_path) -> None:
    store = _store(tmp_path)
    key = _begin(store)
    assert store.unit(round_no=1, stage="users", key=key)["attempt"] == 1
    _begin(store)
    assert store.unit(round_no=1, stage="users", key=key)["attempt"] == 2
    store.complete_unit(round_no=1, stage="users", key=key)
    _begin(store)
    assert store.unit(round_no=1, stage="users", key=key)["attempt"] == 2


def test_input_output_and_frozen_round_conflicts_fail_closed(tmp_path) -> None:
    store = _store(tmp_path)
    key = _begin(store)
    with pytest.raises(RecoveryConflictError, match="input digest"):
        store.begin_unit(
            round_no=1,
            stage="users",
            key=key,
            input_value={"persona": "different"},
        )
    store.save_output(round_no=1, stage="users", key=key, output={"value": 1})
    with pytest.raises(RecoveryConflictError, match="output digest"):
        store.save_output(round_no=1, stage="users", key=key, output={"value": 2})
    with pytest.raises(RecoveryConflictError, match="frozen input"):
        store.freeze_round(round_no=1, user_sha="changed", plan=[])


def test_postcondition_mismatch_blocks_unit_and_stage(tmp_path) -> None:
    store = _store(tmp_path)
    key = _begin(store, expected={"state": "closed", "labels": ["merged"]})
    assert not store.reconcile_unit(
        round_no=1,
        stage="users",
        key=key,
        observed_postconditions={"state": "open", "labels": ["merged"]},
    )
    assert store.unit(round_no=1, stage="users", key=key)["status"] == "blocked"
    assert store.stage_status(round_no=1, stage="users") == "blocked"


def test_stage_dependencies_and_seal_are_checked(tmp_path) -> None:
    store = _store(tmp_path)
    key = operation_key("triage", 1)
    with pytest.raises(RecoveryConflictError, match="dependencies"):
        store.begin_unit(
            round_no=1,
            stage="triage",
            key=key,
            input_value={},
            dependencies=("users",),
        )
    user_key = _begin(store)
    store.complete_unit(round_no=1, stage="users", key=user_key)
    store.complete_stage(round_no=1, stage="users")
    store.begin_unit(
        round_no=1,
        stage="triage",
        key=key,
        input_value={},
        dependencies=("users",),
    )
    with pytest.raises(RecoveryConflictError, match="incomplete"):
        store.seal_round(round_no=1, sealed_sha="abc")


def test_old_controller_revision_cannot_overwrite_new_state(tmp_path) -> None:
    first = _store(tmp_path)
    stale = RecoveryStore.open(root=tmp_path, identity=_identity())
    _begin(first)
    with pytest.raises(StaleRevisionError):
        stale.freeze_round(round_no=2, user_sha="user-b", plan=[])


def test_torn_snapshot_and_receipt_digest_are_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    key = _begin(store)
    unit = store.save_output(round_no=1, stage="users", key=key, output={"value": 1})
    receipt = tmp_path / unit["output_artifact"]
    body = json.loads(receipt.read_text())
    body["output"] = {"value": 2}
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(RecoveryCorruptError, match="digest mismatch"):
        store.read_output(round_no=1, stage="users", key=key)

    (tmp_path / STATE_FILE).write_text('{"revision":', encoding="utf-8")
    with pytest.raises(RecoveryCorruptError, match="invalid recovery file"):
        RecoveryStore.open(root=tmp_path, identity=_identity())


def test_secret_shaped_fields_are_never_persisted(tmp_path) -> None:
    store = _store(tmp_path)
    key = operation_key("safe")
    with pytest.raises(UnsafeRecoveryDataError):
        store.begin_unit(
            round_no=1,
            stage="users",
            key=key,
            input_value={"gitea_token": "do-not-write"},
        )
    assert "do-not-write" not in (tmp_path / STATE_FILE).read_text()


def test_operation_key_is_stable_opaque_and_order_sensitive() -> None:
    assert operation_key("round", 1, "user") == operation_key("round", 1, "user")
    assert operation_key("round", 1, "user") != operation_key("user", 1, "round")
    assert "user" not in operation_key("round", 1, "user")
