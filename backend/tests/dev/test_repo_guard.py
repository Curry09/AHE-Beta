# Spec-0021/T1：编排仓完整性绊线单测——快照/校验对提交、改 tracked、新 untracked 各分支。
"""verify_unchanged 应放行「未变」，对新增 commit / 改 tracked / 新 untracked 抛 RepoIntegrityError，
既有 untracked 前后都在时不误报；git 读失败也抛（宁紧勿松）。用 symbolic-ref 建仓兼容 git <2.28。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_designer.dev.repo_guard import (
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
    verify_unchanged(repo=str(repo), before=before)  # 不抛即通过


def test_new_commit_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "commit", "-am", "dev 偷偷提交")
    with pytest.raises(RepoIntegrityError, match="新提交"):
        verify_unchanged(repo=str(repo), before=before)


def test_modified_tracked_file_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "tracked.txt").write_text("被改\n", encoding="utf-8")  # 改了不提交
    with pytest.raises(RepoIntegrityError, match="新增改动"):
        verify_unchanged(repo=str(repo), before=before)


def test_new_untracked_file_detected(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    before = snapshot_repo(repo=str(repo))
    (repo / "escape.md").write_text("harness 内容写进 def\n", encoding="utf-8")
    with pytest.raises(RepoIntegrityError):
        verify_unchanged(repo=str(repo), before=before)


def test_preexisting_untracked_not_flagged(tmp_path) -> None:
    """既有 untracked（如本地 docs / .idea）在前后快照都在 → 不误报。"""
    repo = _seed_repo(tmp_path)
    (repo / "local-note.md").write_text("我早就在这\n", encoding="utf-8")  # run 前就存在
    before = snapshot_repo(repo=str(repo))
    verify_unchanged(repo=str(repo), before=before)  # 同一个 untracked 仍在 → 不抛


def test_git_read_failure_raises(tmp_path) -> None:
    """非 git 仓 → snapshot 抛 RepoIntegrityError（宁紧勿松，不放过）。"""
    with pytest.raises(RepoIntegrityError):
        snapshot_repo(repo=str(tmp_path / "not-a-repo"))
