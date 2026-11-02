"""Spec-0074/T2: actual frozen children, scripted single-run lifecycle boundaries."""

import copy
import json
import threading
from pathlib import Path

import pytest

from ahe_beta.experiment import batch, materials, runtime
from ahe_beta.experiment.batch_config import load_batch_config
from ahe_beta.experiment.batch_store import BatchStore
from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.manifest import read_runtime, update_runtime
from test_experiment_batch_config import batch_path as batch_inputs
from test_experiment_materials import prepared_inputs as material_inputs

REAL_STATUS = runtime.status_v2


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return material_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def batch_path(prepared_inputs, tmp_path):
    return batch_inputs.__wrapped__(prepared_inputs, tmp_path)


class Lifecycle:
    def __init__(self):
        self.calls = []
        self.states = {}
        self.ticks = {}
        self.behavior = {}
        self.maximum = 0
        self.finish_after = 3

    def prepare(self, *, config_path, root, secrets_file):
        self.calls.append(("prepare", root.name))
        manifest = materials.prepare_materials(config_path, root, secrets_file)
        update_runtime(
            run_dir=Path(manifest["run_dir"]),
            action="fixture-prepared",
            changes={"preparation_complete": True, "experiment_state": "PREPARED"},
        )
        return {"run_id": manifest["run_id"]}

    def status(self, *, run_id, root, secrets_file):
        receipt = read_runtime(run_dir=root / run_id)
        state = self.states.get(run_id, "PREPARED")
        behavior = self.behavior.get(run_id)
        if state == "RUNNING":
            self.ticks[run_id] = self.ticks.get(run_id, 0) + 1
            if self.ticks[run_id] >= self.finish_after and behavior not in {
                "unknown",
                "operation",
                "lost",
                "ambiguous",
            }:
                state = "FAILED" if behavior == "failed" else "COMPLETED"
                self.states[run_id] = state
        controller = {
            "PREPARED": "ABSENT",
            "RUNNING": "RUNNING",
            "COMPLETED": "EXITED",
            "FAILED": "EXITED",
            "STOPPED": "STOPPED",
            "LOST": "LOST",
        }[state]
        if behavior == "ambiguous":
            state, controller = "PREPARED", "ABSENT"
        if behavior == "lost" and state == "RUNNING":
            state, controller = "LOST", "LOST"
        observation = "UNKNOWN" if behavior == "unknown" and state == "RUNNING" else "OBSERVED"
        if behavior == "operation" and state == "RUNNING":
            observation = "OPERATION_IN_PROGRESS"
        return {
            **receipt,
            "experiment_state": state,
            "observation": observation,
            "resource_state": "ABSENT"
            if state == "PREPARED" and behavior != "ambiguous"
            else ("LOST" if state == "LOST" else "RUNNING"),
            "provider": {
                "controller": {
                    "state": controller,
                    "running": state == "RUNNING",
                    "nonce": "nonce-" + run_id,
                }
            },
        }

    def run(self, *, run_id, root, secrets_file, resume_run, monitor):
        assert monitor is False
        self.calls.append(("resume" if resume_run else "run", run_id))
        self.states[run_id] = "RUNNING"
        self.ticks[run_id] = 0
        update_runtime(
            run_dir=root / run_id,
            action="fixture-started",
            changes={
                "experiment_state": "RUNNING",
                "resource_state": "RUNNING",
                "launch_mode": "resume" if resume_run else "fresh",
                "collection_state": "PARTIAL",
            },
        )
        (root / run_id / "resources.json").write_text("{}")
        self.maximum = max(self.maximum, sum(value == "RUNNING" for value in self.states.values()))
        return {"experiment_state": "RUNNING"}

    def collect(self, *, run_id, root, secrets_file):
        self.calls.append(("collect", run_id))
        if self.behavior.get(run_id) == "partial":
            return {"collection_state": "PARTIAL"}
        assert self.states.get(run_id) in {"COMPLETED", "FAILED", "STOPPED"}
        update_runtime(
            run_dir=root / run_id,
            action="fixture-collected",
            changes={"collection_state": "COMPLETE"},
        )
        return {
            "collection_state": "COMPLETE",
            "controller": {
                "nonce": "nonce-" + run_id,
                "state": "STOPPED" if self.states[run_id] == "STOPPED" else "EXITED",
                "running": False,
            },
        }

    def stop(self, *, run_id, root, secrets_file):
        self.calls.append(("stop", run_id))
        self.states[run_id] = "STOPPED"
        return {"experiment_state": "STOPPED"}


