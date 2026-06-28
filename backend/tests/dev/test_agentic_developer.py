# Spec-0005/T1：AgenticDeveloper 直推 main 单测（mock nexau agent + 临时 git 仓 fixture）。
"""验证开发者侧纯 trunk 流程：

- 直推 main 后仓内**无新分支**（仅 main）、有新 commit + 新 vK tag；
- 仓状态（新 tag）为 ground truth → DevOutcome.committed 为真、issue 被 close；
- 无可领 open issue → 返回空 DevOutcome、不跑 agent。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_designer.dev.agentic_developer import AgenticDeveloper, DevOutcome
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _seed_repo(tmp_path: Path) -> Path:
    """种一个只有 main 的本地 harness 仓（无 release，对齐 trunk 模型）。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "agents").mkdir()
    (repo / "agents" / "main.md").write_text("v0 prompt\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed: harness v0")
    return repo


class _DirectPushDev(AgenticDeveloper):
    """覆盖 _run_agent：用真 git 模拟 nexau agent 的「checkout main → 改 → commit → tag」直推流程。

    不创建任何分支、不 merge、不 push（临时仓无 origin），其余全走真实父类逻辑。
    """

    def _run_agent(self, *, issue_number: int, title: str, body: str, tag: str) -> str:
        _git(self._repo, "checkout", "main")
        (self._repo / "agents" / "main.md").write_text(
            f"v0 prompt\n# fix #{issue_number}: {title}\n", encoding="utf-8"
        )
        _git(self._repo, "add", "-A")
        _git(self._repo, "commit", "-m", f"fix: issue #{issue_number}")
        _git(self._repo, "tag", tag)
        return f"done {tag}"


def test_direct_push_main_no_branch_new_commit_tag(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    tracker = FakeTracker()
    ref = tracker.create_issue(IssueDraft(title="慢查询", body="优化 ORM", labels=["bug"]))

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "agent_def"))
    outcome = dev.work_one()

    # 直推 main：commit 落在 main 上，main HEAD 前进
    assert _git(repo, "rev-parse", "main") != head_before
    # 仓内无新分支：只剩 main 一条线（无 fix/issue-* / release）
    branches = _git(repo, "branch", "--format=%(refname:short)").split()
    assert branches == ["main"]
    # 新 vK tag 出现 = ground truth
    assert "v1" in _git(repo, "tag").split()
    assert outcome == DevOutcome(issue_number=ref.number, tag="v1", committed=True)
    # 新 tag → issue 被 close
    assert tracker.issue(ref.number)["state"] == "closed"


def test_no_open_issue_returns_empty_outcome(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()  # 无任何 issue

    calls: list = []

    class _NoAgent(AgenticDeveloper):
        def _run_agent(self, **kw):  # 不应被调用
            calls.append(kw)
            return ""

    outcome = _NoAgent(tracker, str(repo), str(tmp_path / "agent_def")).work_one()
    assert outcome == DevOutcome()  # 空：无 issue_number / tag / committed=False
    assert calls == []  # 无可领 issue 时不跑 agent


def test_skip_excludes_assigned_issue(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    first = tracker.create_issue(IssueDraft(title="a", body="", labels=[]))
    second = tracker.create_issue(IssueDraft(title="b", body="", labels=[]))

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "agent_def"))
    outcome = dev.work_one(skip={first.number})  # 跳过第一条 → 领第二条
    assert outcome.issue_number == second.number
    assert outcome.committed is True


def test_no_new_tag_means_not_committed(tmp_path) -> None:
    """agent 没打出新 tag（改了文件但没走完 git）→ committed=False、issue 不 close。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    ref = tracker.create_issue(IssueDraft(title="x", body="", labels=[]))

    class _NoTagDev(AgenticDeveloper):
        def _run_agent(self, *, issue_number, title, body, tag):
            (self._repo / "agents" / "main.md").write_text("touched\n", encoding="utf-8")
            return "改了但没提交没打 tag"

    outcome = _NoTagDev(tracker, str(repo), str(tmp_path / "agent_def")).work_one()
    assert outcome.committed is False and outcome.tag is None
    assert tracker.issue(ref.number)["state"] == "open"  # 未推进 → 不 close
