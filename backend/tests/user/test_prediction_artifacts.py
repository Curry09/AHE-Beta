"""Spec-0075/T1: actual session runners preserve immutable complete predictions."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ahe_beta.loop.sim_user import (
    EnvironmentInfrastructureError,
    make_direct_run_session_fn,
    make_sim_run_session_fn,
)
from ahe_beta.models import Persona, SeedScenario
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.patches import PredictionArtifactError, preserve_prediction
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.run_live import expert
from ahe_beta.user.sim.runtime import DockerWorkspaceRuntime, LocalWorkspaceRuntime


class _ReviewClient:
    model = "offline-review"

    def __init__(self) -> None:
        self.prompt = ""

    def respond(self, system: str, user: str) -> dict:
        self.prompt = user
        return {"verdict": "accept", "feedback": "reviewed", "score": 3, "reason": "reviewed"}


class _EditingHarness(ScriptedHarness):
    def __init__(self, repo: Path, content: str) -> None:
        super().__init__()
        self.repo = repo
        self.content = content

    def send(self, message: str) -> str:
        (self.repo / "tracked.txt").write_text(self.content, encoding="utf-8")
        return super().send(message)


class _ObservedWorkspace(LocalWorkspaceRuntime):
    def __init__(self, root: str, prediction_path: Path) -> None:
        super().__init__(root)
        self.prediction_path = prediction_path

    def close(self) -> None:
        assert self.prediction_path.is_file()
        super().close()


class _CheckingStore(SessionStore):
    def save(self, session) -> None:
        receipt = session.workspace_evidence["prediction"]
        assert (self.root.parent / receipt["path"]).is_file()
        super().save(session)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "seed",
    )
    return repo


def _runner(mode: str, store: SessionStore, review: _ReviewClient):
    sp = expert()
    persona = Persona(sp.persona_id, "expert", "software", "task", "concise")
    options = {"tracker": FakeTracker(), "store": store, "sim_personas": {sp.persona_id: sp}}
    if mode == "direct":
        run = make_direct_run_session_fn(client_factory=lambda: review, **options)
    else:
        run = make_sim_run_session_fn(client_factory=ScriptedPersonaClient, **options)
    return run, persona


@pytest.mark.parametrize("mode", ["direct", "simulated"])
@pytest.mark.parametrize("long_patch", [False, True])
def test_actual_runners_persist_complete_patch_before_save_and_close(
    tmp_path: Path, mode: str, long_patch: bool
) -> None:
    repo = _repository(tmp_path)
    sid = f"stable-{mode}"
    store = _CheckingStore(tmp_path / "data" / "sessions")
    review = _ReviewClient()
    run, persona = _runner(mode, store, review)
    content = "用户修改\n" * 5000 + "complete-tail\n" if long_patch else "baseline\n"
    prediction_path = store.root.parent / "predictions" / f"{sid}.patch"
    workspace = _ObservedWorkspace(str(repo), prediction_path)
    with bind_usage_context(session_id=sid, round_no=1):
        session = run(
            persona,
            SeedScenario("fix the task"),
            _EditingHarness(repo, content),
            workspace_dir=workspace,
        )
        loaded = run.load_completed_session(sid)
    expected = _git(repo, "diff", "--binary", "--no-ext-diff").encode("utf-8")
    receipt = session.workspace_evidence["prediction"]
    assert receipt == {
        "contract_version": 1,
        "session_id": sid,
        "path": f"predictions/{sid}.patch",
        "sha256": hashlib.sha256(expected).hexdigest(),
        "bytes": len(expected),
    }
    assert prediction_path.read_bytes() == expected
    assert loaded.workspace_evidence["prediction"] == receipt
    assert store.load(sid).workspace_evidence["prediction"] == receipt
    assert str(tmp_path) not in json.dumps(receipt)
    if long_patch:
        assert len(expected.decode("utf-8")) > 12_000
        assert b"complete-tail" in expected
        if mode == "direct":
            assert "complete-tail" not in review.prompt
    else:
        assert expected == b""


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_real_git_export_failure_is_not_an_empty_prediction(tmp_path: Path, mode: str) -> None:
    repo = tmp_path / "not-a-repository"
    repo.mkdir()
    store = SessionStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())
    sid = f"failed-{mode}"
    with bind_usage_context(session_id=sid):
        with pytest.raises(EnvironmentInfrastructureError, match="patch preservation"):
            run(
                persona,
                SeedScenario("task"),
                ScriptedHarness(),
                workspace_dir=LocalWorkspaceRuntime(str(repo)),
            )
    assert store.load_actor_checkpoint(sid) is not None
    assert store.reconcile(sid) is None and store.index() == []
    failure = json.loads(
        next((store.root / "actor-checkpoints" / f"{sid}.failures").glob("*.json")).read_text()
    )
    assert failure["evidence"]["prediction_error"]["status"] == "export_failed"
    assert not (store.root.parent / "predictions").exists()


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_preservation_conflict_saves_failure_without_overwriting_prediction(
    tmp_path: Path, mode: str
) -> None:
    repo = _repository(tmp_path)
    store = SessionStore(tmp_path / "data" / "sessions")
    sid = f"conflict-{mode}"
    preserve_prediction(
        sessions_root=store.root,
        session_id=sid,
        patch="previous",
        patch_sha256=hashlib.sha256(b"previous").hexdigest(),
    )
    path = store.root.parent / "predictions" / f"{sid}.patch"
    before = path.stat().st_mtime_ns
    run, persona = _runner(mode, store, _ReviewClient())
    with bind_usage_context(session_id=sid):
        with pytest.raises(EnvironmentInfrastructureError, match="patch preservation"):
            run(
                persona,
                SeedScenario("task"),
                ScriptedHarness(),
                workspace_dir=LocalWorkspaceRuntime(str(repo)),
            )
    assert store.reconcile(sid) is None
    assert store.load_actor_checkpoint(sid) is not None
    assert path.read_bytes() == b"previous"
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize("sid", ["", ".", "..", "../escape", "/escape", "a/b", "a\\b", "a\x00b"])
def test_prediction_rejects_unsafe_session_ids(tmp_path: Path, sid: str) -> None:
    with pytest.raises(PredictionArtifactError, match="unsafe"):
        preserve_prediction(
            sessions_root=tmp_path / "sessions",
            session_id=sid,
            patch="",
            patch_sha256=hashlib.sha256(b"").hexdigest(),
        )
    assert not (tmp_path / "predictions").exists()


@pytest.mark.parametrize("link_level", ["ancestor", "directory", "target"])
def test_prediction_rejects_symlinks_without_touching_outside_files(
    tmp_path: Path, link_level: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = outside / "original"
    payload.write_bytes(b"untouched")
    data = tmp_path / "data"
    if link_level == "ancestor":
        data.symlink_to(outside, target_is_directory=True)
    else:
        data.mkdir()
        if link_level == "directory":
            (data / "predictions").symlink_to(outside, target_is_directory=True)
        else:
            (data / "predictions").mkdir()
            (data / "predictions" / "stable.patch").symlink_to(payload)
    with pytest.raises((OSError, PredictionArtifactError)):
        preserve_prediction(
            sessions_root=data / "sessions",
            session_id="stable",
            patch="new",
            patch_sha256=hashlib.sha256(b"new").hexdigest(),
        )
    assert payload.read_bytes() == b"untouched"
    assert sorted(path.name for path in outside.iterdir()) == ["original"]
    if link_level == "target":
        assert not list((data / "predictions").glob(".*.tmp"))


def test_prediction_reuse_is_immutable_and_concurrent_conflict_is_atomic(tmp_path: Path) -> None:
    def write(patch: str):
        try:
            return preserve_prediction(
                sessions_root=tmp_path / "sessions",
                session_id="stable",
                patch=patch,
                patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
            )
        except PredictionArtifactError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, ["one", "two"]))
    assert sum(result is not None for result in outcomes) == 1
    path = tmp_path / "predictions" / "stable.patch"
    before = path.stat().st_mtime_ns
    original = path.read_text()
    assert write(original) is not None
    assert path.stat().st_mtime_ns == before
    assert not list(path.parent.glob(".*.tmp"))


def test_prediction_digest_mismatch_is_not_preserved(tmp_path: Path) -> None:
    with pytest.raises(PredictionArtifactError, match="digest mismatch"):
        preserve_prediction(
            sessions_root=tmp_path / "sessions",
            session_id="stable",
            patch="not empty",
            patch_sha256=hashlib.sha256(b"").hexdigest(),
        )
    assert not (tmp_path / "predictions").exists()


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_missing_workspace_is_marked_unavailable(tmp_path: Path, mode: str) -> None:
    store = SessionStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())
    session = run(persona, SeedScenario("task"), ScriptedHarness())
    assert "prediction" not in session.workspace_evidence
    assert session.workspace_evidence["prediction_error"] == {
        "status": "unavailable",
        "reason": "no_workspace",
    }
    assert not (store.root.parent / "predictions").exists()


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_write_failure_does_not_fabricate_receipt_and_retains_session(
    tmp_path: Path, mode: str, monkeypatch
) -> None:
    repo = _repository(tmp_path)
    store = SessionStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())

    def fail(**kwargs):
        raise OSError("private-host-path: disk full")

    monkeypatch.setattr("ahe_beta.loop.sim_user.preserve_prediction", fail)
    sid = f"write-failure-{mode}"
    with bind_usage_context(session_id=sid):
        with pytest.raises(EnvironmentInfrastructureError, match="patch preservation"):
            run(
                persona,
                SeedScenario("task"),
                ScriptedHarness(),
                workspace_dir=LocalWorkspaceRuntime(str(repo)),
            )
    assert store.reconcile(sid) is None and store.index() == []
    assert store.load_actor_checkpoint(sid) is not None
    failure = json.loads(
        next((store.root / "actor-checkpoints" / f"{sid}.failures").glob("*.json")).read_text()
    )
    assert failure["evidence"]["prediction_error"] == {
        "status": "preservation_failed",
        "error_type": "OSError",
    }
    assert "private-host-path" not in json.dumps(failure["evidence"]["prediction_error"])


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_retry_after_session_save_crash_reuses_original_prediction(
    tmp_path: Path, mode: str
) -> None:
    repo = _repository(tmp_path)
    sid = f"retry-{mode}"

    class CrashOnceStore(SessionStore):
        crashed = False

        def save(self, session) -> None:
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("crash before session publication")
            super().save(session)

    store = CrashOnceStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())
    content = "完整补丁\n" * 5000
    with bind_usage_context(session_id=sid):
        with pytest.raises(RuntimeError, match="crash before"):
            run(
                persona,
                SeedScenario("task"),
                _EditingHarness(repo, content),
                workspace_dir=LocalWorkspaceRuntime(str(repo)),
            )
        path = store.root.parent / "predictions" / f"{sid}.patch"
        original = path.read_bytes()
        original_mtime = path.stat().st_mtime_ns
        session = run(
            persona,
            SeedScenario("task"),
            _EditingHarness(repo, content),
            workspace_dir=LocalWorkspaceRuntime(str(repo)),
        )
        restored = run.load_completed_session(sid)
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == original_mtime
    assert session.workspace_evidence["prediction"] == restored.workspace_evidence["prediction"]


class _CommittingHarness(ScriptedHarness):
    def __init__(self, repo: Path) -> None:
        super().__init__()
        self.repo = repo
        self.index_before_export = b""

    def send(self, message: str) -> str:
        if not self.index_before_export:
            (self.repo / "tracked.txt").write_text("Harness committed change\n")
            _git(self.repo, "add", "tracked.txt")
            _git(
                self.repo,
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "Harness-created commit",
            )
            (self.repo / "staged.txt").write_text("staged change\n")
            _git(self.repo, "add", "staged.txt")
            (self.repo / "untracked.txt").write_text("new unstaged file\n")
            (self.repo / ".gitignore").write_text("ignored.txt\n")
            (self.repo / "ignored.txt").write_text("must not become a prediction\n")
            self.index_before_export = (self.repo / ".git" / "index").read_bytes()
        return super().send(message)


class _ContainerExecutionBoundary(DockerWorkspaceRuntime):
    """Run the production container command script on Git, without a Docker daemon."""

    def _exec(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=self.cwd, capture_output=True, text=True)

    def quiesce(self) -> None:
        # This double exercises Git export commands on the host. ScriptedHarness
        # writes synchronously and starts no processes. Never run the production
        # container-wide /proc cleanup outside its disposable container boundary.
        self._ensure_live()

    def close(self) -> None:
        self.evidence["closed_at"] = "offline-container-boundary"
        self._closed = True


@pytest.mark.parametrize("mode", ["direct", "simulated"])
@pytest.mark.parametrize("backend", ["local", "container-command"])
def test_prediction_captures_commits_staged_and_new_files_against_original_base(
    tmp_path: Path, mode: str, backend: str
) -> None:
    repo = _repository(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").strip()
    store = SessionStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())
    workspace = (
        LocalWorkspaceRuntime(str(repo))
        if backend == "local"
        else _ContainerExecutionBoundary(
            container_id="offline",
            container_name="offline",
            image="offline",
            image_digest="offline",
            cwd=str(repo),
        )
    )
    harness = _CommittingHarness(repo)
    session = run(persona, SeedScenario("task"), harness, workspace_dir=workspace)
    assert session.workspace_evidence["actor_freeze"]["status"] == "frozen"
    assert _git(repo, "rev-parse", "HEAD").strip() != base
    assert session.workspace_evidence["diff_base_commit"] == base
    assert (repo / ".git" / "index").read_bytes() == harness.index_before_export
    patch_path = store.root.parent / session.workspace_evidence["prediction"]["path"]
    patch = patch_path.read_text()
    assert "Harness committed change" in patch
    assert "staged change" in patch
    assert "new unstaged file" in patch
    assert "must not become a prediction" not in patch
    # Freeze is idempotent after Harness-created commits: never move the baseline.
    workspace.freeze_patch_base()
    assert workspace.evidence["diff_base_commit"] == base
    fresh = tmp_path / "fresh"
    _git(tmp_path, "clone", "-q", str(repo), str(fresh))
    _git(fresh, "reset", "--hard", base)
    _git(fresh, "apply", str(patch_path))
    assert (fresh / "tracked.txt").read_text() == "Harness committed change\n"
    assert (fresh / "staged.txt").read_text() == "staged change\n"
    assert (fresh / "untracked.txt").read_text() == "new unstaged file\n"
    assert not (fresh / "ignored.txt").exists()


def test_failed_base_capture_cannot_be_replaced_by_a_later_git_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = LocalWorkspaceRuntime(str(repo))
    with pytest.raises(RuntimeError):
        workspace.freeze_patch_base()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("late baseline\n")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "late",
    )
    with pytest.raises(RuntimeError, match="original patch base"):
        workspace.freeze_patch_base()
    with pytest.raises(RuntimeError, match="original patch base"):
        workspace.export_patch()
    assert "diff_base_commit" not in workspace.evidence
    assert workspace.evidence["diff_base_error"] == "RuntimeError"


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("backend", ["local", "container-command"])
def test_prediction_bypasses_textconv_that_hides_real_file_changes(
    tmp_path: Path, frozen: bool, backend: str
) -> None:
    repo = _repository(tmp_path)
    (repo / ".gitattributes").write_text("tracked.txt diff=constant\n")
    _git(repo, "add", ".gitattributes")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "text conversion attribute",
    )
    _git(repo, "config", "diff.constant.textconv", "sh -c 'printf stable'")
    base = _git(repo, "rev-parse", "HEAD").strip()
    workspace = (
        LocalWorkspaceRuntime(str(repo))
        if backend == "local"
        else _ContainerExecutionBoundary(
            container_id="offline",
            container_name="offline",
            image="offline",
            image_digest="offline",
            cwd=str(repo),
        )
    )
    if frozen:
        workspace.freeze_patch_base()
    (repo / "tracked.txt").write_text("real changed bytes\n")
    # The configured driver converts both old/new versions to the same display:
    # exporting that view would manufacture an empty prediction.
    assert _git(repo, "diff", "--textconv") == ""
    patch, digest = workspace.export_patch()
    assert "real changed bytes" in patch
    assert hashlib.sha256(patch.encode()).hexdigest() == digest
    patch_path = tmp_path / "actual.patch"
    patch_path.write_text(patch)
    fresh = tmp_path / "fresh"
    _git(tmp_path, "clone", "-q", str(repo), str(fresh))
    _git(fresh, "reset", "--hard", base)
    _git(fresh, "apply", str(patch_path))
    assert (fresh / "tracked.txt").read_text() == "real changed bytes\n"


class _RuntimeArtifactHarness(ScriptedHarness):
    def __init__(self, repo: Path) -> None:
        super().__init__()
        self.repo = repo
        self.index_before_export = (repo / ".git" / "index").read_bytes()

    def send(self, message: str) -> str:
        artifacts = {
            ".venv/bin/python": "runtime interpreter",
            "nested/.venv/bin/python": "nested interpreter",
            "__pycache__/module.pyc": "runtime bytecode",
            "nested/__pycache__/module.pyc": "nested bytecode",
            "orphan.pyc": "runtime cache",
            "orphan.pyo": "optimized cache",
            "orphan.pyd": "binary extension",
        }
        for name, content in artifacts.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.repo / "new.py").write_text("def answer():\n    return 42\n")
        (self.repo / "tracked.txt").write_text("real source change\n")
        return super().send(message)


@pytest.mark.parametrize("mode", ["direct", "simulated"])
@pytest.mark.parametrize("backend", ["local", "container-command"])
def test_prediction_excludes_generated_runtime_even_without_gitignore(
    tmp_path: Path, mode: str, backend: str
) -> None:
    repo = _repository(tmp_path)
    assert not (repo / ".gitignore").exists()
    _git(repo, "config", "core.excludesFile", "/dev/null")
    base = _git(repo, "rev-parse", "HEAD").strip()
    store = SessionStore(tmp_path / "data" / "sessions")
    run, persona = _runner(mode, store, _ReviewClient())
    workspace = (
        LocalWorkspaceRuntime(str(repo))
        if backend == "local"
        else _ContainerExecutionBoundary(
            container_id="offline",
            container_name="offline",
            image="offline",
            image_digest="offline",
            cwd=str(repo),
        )
    )
    harness = _RuntimeArtifactHarness(repo)
    session = run(persona, SeedScenario("task"), harness, workspace_dir=workspace)
    assert session.workspace_evidence["actor_freeze"]["status"] == "frozen"
    assert (repo / ".git" / "index").read_bytes() == harness.index_before_export
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    assert ".venv/bin/python" in untracked
    assert "__pycache__/module.pyc" in untracked
    patch_path = store.root.parent / session.workspace_evidence["prediction"]["path"]
    patch = patch_path.read_text()
    assert "real source change" in patch
    assert "def answer():" in patch
    assert ".venv" not in patch
    assert "__pycache__" not in patch
    assert "orphan.py" not in patch
    assert not (repo / ".gitignore").exists()
    fresh = tmp_path / "fresh"
    _git(tmp_path, "clone", "-q", str(repo), str(fresh))
    _git(fresh, "reset", "--hard", base)
    _git(fresh, "apply", str(patch_path))
    assert (fresh / "new.py").read_text() == "def answer():\n    return 42\n"
    assert (fresh / "tracked.txt").read_text() == "real source change\n"
    assert not (fresh / ".venv").exists()
    assert not (fresh / "__pycache__").exists()


@pytest.mark.parametrize("mode", ["direct", "simulated"])
def test_actor_breaking_git_is_task_artifact_failure_and_does_not_block_feedback(tmp_path, mode):
    import shutil

    repo = _repository(tmp_path)
    store = SessionStore(tmp_path / "data/sessions")
    run, persona = _runner(mode, store, _ReviewClient())

    class BrokenGitHarness(ScriptedHarness):
        def send(self, message):
            shutil.rmtree(repo / ".git", ignore_errors=True)
            return super().send(message)

    session = run(
        persona,
        SeedScenario("task"),
        BrokenGitHarness(),
        workspace_dir=LocalWorkspaceRuntime(str(repo)),
    )
    assert session.workspace_evidence["prediction_error"]["status"] == "invalid_task_artifact"
    assert "prediction" not in session.workspace_evidence
    assert session.workspace_evidence["review_snapshot"]["omissions"] == ["invalid_git_artifact"]
    assert store.load(session.session_id).session_id == session.session_id