@pytest.fixture
def lifecycle(monkeypatch):
    fake = Lifecycle()
    monkeypatch.setenv("MODEL_BASE_URL", "https://fixture.invalid")
    monkeypatch.setenv("MODEL_API_KEY", "fixture-key")
    for name, method in {
        "prepare_v2": fake.prepare,
        "run_v2": fake.run,
        "status_v2": fake.status,
        "stop_v2": fake.stop,
        "collect_v2": fake.collect,
    }.items():
        monkeypatch.setattr(runtime, name, method)
    monkeypatch.setattr(
        runtime,
        "check_v2",
        lambda *, config_path, offline, secrets_file: {
            "ok": True,
            "offline": offline,
            **materials.check_materials(config_path),
        },
    )
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    return fake


def prepare(batch_path, tmp_path):
    result = batch.prepare_batch(batch_path, root=tmp_path / "runs")
    assert result["ok"] and result["batch_state"] == "READY"
    return BatchStore.load(result["batch_id"], tmp_path / "runs")


@pytest.mark.parametrize("limit", [1, 2])
def test_start_ack_retains_lease_and_terminal_collect_releases(
    batch_path, tmp_path, lifecycle, limit
):
    payload = json.loads(batch_path.read_text())
    payload["max_parallel_runs"] = limit
    batch_path.write_text(json.dumps(payload))
    store = prepare(batch_path, tmp_path)
    progress = []
    result = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", poll_seconds=0.01, progress=progress.append
    )
    assert result["ok"] and result["experiment_success"]
    assert result["batch_state"] == "COMPLETED" and result["collection_state"] == "COMPLETE"
    assert lifecycle.maximum == limit
    assert len([item for item in lifecycle.calls if item[0] == "run"]) == 2
    assert len([item for item in lifecycle.calls if item[0] == "collect"]) == 2
    assert result["counts"]["active"] == 0 and result["counts"]["retained_resources"] == 2
    assert result["member_configuration"]["first"]["max_parallel_users"] == 1
    before = copy.deepcopy(lifecycle.calls)
    batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert lifecycle.calls == before


@pytest.mark.parametrize(
    "behavior,expected,leases",
    [
        ("unknown", "BLOCKED_OBSERVATION", 1),
        ("operation", "BLOCKED_OBSERVATION", 1),
        ("partial", "BLOCKED_COLLECTION", 1),
        ("lost", "BLOCKED_LOST", 0),
        ("failed", "BLOCKED_MEMBER_FAILURE", 0),
    ],
)
def test_uncertain_or_failed_member_blocks_pending(
    batch_path, tmp_path, lifecycle, behavior, expected, leases
):
    store = prepare(batch_path, tmp_path)
    first = store.state()["entries"]["first"]["run_id"]
    lifecycle.behavior[first] = behavior
    result = batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert not result["ok"] and result["batch_state"] == expected
    assert result["counts"]["active"] == leases
    assert len([item for item in lifecycle.calls if item[0] == "run"]) == 1
    if behavior in {"failed", "lost"}:
        batch.run_batch(
            store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
        )
        assert len([item for item in lifecycle.calls if item[0] == "run"]) == 1


def test_crash_after_start_ack_attaches_original_run(batch_path, tmp_path, lifecycle, monkeypatch):
    store = prepare(batch_path, tmp_path)
    original = runtime.run_v2
    first = store.state()["entries"]["first"]["run_id"]

    def crash(**kwargs):
        original(**kwargs)
        raise KeyboardInterrupt("after provider acknowledgement")

    monkeypatch.setattr(runtime, "run_v2", crash)
    result = batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert result["batch_state"] == "INTERRUPTED" and result["counts"]["active"] == 1
    monkeypatch.setattr(runtime, "run_v2", original)
    completed = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )
    assert completed["experiment_success"]
    assert lifecycle.calls.count(("run", first)) == 1
    assert len([item for item in lifecycle.calls if item[0] == "prepare"]) == 2


