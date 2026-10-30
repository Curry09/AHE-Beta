"""Spec-0074/T5: real lifecycle/process/round ledgers with offline provider/model boundaries.

No single-run lifecycle function is replaced. The child imports its frozen source;
Docker builds, workspace provisioning, role/model replies and forge delivery are
offline substitutes. This is deliberately not a live Docker or E2B validation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_designer.experiment import batch, engine, runtime, workload
from auto_designer.experiment.batch_store import BatchStore
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.manifest import read_manifest, read_runtime
from test_experiment_materials import prepared_inputs as prepared_inputs


def _json(path):
    return json.loads(path.read_text())


def _controller(root):
    """A real child process running production sessions, durable stages and seals."""
    from auto_designer import invocation
    from auto_designer.experiment.controllers import runtime as shared
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
    from auto_designer.models import IssueDraft, Persona, SeedScenario, WorkspaceSpec
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.harness_adapter import ScriptedHarness
    from auto_designer.user.sim.persona_client import ScriptedPersonaClient

    manifest = read_manifest(path=root / "manifest.json")
    catalog = workload.read_task_catalog(root, manifest)
    plan = workload.read_session_plan(root, manifest)
    tasks = workload.tasks_by_id(catalog)
    repo = root / "runtime/offline-harness"
    store = SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions")
    tracker = FakeTracker()
    identity = RecoveryIdentity(
        experiment_id=manifest["run_id"],
        run_id=manifest["run_id"],
        config_hash=manifest["config_hash"],
        controller_sha=manifest["controller_sha"],
        plan_hash=manifest["plan_hash"],
    )
    recovery = (
        RecoveryStore.open(root=root / "checkpoints", identity=identity)
        if (root / "checkpoints/recovery.json").exists()
        else RecoveryStore.initialize(root=root / "checkpoints", identity=identity)
    )
    if not (Path(os.environ["ROLE_RUNS_DIR"]) / "manifest.json").exists():
        invocation.init_manifest(roster={"user": 1, "owner": 1}, models={})
    # Initialization is durable before interruption, so resume uses the same identity.
    (root / "runtime/runner-ready").touch()
    deadline = time.monotonic() + 20
    while (root / "runtime/hold").exists():
        if time.monotonic() > deadline:
            raise TimeoutError("test barrier not released")
        time.sleep(0.02)
    time.sleep(0.3)  # The engine must acknowledge an actual live process.

    class Client(ScriptedPersonaClient):
        def respond(self, system, user):
            if "<direct_review>" in user:
                return {
                    "verdict": "file_issue",
                    "feedback": "Missing verified artifact",
                    "issue": "Implement the requested artifact",
                    "score": 2,
                    "reason": "Artifact missing",
                }
            return super().respond(system, user)

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            if (root / "runtime/model-error").exists():
                raise RuntimeError("offline model transport failed")
            return ScriptedHarness()

    class AdmissionAndDelivery:
        """Offline role/forge boundary; actual orchestrator admission and gate stay live."""

        def admit_once(self):
            issue = tracker.create_issue(
                IssueDraft("Deliver artifact", "Change requested", ["ready"])
            )
            (repo / "delivered.txt").write_text("actual delivered artifact\n")
            subprocess.run(["git", "-C", str(repo), "add", "delivered.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "delivered artifact",
                ],
                check=True,
            )
            tracker.set_state(issue.number, "closed", "delivered")
            (root / "runtime/delivery.json").write_text(json.dumps({"issue": issue.number}))
            return SimpleNamespace(admitted=[issue.number])

    def resolve(binding):
        task = tasks[binding["task_id"]]
        instruction = workload.task_material_path(root, manifest, task, "instruction").read_text()
        return Persona(binding["persona_id"], "expert", "python", "task", "precise"), SeedScenario(
            instruction,
            WorkspaceSpec(
                kind="empty",
                params={
                    "task_id": task["id"],
                    "instance_id": task["id"],
                    "task_digest": task["digest"],
                    "task_kind": task["kind"],
                    "interaction": binding["interaction"],
                },
            ),
        )

    def round_end(number, sha):
        state = recovery.round_state(round_no=number)
        invocation.append_round(round_no=number, user_sha=state["user_sha"], sealed_sha=sha)
        if number == 1:
            (root / "runtime/round-one-ready").touch()
            deadline = time.monotonic() + 20
            while (root / "runtime/hold-second").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("round barrier not released")
                time.sleep(0.02)

    runner = shared._make_user_run_session_fn(
        client_factory=Client,
        tracker=tracker,
        store=store,
        sim_personas={},
    )
    orchestrator = Orchestrator(
        launcher=Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=runner,
        initial_ref="main",
        recovery=recovery,
        frozen_session_plan=lambda number: plan["rounds"][number - 1],
        resolve_session=resolve,
        task_kinds={key: task["kind"] for key, task in tasks.items()},
        owner=AdmissionAndDelivery(),
        fetch_issue=lambda number: tracker.get_issue(number=number),
        on_round_end=round_end,
    )
    orchestrator.run(manifest["config"]["rounds"]["count"])
    (root / "runtime/import-location").write_text(__import__("auto_designer").__file__)


class LostSupervisor(BaseException):
    """Simulate loss after provider startup but before single-run launch receipt."""


class OfflineProvider:
    def __init__(self):
        self.roots = {}
        self.calls = []
        self.behaviors = {}
        self.maximum = 0
        self.launch_barrier = []

    def adapter(self, *, run_dir, manifest, credentials):
        self.roots[manifest["run_id"]] = run_dir
        return Adapter(self, run_dir, manifest)

    def active(self):
        return sum(
            engine.inspect_controller(path).get("running", False) for path in self.roots.values()
        )

    def wait(self, predicate, *, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                logs = "\n".join(engine.controller_logs(root) for root in self.roots.values())
                pytest.fail("offline controller did not reach expected state:\n" + logs)
            time.sleep(0.02)


class Adapter:
    def __init__(self, provider, root, manifest):
        self.provider, self.root, self.manifest = provider, root, manifest
        self.id = manifest["run_id"]

    def provision(self):
        self.provider.calls.append(("provision", self.id))
        if self.provider.behaviors.get(self.id) == "quota":
            raise RuntimeError("repository limit: offline quota failure")
        engine.materialize_controller_source(self.root, self.manifest)
        repo = self.root / "runtime/offline-harness"
        if not repo.exists():
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            (repo / "entry.py").write_text("pass\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-qm",
                    "baseline",
                ],
                check=True,
            )
        (self.root / "resources.json").write_text(json.dumps({"offline_resource": self.id}))

    def preflight(self):
        pass

    def launch(self, *, mode):
        self.provider.calls.append((mode, self.id))
        source = self.root / "source/controller/backend"
        env = {
            "PYTHONPATH": str(source),
            "ROLE_RUNS_DIR": str(self.root / "data/role_runs" / self.id),
            "AUTO_DESIGNER_RUN_ID": self.id,
        }
        receipt = engine.launch_controller(
            run_dir=self.root,
            command=[sys.executable, str(Path(__file__).resolve()), "--runner", str(self.root)],
            env=env,
        )
        self.provider.maximum = max(self.provider.maximum, self.provider.active())
        # Keep the deliberately short workers alive until both real processes
        # start. Frozen SDK extraction can take longer than the worker itself;
        # overlap must not depend on a machine-specific startup speed.
        if self.provider.launch_barrier and self.provider.active() == len(
            self.provider.launch_barrier
        ):
            for root in self.provider.launch_barrier:
                (root / "runtime/hold").unlink(missing_ok=True)
            self.provider.launch_barrier = []
        if self.provider.behaviors.get(self.id) == "crash":
            self.provider.behaviors.pop(self.id)
            raise LostSupervisor()
        return {"controller": receipt, "resource_state": "RUNNING"}

    def inspect(self):
        if (
            self.provider.behaviors.get(self.id) == "unknown"
            and (self.root / "resources.json").exists()
        ):
            return {"observation": "UNKNOWN", "resource_state": "RUNNING"}
        return {
            "controller": engine.inspect_controller(self.root),
            "resource_state": "RUNNING" if (self.root / "resources.json").exists() else "ABSENT",
        }

    def collect(self):
        controller = engine.inspect_controller(self.root)
        if self.provider.behaviors.get(self.id) == "wrong-nonce":
            controller = {**controller, "nonce": "another-generation"}
        return {
            "snapshot_dir": str(self.root),
            "files": {},
            "controller": controller,
            "terminal": controller["state"] in {"STOPPED", "EXITED"},
            "consistent": self.provider.behaviors.get(self.id) != "partial",
        }

    def stop(self, *, grace_seconds):
        return engine.stop_controller(self.root, grace_seconds=min(grace_seconds, 3))


@pytest.fixture
def setup_batch(prepared_inputs, tmp_path, monkeypatch):
    config = _json(prepared_inputs)
    config["rounds"]["count"] = 2
    prepared_inputs.write_text(json.dumps(config))
    package_path = tmp_path / "task.json"
    package = _json(package_path)
    package["interaction"] = "direct"
    package_path.write_text(json.dumps(package))
    monkeypatch.setenv("MODEL_BASE_URL", "https://offline.invalid")
    monkeypatch.setenv("MODEL_API_KEY", "offline-secret-never-published")
    real_run = subprocess.run

    def provider_command(command, *args, **kwargs):
        if command[0] == "docker":
            return subprocess.CompletedProcess(command, 0, stdout="offline provider", stderr="")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", provider_command)
    monkeypatch.setattr(
        "auto_designer.experiment.backends.local.prepare_images", lambda **kwargs: None
    )
    provider = OfflineProvider()
    monkeypatch.setattr(runtime, "backend_v2", provider.adapter)
    path = tmp_path / "batch.json"
    root = tmp_path / "runs"

    def prepare(limit=1):
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "offline-integration",
                    "max_parallel_runs": limit,
                    "entries": [
                        {"id": key, "config": str(prepared_inputs)} for key in ("first", "second")
                    ],
                }
            )
        )
        result = batch.prepare_batch(path, root=root)
        assert result["ok"], result
        return BatchStore.load(result["batch_id"], root)

    yield SimpleNamespace(prepare=prepare, provider=provider, root=root)
    for directory in provider.roots.values():
        engine.stop_controller(directory, grace_seconds=2)


def _members(store):
    return {
        key: store.child_root(key) / row["run_id"] for key, row in store.state()["entries"].items()
    }


def _run(fixture, store, **kwargs):
    return batch.run_batch(store.batch_id, root=fixture.root, poll_seconds=0.03, **kwargs)


@pytest.mark.parametrize("limit", [1, 2])
def test_two_real_processes_seal_deliver_collect_and_respect_active_cap(setup_batch, limit):
    fixture = setup_batch
    store = fixture.prepare(limit)
    if limit == 2:
        fixture.provider.launch_barrier = list(_members(store).values())
        for root in fixture.provider.launch_barrier:
            (root / "runtime/hold").touch()
    result = _run(fixture, store)
    assert result["ok"] and result["experiment_success"], result
    assert fixture.provider.maximum == limit
    for directory in _members(store).values():
        ledger = _json(directory / "checkpoints/recovery.json")
        assert all(row["status"] == "completed" for row in ledger["rounds"].values())
        assert ledger["rounds"]["1"]["admitted_issue_ids"]
        assert ledger["rounds"]["1"]["user_sha"] != ledger["rounds"]["1"]["sealed_sha"]
        assert "owner" not in ledger["rounds"]["2"]["stages"]
        assert (directory / "runtime/offline-harness/delivered.txt").read_text().strip()
        index = _json(directory / "data/role_runs" / directory.name / "sessions/index.json")
        assert len(index) == 2 and len({row["session_id"] for row in index}) == 2
        assert (
            str(directory / "source/controller/backend")
            in (directory / "runtime/import-location").read_text()
        )
        collection = read_runtime(run_dir=directory)["collection"]
        assert collection["collection_state"] == "COMPLETE"
        with tarfile.open(collection["archive"]) as archive:
            assert any("recovery.json" in name for name in archive.getnames())
            assert any("delivered.txt" in name for name in archive.getnames())
            assert b"offline-secret-never-published" not in b"".join(
                archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            )
    before = list(fixture.provider.calls)
    assert _run(fixture, store)["ok"]
    assert batch.collect_batch(store.batch_id, root=fixture.root)["ok"]
    assert fixture.provider.calls == before


def test_crash_after_real_start_ack_resumes_same_run_without_reprovision(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    fixture.provider.behaviors[first.name] = "crash"
    with pytest.raises(LostSupervisor):
        _run(fixture, store)
    assert store.state()["entries"]["first"]["active_lease"]
    assert engine.inspect_controller(first)["running"]
    assert _run(fixture, store, resume_batch=True)["ok"]
    assert fixture.provider.calls.count(("provision", first.name)) == 1
    assert fixture.provider.calls.count(("fresh", first.name)) == 1


def test_unknown_observation_holds_real_process_lease_and_pending_member(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]

    def lose_observation(value):
        if fixture.provider.active():
            fixture.provider.behaviors[first.name] = "unknown"

    result = _run(fixture, store, progress=lose_observation)
    assert result["batch_state"] == "BLOCKED_OBSERVATION", result
    assert result["counts"]["active"] == 1 and result["counts"]["pending"] == 1
    assert fixture.provider.calls.count(("fresh", first.name)) == 1
    fixture.provider.behaviors.clear()
    assert _run(fixture, store, resume_batch=True)["ok"]


def test_partial_archive_holds_slot_until_actual_terminal_collection_retry(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    fixture.provider.behaviors[first.name] = "partial"
    result = _run(fixture, store)
    assert result["batch_state"] == "BLOCKED_COLLECTION", result
    assert result["counts"]["active"] == 1 and result["counts"]["pending"] == 1
    assert read_runtime(run_dir=first)["collection_state"] == "PARTIAL"
    fixture.provider.behaviors.clear()
    assert batch.collect_batch(store.batch_id, root=fixture.root)["ok"]
    assert _run(fixture, store, resume_batch=True)["ok"]
    assert fixture.provider.calls.count(("fresh", first.name)) == 1


def test_stop_resume_preserves_child_identity_and_recovery_with_real_signals(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    (first / "runtime").mkdir(exist_ok=True)
    (first / "runtime/hold-second").touch()

    def detach(value):
        if fixture.provider.active():
            raise KeyboardInterrupt

    result = _run(fixture, store, progress=detach)
    assert result["batch_state"] == "INTERRUPTED"
    fixture.provider.wait(lambda: (first / "runtime/round-one-ready").exists())
    identity = _json(first / "checkpoints/recovery.json")["identity"]
    first_seal = _json(first / "checkpoints/recovery.json")["rounds"]["1"]["sealed_sha"]
    stopped = batch.stop_batch(store.batch_id, root=fixture.root)
    assert stopped["batch_state"] == "PAUSED", stopped
    assert engine.inspect_controller(first)["state"] == "STOPPED"
    (first / "runtime/hold-second").unlink()
    assert _run(fixture, store, resume_batch=True)["ok"]
    assert _json(first / "checkpoints/recovery.json")["identity"] == identity
    assert _json(first / "checkpoints/recovery.json")["rounds"]["1"]["sealed_sha"] == first_seal
    assert (
        subprocess.check_output(
            ["git", "-C", str(first / "runtime/offline-harness"), "rev-list", "--count", "main"],
            text=True,
        ).strip()
        == "2"
    )
    assert fixture.provider.calls.count(("fresh", first.name)) == 1
    assert fixture.provider.calls.count(("resume", first.name)) == 1
    index = first / "data/role_runs" / first.name / "sessions/index.json"
    assert len(_json(index)) == 2


@pytest.mark.parametrize("failure", ["quota", "model"])
def test_provider_or_model_failure_blocks_pending_without_replacement(setup_batch, failure):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    if failure == "quota":
        fixture.provider.behaviors[first.name] = "quota"
    else:
        (first / "runtime").mkdir(exist_ok=True)
        (first / "runtime/model-error").touch()
    result = _run(fixture, store)
    assert not result["ok"] and result["counts"]["pending"] == 1, result
    if failure == "model":
        assert result["batch_state"] == "BLOCKED_MEMBER_FAILURE"
        assert read_runtime(run_dir=first)["collection_state"] == "COMPLETE"
        assert not engine.inspect_controller(first)["experiment_complete"]
    else:
        assert result["counts"]["active"] == 1
    before = list(fixture.provider.calls)
    assert not _run(fixture, store, resume_batch=True)["ok"]
    assert fixture.provider.calls == before


def test_changed_child_manifest_is_rejected_before_any_real_launch(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    manifest = _json(first / "manifest.json")
    manifest["config_hash"] = "tampered"
    (first / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ConfigError):
        _run(fixture, store)
    assert fixture.provider.calls == []


def test_archive_from_wrong_controller_generation_cannot_release_live_lease(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    first = _members(store)["first"]
    fixture.provider.behaviors[first.name] = "wrong-nonce"
    result = _run(fixture, store)
    assert result["batch_state"] == "BLOCKED_COLLECTION", result
    assert result["counts"]["active"] == 1 and result["counts"]["pending"] == 1
    # A COMPLETE single-run archive alone must not release the batch's generation lease.
    assert read_runtime(run_dir=first)["collection_state"] == "COMPLETE"
    fixture.provider.behaviors.clear()
    assert batch.collect_batch(store.batch_id, root=fixture.root)["ok"]
    assert _run(fixture, store, resume_batch=True)["ok"]


def test_tampered_batch_receipt_is_rejected_before_provider_observation(setup_batch):
    fixture = setup_batch
    store = fixture.prepare()
    receipt_path = store.directory / "runtime.json"
    receipt = _json(receipt_path)
    receipt["entries"]["first"]["active_lease"] = True
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ConfigError):
        _run(fixture, store)
    assert fixture.provider.roots == {} and fixture.provider.calls == []


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--runner":
        raise SystemExit("Internal offline test runner only")
    _controller(Path(sys.argv[2]))
