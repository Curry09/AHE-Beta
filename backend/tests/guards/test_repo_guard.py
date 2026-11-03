# Spec-0021/T1: orchestration repository integrity tripwire unit test—snapshot/checksum for commits, tracked modifications, new untracked files across branches.
"""verify_unchanged should allow "unchanged"; throw RepoIntegrityError for new commits / modified tracked / new untracked,
no false positive when pre-existing untracked files exist before and after; throw on git read failure too (fail closed). Use symbolic-ref for repository compatibility with git <2.28.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ahe_beta.guards.repo_guard import (
    RepoIntegrityError,
    snapshot_repo,
    verify_unchanged,
)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "tracked.txt").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


def test_unchanged_passes(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    verify_unchanged(repo=str(repo), before=before)  # Passing = no exception raised


def test_new_commit_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "commit", "-am", "dev Submit covertly")
    with pytest.raises(RepoIntegrityError, match="new commit"):
        verify_unchanged(repo=str(repo), before=before)


def test_modified_tracked_file_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "tracked.txt").write_text("Modified\n", encoding="utf-8")  # Modified but not committed
    with pytest.raises(RepoIntegrityError, match="New working tree changes"):
        verify_unchanged(repo=str(repo), before=before)


def test_new_untracked_file_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "escape.md").write_text("harness Write content into def\n", encoding="utf-8")
    with pytest.raises(RepoIntegrityError):
        verify_unchanged(repo=str(repo), before=before)


def test_preexisting_untracked_not_flagged(tmp_path) -> None:
    """Pre-existing untracked files (e.g., local docs / .idea) present in both pre and post snapshots → no false positive."""
    repo = _seed_repo(tmp_path)
    (repo / "local-note.md").write_text(
        "I was already here\n", encoding="utf-8"
    )  # Existed before run
    before = snapshot_repo(repo=str(repo))
    # Same untracked file still present → do not throw
    verify_unchanged(repo=str(repo), before=before)


def test_git_read_failure_raises(tmp_path) -> None:
    """Non-git repository → snapshot throws RepoIntegrityError (fail closed, do not pass)."""
    with pytest.raises(RepoIntegrityError):
        snapshot_repo(repo=str(tmp_path / "not-a-repo"))