def test_crash_after_intent_before_start_is_safely_resumed(batch_path, tmp_path, lifecycle):
    store = prepare(batch_path, tmp_path)

    def interrupt(value):
        if value.get("phase") == "STARTING":
            raise KeyboardInterrupt

    result = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", progress=interrupt, poll_seconds=0.01
    )
    assert result["batch_state"] == "INTERRUPTED"
    assert not [item for item in lifecycle.calls if item[0] == "run"]
    assert batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )["experiment_success"]


def test_bootstrap_resources_without_ack_are_not_reprovisioned(batch_path, tmp_path, lifecycle):
    store = prepare(batch_path, tmp_path)
    run_id = store.state()["entries"]["first"]["run_id"]
    directory = store.child_root("first") / run_id
    (directory / "resources.json").write_text(json.dumps({"bootstrap_complete": False}))
    update_runtime(
        run_dir=directory,
        action="provision-intent",
        changes={"resource_state": "PROVISIONING", "launch_mode": "fresh"},
    )
    store.update("launch-intent", {}, {"first": {"launch_intent": True, "active_lease": True}})
    lifecycle.behavior[run_id] = "ambiguous"
    result = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )
    assert result["batch_state"] == "BLOCKED_PROVISION" and result["counts"]["active"] == 1
    assert not [item for item in lifecycle.calls if item[0] == "run"]


def test_partial_terminal_collection_retry_then_resume_pending(batch_path, tmp_path, lifecycle):
    store = prepare(batch_path, tmp_path)
    first = store.state()["entries"]["first"]["run_id"]
    lifecycle.behavior[first] = "partial"
    assert not batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)["ok"]
    lifecycle.behavior.pop(first)
    assert batch.collect_batch(store.batch_id, root=tmp_path / "runs")["counts"]["active"] == 0
    assert batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )["experiment_success"]
    assert lifecycle.calls.count(("run", first)) == 1


def test_prepare_crash_recovers_unique_original_child(batch_path, tmp_path, lifecycle, monkeypatch):
    original = runtime.prepare_v2

    def crash(**kwargs):
        original(**kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime, "prepare_v2", crash)
    with pytest.raises(KeyboardInterrupt):
        batch.prepare_batch(batch_path, root=tmp_path / "runs")
    directory = next((tmp_path / "runs/.batches").iterdir())
    store = BatchStore.load(directory.name, tmp_path / "runs")
    original_child = store.find_child(store.intent["config"]["entries"][0])["run_id"]
    monkeypatch.setattr(runtime, "prepare_v2", original)
    result = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )
    assert result["experiment_success"]
    assert result["entries"]["first"]["run_id"] == original_child
    assert lifecycle.calls.count(("prepare", "first")) == 1


def test_frozen_unprepared_child_blocks_instead_of_creating_replacement(
    batch_path, tmp_path, lifecycle
):
    store = BatchStore.create(load_batch_config(batch_path), tmp_path / "runs")
    entry = store.intent["config"]["entries"][0]
    original = materials.prepare_materials(entry["config_path"], store.child_root("first"))
    result = batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )
    assert result["batch_state"] == "BLOCKED_PREPARATION"
    assert result["entries"]["first"]["run_id"] == original["run_id"]
    assert not lifecycle.calls


def test_stop_during_launch_preserves_pause_and_prevents_next_dispatch(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = runtime.run_v2
    result = {}

    def in_flight(**kwargs):
        entered.set()
        assert release.wait(10)
        return original(**kwargs)

    monkeypatch.setattr(runtime, "run_v2", in_flight)
    scheduler = threading.Thread(
        target=lambda: result.update(
            run=batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
        )
    )
    scheduler.start()
    assert entered.wait(10)
    stopper = threading.Thread(
        target=lambda: result.update(stop=batch.stop_batch(store.batch_id, root=tmp_path / "runs"))
    )
    stopper.start()
    for _ in range(10000):
        if store.state().get("paused"):
            break
    assert store.state()["paused"] is True
    assert (
        store.state()["batch_state"] == "PAUSING"
        and store.state()["entries"]["first"]["active_lease"]
    )
    release.set()
    scheduler.join(10)
    stopper.join(10)
    assert not scheduler.is_alive() and not stopper.is_alive()
    assert store.state()["paused"] is True
    assert result["stop"]["batch_state"] == "PAUSED"
    assert len([item for item in lifecycle.calls if item[0] == "run"]) == 1
    monkeypatch.setattr(runtime, "run_v2", original)
    assert batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )["experiment_success"]


