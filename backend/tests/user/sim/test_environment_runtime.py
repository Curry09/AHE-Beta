"""Spec-0081/T3: no-Git runtime and source attempt binding."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_designer.experiment.task_environments.contract import (
    container_environment,
    environment_identity,
)
from auto_designer.experiment.task_environments.docker import (
    ContainerTaskRuntime,
    TaskEnvironmentError,
)
from auto_designer.loop.sim_user import _export_prediction
from auto_designer.models import WorkspaceSpec
from auto_designer.usage import bind_usage_context
from auto_designer.user.sim.runtime import (
    capture_review_snapshot,
    list_review_files,
    read_bounded_file,
)
from auto_designer.user.sim.sources.container import ContainerSource


def runtime():
    manager = SimpleNamespace(
        environment={"workdir": "/app", "patch": "not_applicable"},
        key="key",
        record_path=Path("/registry/key.json"),
        harness_python="/tools/python",
        identity={"recipe_hash": "a" * 64},
    )
    record = {
        "resources": {
            "containers": {
                "task": {"id": "owned", "name": "task", "image": "image", "image_id": "digest"}
            }
        },
        "phase": "frozen",
    }
    return ContainerTaskRuntime(manager=manager, record=record)


def test_no_git_task_has_no_fake_prediction_or_git_review(monkeypatch, tmp_path):
    workspace = runtime()
    calls = []

    def read_only_listing(argv, *, timeout):
        calls.append(argv)
        assert argv[0] == "/tools/python" and timeout == 10
        assert "list_review_files" in argv[2]
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"returncode": 0, "stdout": "", "clipped": False})
        )

    monkeypatch.setattr(workspace, "_exec", read_only_listing)
    workspace.freeze_patch_base()
    assert workspace.export_patch() == ("", "")
    evidence = {"prediction": {"old": "receipt"}, "prediction_error": {"old": "failure"}}
    patch = _export_prediction(
        workspace=workspace,
        store=SimpleNamespace(root=tmp_path),
        session_id="session",
        evidence=evidence,
    )
    assert patch == ("", "") and evidence["prediction_status"] == "not_applicable"
    assert "prediction" not in evidence and "prediction_error" not in evidence
    assert list(tmp_path.iterdir()) == []
    snapshot = capture_review_snapshot(workspace, files={"report.txt": b"original"})
    assert snapshot.read_text("report.txt") == "original"
    assert snapshot.evidence["omissions"] == []
    assert len(calls) == 1  # No Git, patch creation, or model-selected command.


def test_no_git_container_review_captures_source_with_readonly_python(monkeypatch, tmp_path):
    workspace = runtime()
    workspace.cwd = str(tmp_path)
    source = tmp_path / "generated_app"
    source.mkdir()
    (source / "main.js").write_text("module.exports = 42;\n")
    (source / "external").symlink_to("/etc/passwd")
    (source / "node_modules").mkdir()
    (source / "node_modules/dependency.js").write_text("not a source preview\n")

    def execute_fixed_reader(argv, *, timeout):
        assert argv[0] == "/tools/python" and argv[1] == "-c"
        return subprocess.run(
            [sys.executable, *argv[1:]], capture_output=True, text=True, timeout=timeout
        )

    monkeypatch.setattr(workspace, "_exec", execute_fixed_reader)
    monkeypatch.setattr(
        workspace,
        "export_file",
        lambda path, max_bytes: read_bounded_file(str(tmp_path), path, max_bytes),
    )
    snapshot = capture_review_snapshot(workspace)
    assert snapshot.read_text("generated_app/main.js") == "module.exports = 42;\n"
    assert "generated_app/external" not in snapshot.list_files()
    assert "generated_app/node_modules/dependency.js" not in snapshot.list_files()
    assert not snapshot.evidence["omissions"]


def test_non_git_preview_is_bounded_and_rejects_linked_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    for index in range(270):
        (root / f"file-{index:03}.txt").write_text("source\n")
    result = list_review_files(root=str(root), max_output=20000)
    assert result["clipped"] and len(result["stdout"].split("\0")) <= 257
    link = tmp_path / "alias"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="Linked review"):
        list_review_files(root=str(link), max_output=20000)


def params():
    package = {
        "schema_version": 3,
        "environment": {
            "kind": "container",
            "image": "example.org/image@sha256:" + "a" * 64,
            "workdir": "/app",
            "inputs": [],
            "services": [],
            "readiness": {"argv": ["true"], "timeout_seconds": 2},
        },
    }
    return {
        "environment": container_environment(package),
        "recipe_hash": environment_identity(package),
        "run_id": "run",
        "config_hash": "b" * 64,
        "task_id": "task",
        "task_digest": "c" * 64,
        "registry_root": "/registry",
        "harness_python": "/tools/python",
        "harness_mounts": [],
        "session_id": "untrusted-caller-session",
        "round_no": 100,
        "slot": 999,
        "attempt": 900,
    }


def test_source_uses_current_bound_attempt_not_caller_supplied_ids(monkeypatch):
    seen = {}

    class Manager:
        def __init__(self, **values):
            seen.update(values)

        def open(self):
            return "owned-runtime"

    monkeypatch.setattr(
        "auto_designer.experiment.task_environments.docker.DockerTaskEnvironmentManager", Manager
    )
    with bind_usage_context(
        run_id="run",
        task_id="task",
        task_digest="c" * 64,
        session_id="real-session",
        round_no=3,
        slot=2,
        attempt=4,
    ):
        assert (
            ContainerSource().provision(WorkspaceSpec(kind="container", params=params()))
            == "owned-runtime"
        )
    assert seen["identity"]["session_id"] == "real-session"
    assert (
        seen["identity"]["round_no"],
        seen["identity"]["slot"],
        seen["identity"]["attempt"],
    ) == (3, 2, 4)


def test_source_rejects_usage_task_mismatch_before_provision():
    with bind_usage_context(run_id="run", task_id="other-task", task_digest="c" * 64):
        with pytest.raises(TaskEnvironmentError, match="binding differs"):
            ContainerSource().provision(WorkspaceSpec(kind="container", params=params()))


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
def test_completed_actor_capture_retry_never_reexecutes_actor_or_publishes_infra_feedback(
    tmp_path, monkeypatch, mode
):
    from auto_designer.loop.sim_user import (
        EnvironmentInfrastructureError,
        make_mixed_run_session_fn,
    )
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.harness_adapter import ScriptedHarness
    from auto_designer.user.sim.persona_client import ScriptedPersonaClient
    from auto_designer.user.sim.run_live import expert

    context = dict(
        run_id="run",
        session_id="session",
        round_no=1,
        slot=0,
        persona_id="P-0991",
        task_id="task",
        task_digest="c" * 64,
        task_kind="benchmark",
        interaction_mode=mode,
        harness_sha="d" * 40,
        attempt=1,
    )
    identity = {
        key: context[key]
        for key in ("run_id", "session_id", "round_no", "slot", "task_id", "task_digest", "attempt")
    }
    identity.update(config_hash="b" * 64, recipe_hash="e" * 64)
    binding = {
        "kind": "container",
        "registry_root": str(tmp_path / "registry"),
        "environment_key": "f" * 64,
        "identity": identity,
    }

    class Environment:
        cwd = "/task"

        def __init__(self):
            self.evidence = {"patch_capability": "not_applicable"}
            self.copy_failed = False
            self.exports = 0
            self.finalizations = 0
            self.sealed = False

        def collection_binding(self):
            return binding

        def freeze_patch_base(self):
            pass

        def export_patch(self):
            return "", ""

        def review_file_listing(self):
            return {"returncode": 0, "stdout": ""}

        def quiesce(self):
            pass

        def finalize_task(self):
            if not self.sealed:
                self.sealed = True
                self.finalizations += 1

        def export_file(self, path, max_bytes):
            self.exports += 1
            if not self.copy_failed:
                self.copy_failed = True
                raise OSError("temporary transport failure")
            return b"original completed Actor output"

        def close(self):
            pass

    environment = Environment()
    actor_messages, reviews = [], []

    class Harness(ScriptedHarness):
        def send(self, message):
            actor_messages.append(message)
            return super().send(message)

    class SimClient(ScriptedPersonaClient):
        def respond(self, system, user):
            reviews.append(user)
            return super().respond(system, user)

    class DirectClient:
        def respond(self, system, user):
            reviews.append(user)
            return {
                "verdict": "file_issue",
                "task_assessment": "unfulfilled",
                "score": 2,
                "reason": "task gap",
                "issue": "A real task issue",
            }

    persona = expert()
    context["persona_id"] = persona.persona_id
    model_persona = Persona(persona.persona_id, "expert", "software", "task", "concise")
    config = {
        key: identity[key]
        for key in ("run_id", "config_hash", "task_id", "task_digest", "recipe_hash")
    }
    scenario = SeedScenario(
        "run task",
        WorkspaceSpec(
            kind="container",
            params={
                **config,
                "registry_root": binding["registry_root"],
                "interaction": mode,
                "task_kind": "benchmark",
                "evaluation_artifacts": [
                    {
                        "id": "report",
                        "source": "workspace",
                        "path": "report",
                        "required": True,
                        "max_bytes": 1024,
                        "content_type": "text/plain",
                    }
                ],
            },
        ),
    )
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "data/sessions")
    run = make_mixed_run_session_fn(
        client_factory=DirectClient if mode == "direct" else SimClient,
        tracker=tracker,
        store=store,
        sim_personas={persona.persona_id: persona},
    )
    adopted, released = [], []

    def adopt(*, binding, expected_provenance):
        adopted.append(binding)
        assert binding["identity"]["attempt"] == 1
        return environment

    monkeypatch.setattr(
        "auto_designer.experiment.task_environments.docker.resume_collection", adopt
    )
    monkeypatch.setattr(
        "auto_designer.experiment.task_environments.docker.release_collection",
        lambda **values: released.append(values),
    )
    with bind_usage_context(**context):
        with pytest.raises(EnvironmentInfrastructureError, match="artifact transport"):
            run(model_persona, scenario, Harness(), workspace_dir=environment)
    assert store.reconcile("session") is None and store.index() == []
    assert tracker.list_open_issues() == []
    assert store.load_actor_checkpoint("session") is not None
    assert not any("<file_issue>" in prompt or "<rate_experience>" in prompt for prompt in reviews)
    if mode == "direct":
        assert reviews == []
    before_messages = list(actor_messages)
    before_main_reviews = sum("<main_" in prompt for prompt in reviews)
    with bind_usage_context(**{**context, "attempt": 2}):
        session = run.load_completed_session("session")
    assert session.session_id == "session"
    assert actor_messages == before_messages
    assert sum("<main_" in prompt for prompt in reviews) == before_main_reviews
    assert len(adopted) == len(released) == 1
    assert environment.finalizations == 1
    assert session.workspace_evidence["evaluation_artifacts"]["entries"][0]["status"] == "collected"
    assert tracker.list_open_issues()


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
def test_crash_after_observation_publish_and_source_cleanup_reuses_verified_bundle(
    tmp_path, monkeypatch, mode
):
    import json
    import shutil

    from auto_designer.loop.sim_user import make_mixed_run_session_fn
    from auto_designer.models import Persona, SeedScenario
    from auto_designer.observations.publication import ObservationSource
    from auto_designer.tracker.fake import FakeTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.harness_adapter import ScriptedHarness
    from auto_designer.user.sim.persona_client import ScriptedPersonaClient
    from auto_designer.user.sim.run_live import expert

    sp = expert()
    context = dict(
        run_id="run",
        session_id="session",
        round_no=1,
        slot=0,
        persona_id=sp.persona_id,
        task_id="task",
        task_digest="c" * 64,
        task_kind="benchmark",
        interaction_mode=mode,
        harness_sha="d" * 40,
        attempt=1,
    )
    identity = {
        key: context[key]
        for key in ("run_id", "session_id", "round_no", "slot", "task_id", "task_digest", "attempt")
    }
    identity.update(config_hash="b" * 64, recipe_hash="e" * 64)
    binding = {
        "kind": "container",
        "registry_root": str(tmp_path / "registry"),
        "environment_key": "f" * 64,
        "identity": identity,
    }

    class Environment:
        cwd = "/task"
        evidence = {"patch_capability": "not_applicable"}

        def collection_binding(self):
            return binding

        def freeze_patch_base(self):
            pass

        def export_patch(self):
            return "", ""

        def review_file_listing(self):
            return {"returncode": 0, "stdout": ""}

        def quiesce(self):
            pass

        def finalize_task(self):
            pass

        def close(self):
            pass

    producer = tmp_path / "producer"
    producer.mkdir()
    (producer / "READING.md").write_text("Original immutable observations")
    (producer / "manifest.json").write_text(
        json.dumps(
            {"status": "complete", "reading": "READING.md", "files": [{"path": "READING.md"}]}
        )
    )
    collect_count = []
    original_collect = ObservationSource.collect

    def collect(self, **values):
        collect_count.append(self.run_id)
        return original_collect(self, **values)

    monkeypatch.setattr(ObservationSource, "collect", collect)
    released = []

    def release(**values):
        released.append(values)
        shutil.rmtree(producer, ignore_errors=True)

    monkeypatch.setattr(
        "auto_designer.experiment.task_environments.docker.release_collection", release
    )
    monkeypatch.setattr(
        "auto_designer.experiment.task_environments.docker.resume_collection",
        lambda **values: (_ for _ in ()).throw(
            AssertionError("frozen capture must not touch resources")
        ),
    )
    crashed = []

    def crash_once():
        if not crashed:
            crashed.append(True)
            assert released and not producer.exists()
            raise KeyboardInterrupt("crash after source cleanup, before terminal review")

    class SimClient(ScriptedPersonaClient):
        def respond(self, system, user):
            if "<file_issue>" in user or "<rate_experience>" in user:
                crash_once()
            return super().respond(system, user)

    class DirectClient:
        def respond(self, system, user):
            crash_once()
            return {"score": 3, "reason": "reviewed", "feedback": "reviewed"}

    params = {
        key: identity[key]
        for key in ("run_id", "config_hash", "task_id", "task_digest", "recipe_hash")
    }
    scenario = SeedScenario(
        "run task",
        WorkspaceSpec(
            kind="container",
            params={
                **params,
                "registry_root": binding["registry_root"],
                "interaction": mode,
                "task_kind": "benchmark",
            },
        ),
    )
    store = SessionStore(tmp_path / "data/sessions")
    tracker = FakeTracker()
    run = make_mixed_run_session_fn(
        client_factory=DirectClient if mode == "direct" else SimClient,
        tracker=tracker,
        store=store,
        sim_personas={sp.persona_id: sp},
    )
    harness = ScriptedHarness()
    harness.observation_source = ObservationSource(
        directory=str(producer), container_id=None, version={"harness_sha": context["harness_sha"]}
    )
    with bind_usage_context(**context):
        with pytest.raises(KeyboardInterrupt):
            run(
                Persona(sp.persona_id, "expert", "software", "task", "concise"),
                scenario,
                harness,
                workspace_dir=Environment(),
            )
    assert store.reconcile("session") is None
    assert store.load_actor_capture("session") is not None
    assert tracker.list_open_issues() == []
    with bind_usage_context(**{**context, "attempt": 2}):
        session = run.load_completed_session("session")
    assert session.workspace_evidence["observation"]["status"] == "complete"
    assert len(collect_count) == 1


def test_conversational_scratch_has_explicit_no_git_and_bounded_safe_review(tmp_path):
    from auto_designer.user.sim.runtime import make_empty_runtime

    workspace = make_empty_runtime()
    try:
        workspace.write_text("result.txt", "conversation output")
        outside = tmp_path / "private.txt"
        outside.write_text("outside secret")
        (Path(workspace.cwd) / "outside-link").symlink_to(outside)
        (Path(workspace.cwd) / "directory-link").symlink_to(tmp_path, target_is_directory=True)
        workspace.freeze_patch_base()
        assert workspace.export_patch() == ("", "")
        assert workspace.evidence["patch_status"] == "not_applicable"
        evidence = {}
        assert _export_prediction(
            workspace=workspace,
            store=SimpleNamespace(root=tmp_path / "sessions"),
            session_id="scratch",
            evidence=evidence,
        ) == ("", "")
        assert evidence["prediction_status"] == "not_applicable"
        assert "prediction" not in evidence and "prediction_error" not in evidence
        snapshot = capture_review_snapshot(workspace)
        assert snapshot.list_files() == ["result.txt"]
        assert snapshot.read_text("result.txt") == "conversation output"
        assert snapshot.evidence["omissions"] == []
        assert not (Path(workspace.cwd) / ".git").exists()
        assert not (tmp_path / "predictions").exists()
    finally:
        workspace.close()


def test_collection_recovery_registry_rejects_sources_without_frozen_capability():
    from auto_designer.user.sim.seed_source import release_collection, resume_collection

    for operation in (release_collection, resume_collection):
        with pytest.raises(ValueError, match="collection"):
            operation(
                binding={"kind": "local-fixture"},
                expected_provenance={},
                spec=WorkspaceSpec(kind="local-fixture"),
            )


def test_fixture_source_preserves_real_git_metadata_and_local_path_api(tmp_path, monkeypatch):
    import os
    import subprocess

    from auto_designer.user.sim import seed_source

    fixtures = tmp_path / "fixtures"
    project = fixtures / "tracked/project"
    project.mkdir(parents=True)
    (project / "source.txt").write_text("baseline\n")
    for argv in (
        ["git", "init", "-q", str(project)],
        ["git", "-C", str(project), "add", "source.txt"],
        [
            "git",
            "-C",
            str(project),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
    ):
        subprocess.run(argv, check=True, capture_output=True)
    monkeypatch.setattr(
        "auto_designer.user.sim.sources.local_fixture.seed_workspaces_root", lambda: fixtures
    )
    runtime = seed_source.provision(WorkspaceSpec(fixture="tracked"))
    try:
        assert runtime.evidence["patch_capability"] == "git"
        assert os.fspath(runtime) == runtime.cwd == str(runtime)
        assert Path(runtime).is_dir()
        runtime.freeze_patch_base()
        runtime.write_text("source.txt", "changed\n")
        patch, digest = runtime.export_patch()
        assert "+changed" in patch and digest
        assert (project / "source.txt").read_text() == "baseline\n"
    finally:
        runtime.close()
