# spec-0002/T3 + Spec-0007/T4: bootstrap_harness unit test, mock Gitea API + temporary git (no network, no real git execution).
"""Spec-0007/T4: Pure trunk—assert only main created, no release branch, and ensure default branch is main (PATCH repo config)."""

from __future__ import annotations

from pathlib import Path

import requests

from bootstrap_harness import HARNESS_REPO, bootstrap_harness


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeSession:
    """Route by URL and return fixed status code; can set connection exceptions. Record POST/PATCH calls for assertion."""

    def __init__(
        self, repo_status: int, default_status: int, raise_exc: Exception | None = None
    ) -> None:
        self._repo_status = repo_status
        self._default_status = default_status
        self._raise = raise_exc
        self.calls: list[tuple[str, str, dict]] = []  # (method, url, json)

    def post(self, url: str, json: dict) -> _Resp:
        if self._raise is not None:
            raise self._raise
        self.calls.append(("POST", url, json))
        if url.endswith("/user/repos"):
            return _Resp(self._repo_status)
        raise AssertionError(f"unexpected POST url {url}")

    def patch(self, url: str, json: dict) -> _Resp:
        if self._raise is not None:
            raise self._raise
        self.calls.append(("PATCH", url, json))
        if url.endswith(f"/repos/o/{HARNESS_REPO}"):
            return _Resp(self._default_status)
        raise AssertionError(f"unexpected PATCH url {url}")


class _GitRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, args: list[str], cwd: str) -> None:
        self.calls.append((args, cwd))


def _repo_root_with_template(tmp_path: Path) -> Path:
    (tmp_path / "harness_template").mkdir()
    (tmp_path / "harness_template" / "entry.py").write_text("print('v0')\n", encoding="utf-8")
    return tmp_path


def _run(session: _FakeSession, git: _GitRecorder, repo_root: Path) -> int:
    return bootstrap_harness(
        session=session,
        run_git=git,
        repo_root=repo_root,
        gitea_url="http://gitea:3000",
        owner="o",
        token="T",
        harness_repo=HARNESS_REPO,
    )


def test_create_pushes_seed_main_only_no_release(tmp_path) -> None:
    session = _FakeSession(repo_status=201, default_status=200)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 0
    # Repo creation hits /user/repos and parameters contain harness repo name
    repo_call = [c for c in session.calls if c[1].endswith("/user/repos")][0]
    assert repo_call[2]["name"] == HARNESS_REPO
    # Seed initial commit into single line and push to main
    git_args = [a for a, _ in git.calls]
    assert ["init", "-b", "main"] in git_args
    assert any(a[:2] == ["push", "-u"] and a[-1] == "HEAD:main" for a in git_args)
    # Pure trunk: do not create any release branch (no /branches calls)
    assert not any(c[1].endswith("/branches") for c in session.calls)
    # Default branch set to main via PATCH
    patch_call = [c for c in session.calls if c[0] == "PATCH"][0]
    assert patch_call[2] == {"default_branch": "main"}


def test_idempotent_existing_repo_skips_push_still_sets_default(tmp_path) -> None:
    session = _FakeSession(repo_status=409, default_status=200)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 0
    # Repo already exists → do not force push overwrite (preserve evolution history)
    assert git.calls == []
    # Still ensure default branch is main and do not create release
    assert any(c[0] == "PATCH" and c[2] == {"default_branch": "main"} for c in session.calls)
    assert not any(c[1].endswith("/branches") for c in session.calls)


def test_auth_failure_returns_nonzero_no_push(tmp_path) -> None:
    session = _FakeSession(repo_status=401, default_status=200)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 1
    assert git.calls == []
    # Repo creation failed → return early, do not set default branch
    assert not any(c[0] == "PATCH" for c in session.calls)


def test_default_branch_failure_returns_nonzero(tmp_path) -> None:
    session = _FakeSession(repo_status=201, default_status=500)
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 1  # Setting default branch failed → non-zero exit


def test_connection_error_returns_nonzero(tmp_path) -> None:
    session = _FakeSession(
        repo_status=201, default_status=200, raise_exc=requests.ConnectionError("down")
    )
    git = _GitRecorder()
    rc = _run(session, git, _repo_root_with_template(tmp_path))
    assert rc == 1
    assert git.calls == []


def test_missing_template_returns_2_no_remote_write(tmp_path) -> None:
    session = _FakeSession(repo_status=201, default_status=200)
    git = _GitRecorder()
    rc = _run(session, git, tmp_path)  # No harness_template
    assert rc == 2
    assert session.calls == []  # Pre-flight check failed, do not initiate any remote write
    assert git.calls == []


def test_empty_template_returns_2(tmp_path) -> None:
    (tmp_path / "harness_template").mkdir()  # Exists but empty
    session = _FakeSession(repo_status=201, default_status=200)
    rc = _run(session, _GitRecorder(), tmp_path)
    assert rc == 2
    assert session.calls == []