def test_refresh_derived_state_retries_concurrent_pause(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)
    original = store.update
    raced = False

    def update(action, changes, entries=None, expected_revision=None):
        nonlocal raced
        if expected_revision is not None and not raced:
            raced = True
            original("stop", {"paused": True, "batch_state": "PAUSING"})
        return original(action, changes, entries, expected_revision)

    monkeypatch.setattr(store, "update", update)
    batch._refresh_state(store)
    assert store.state()["paused"] and store.state()["batch_state"] == "PAUSED"


@pytest.mark.parametrize("seconds", [0, -1, 61, True, float("nan")])
def test_invalid_poll_interval_rejected_before_side_effects(seconds):
    with pytest.raises(ConfigError, match="poll_seconds"):
        batch.run_batch("not-created", poll_seconds=seconds)


def test_real_single_run_prepared_status_is_dispatchable(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)

    class PreparedProvider:
        def inspect(self):
            return {
                "resource_state": "ABSENT",
                "observation": "KNOWN",
                "controller": {"state": "ABSENT", "running": False},
            }

    monkeypatch.setattr(runtime, "status_v2", REAL_STATUS)
    monkeypatch.setattr(runtime, "backend_v2", lambda **kwargs: PreparedProvider())
    result = batch.status_batch(store.batch_id, root=tmp_path / "runs")
    assert result["batch_state"] == "READY"
    assert result["counts"]["pending"] == 2
    assert result["entries"]["first"]["last_status"]["controller_state"] == "ABSENT"


def test_launch_failure_with_no_side_effects_is_not_automatically_retried(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)
    calls = []

    def failed(**kwargs):
        calls.append(kwargs["run_id"])
        raise ConfigError("repository limit: sensitive-credential-do-not-persist")

    monkeypatch.setattr(runtime, "run_v2", failed)
    result = batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert result["batch_state"] == "BLOCKED_MEMBER_FAILURE"
    batch.run_batch(store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01)
    assert len(calls) == 1
    assert "sensitive-credential" not in json.dumps(result)


def test_progress_callback_observes_actual_user_count_changes(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)
    original = runtime.status_v2

    def status(**kwargs):
        value = original(**kwargs)
        completed = lifecycle.ticks.get(kwargs["run_id"], 0)
        value["progress"] = {
            "current_round": 1,
            "observation": "RECOVERY_LEDGER",
            "rounds": {
                "1": {
                    "status": "running",
                    "users": {
                        "completed": completed,
                        "running": 1,
                        "pending": 2 - completed,
                        "sessions": [{"api_key": "never-copy-private-extra-fields"}],
                    },
                }
            },
        }
        return value

    monkeypatch.setattr(runtime, "status_v2", status)
    values = []
    assert batch.run_batch(
        store.batch_id, root=tmp_path / "runs", poll_seconds=0.01, progress=values.append
    )["experiment_success"]
    observed = [
        row["entries"]["first"]["last_status"]["progress"]["rounds"]["1"]["users"]["completed"]
        for row in values
        if "entries" in row
    ]
    assert 1 in observed and 2 in observed
    assert "never-copy-private" not in json.dumps(values)


def test_collection_downgrade_does_not_reuse_old_terminal_receipt(batch_path, tmp_path, lifecycle):
    store = prepare(batch_path, tmp_path)
    assert (
        batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)[
            "collection_state"
        ]
        == "COMPLETE"
    )
    first = store.state()["entries"]["first"]["run_id"]
    update_runtime(
        run_dir=store.child_root("first") / first,
        action="manual-collection-failed",
        changes={"collection_state": "PARTIAL"},
    )
    result = batch.status_batch(store.batch_id, root=tmp_path / "runs")
    assert result["collection_state"] == "PARTIAL" and not result["experiment_success"]
    assert result["entries"]["first"]["phase"] == "AWAITING_COLLECTION"
    assert result["entries"]["first"]["terminal_collection"] is None
    assert result["counts"]["active"] == 1
    assert (
        batch.collect_batch(store.batch_id, root=tmp_path / "runs")["collection_state"]
        == "COMPLETE"
    )


