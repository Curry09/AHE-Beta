"""spec-0003/T5：release 发版单测（临时 git 仓 + FakeTracker）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_designer.dev.release import release
from auto_designer.dev.test_agent import Verdict
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker


def _git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True,
    ).stdout


def _repo(tmp_path: Path) -> str:
    repo = tmp_path / "harness"
    repo.mkdir()
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "base")
    _git(str(repo), "branch", "release")
    return str(repo)


def _candidate(repo: str, name: str, content: str) -> None:
    _git(repo, "checkout", "-b", name, "release")
    (Path(repo) / "f.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", f"change on {name}")
    _git(repo, "checkout", "release")


def _verdict(passed: bool) -> Verdict:
    return Verdict(passed=passed, mean=3.0 if passed else 1.0, baseline=2.0, n=1, per_session=[3])


def _tags(repo: str) -> list[str]:
    return _git(repo, "tag", "--list").split()


def test_pass_merges_and_tags_v1(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "improved\n")
    result = release(repo, "fix/issue-1", _verdict(True), None, None)
    assert result.released is True and result.tag == "v1"
    assert "v1" in _tags(repo)
    assert (Path(repo) / "f.txt").read_text(encoding="utf-8") == "improved\n"  # 已合入 release


def test_fail_does_not_touch_release(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "improved\n")
    head_before = _git(repo, "rev-parse", "HEAD").strip()
    result = release(repo, "fix/issue-1", _verdict(False), None, None)
    assert result.released is False and result.tag is None
    assert _tags(repo) == []
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before


def test_pass_closes_issue(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "improved\n")
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    release(repo, "fix/issue-1", _verdict(True), tracker, 1)
    assert tracker.issue(1)["state"] == "closed"


def test_fail_comments_rejection(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "improved\n")
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b"))
    release(repo, "fix/issue-1", _verdict(False), tracker, 1)
    assert any("门禁未过" in c for c in tracker.issue(1)["comments"])
    assert tracker.issue(1)["state"] == "open"  # 未关闭


def test_missing_candidate_raises(tmp_path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(RuntimeError):
        release(repo, "no-such-branch", _verdict(True), None, None)


def test_merge_conflict_raises_and_keeps_release(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "A\n")
    # release 自身也改同一行 → 与候选冲突
    (Path(repo) / "f.txt").write_text("B\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "diverge on release")
    head_before = _git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(RuntimeError):
        release(repo, "fix/issue-1", _verdict(True), None, None)
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before  # release 原状
    assert _tags(repo) == []


def test_second_release_increments_version(tmp_path) -> None:
    repo = _repo(tmp_path)
    _candidate(repo, "fix/issue-1", "one\n")
    release(repo, "fix/issue-1", _verdict(True), None, None)  # v1
    _candidate(repo, "fix/issue-2", "two\n")
    result = release(repo, "fix/issue-2", _verdict(True), None, None)
    assert result.tag == "v2" and set(_tags(repo)) == {"v1", "v2"}