def test_all_selected_checks_precede_any_prepare(batch_path, tmp_path, lifecycle, monkeypatch):
    checks = []

    def check(**kwargs):
        checks.append(kwargs["config_path"])
        if len(checks) == 2:
            raise ConfigError("second provider unavailable")
        return {"ok": True}

    monkeypatch.setattr(runtime, "check_v2", check)
    with pytest.raises(ConfigError, match="unavailable"):
        batch.prepare_batch(batch_path, root=tmp_path / "runs")
    assert len(checks) == 2 and lifecycle.calls == []
    assert not (tmp_path / "runs").exists()


def test_status_does_not_allow_plain_run_after_supervision_interrupt(
    batch_path, tmp_path, lifecycle
):
    store = prepare(batch_path, tmp_path)

    def interrupt(value):
        if value.get("phase") == "STARTING":
            raise KeyboardInterrupt

    batch.run_batch(store.batch_id, root=tmp_path / "runs", progress=interrupt, poll_seconds=0.01)
    status = batch.status_batch(store.batch_id, root=tmp_path / "runs")
    assert status["supervisor_stopped"] is True
    with pytest.raises(ConfigError, match="use batch resume"):
        batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert batch.run_batch(
        store.batch_id, root=tmp_path / "runs", resume_batch=True, poll_seconds=0.01
    )["experiment_success"]


def test_concurrent_pause_ends_resume_before_any_dispatch(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)
    sleeps = []

    def pause(value):
        if value.get("batch_state") == "READY":
            store.update("concurrent-stop", {"paused": True, "batch_state": "PAUSED"})

    def bounded_sleep(seconds):
        sleeps.append(seconds)
        assert len(sleeps) <= 1, "resume must observe the concurrent stop and return"

    monkeypatch.setattr(batch.time, "sleep", bounded_sleep)
    result = batch.run_batch(
        store.batch_id,
        root=tmp_path / "runs",
        resume_batch=True,
        progress=pause,
        poll_seconds=0.01,
    )
    assert result["paused"] and result["batch_state"] == "PAUSED"
    assert result["counts"]["active"] == 0
    assert not any(action in {"run", "resume"} for action, _ in lifecycle.calls)


@pytest.mark.parametrize("change", ["nonce", "missing_nonce", "running", "state", "missing"])
def test_terminal_collection_confirms_observed_attempt_before_releasing_lease(
    batch_path, tmp_path, lifecycle, monkeypatch, change
):
    store = prepare(batch_path, tmp_path)
    store.update(
        "previous-attempt",
        {},
        {"first": {"terminal_collection": {"state": "FAILED", "nonce": "previous-attempt"}}},
    )

    def mismatched_collection(**kwargs):
        receipt = lifecycle.collect(**kwargs)
        if change == "missing":
            receipt.pop("controller")
        elif change == "missing_nonce":
            receipt["controller"].pop("nonce")
        elif change == "nonce":
            receipt["controller"]["nonce"] = "different-attempt"
        elif change == "running":
            receipt["controller"]["running"] = True
        else:
            receipt["controller"]["state"] = "STOPPED"
        return receipt

    monkeypatch.setattr(runtime, "collect_v2", mismatched_collection)
    result = batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)
    assert result["batch_state"] == "BLOCKED_COLLECTION"
    assert result["counts"]["active"] == 1 and result["collection_state"] == "PARTIAL"
    assert result["entries"]["first"]["terminal_collection"] is None
    assert result["entries"]["second"]["launch_intent"] is False
    monkeypatch.setattr(runtime, "collect_v2", lifecycle.collect)
    recovered = batch.collect_batch(store.batch_id, root=tmp_path / "runs")
    assert recovered["counts"]["active"] == 0
    assert recovered["entries"]["first"]["terminal_collection"]["nonce"].startswith("nonce-")
    assert batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)[
        "experiment_success"
    ]


def test_nested_e2b_controller_collection_receipt_matches_observation(
    batch_path, tmp_path, lifecycle, monkeypatch
):
    store = prepare(batch_path, tmp_path)

    def nested_collection(**kwargs):
        receipt = lifecycle.collect(**kwargs)
        receipt["controller"] = {"controller": receipt["controller"]}
        return receipt

    monkeypatch.setattr(runtime, "collect_v2", nested_collection)
    assert batch.run_batch(store.batch_id, root=tmp_path / "runs", poll_seconds=0.01)[
        "experiment_success"
    ]
