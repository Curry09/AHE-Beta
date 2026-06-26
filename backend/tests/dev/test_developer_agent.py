"""spec-0003/T3：DeveloperAgent 单测（mock nexau + FakeTracker + 临时 git 仓）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_designer.dev.developer_agent import DeveloperAgent
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker

_BASE_CONTENT = "v0 主 agent 定义\n"


class _FakeAgent:
    def __init__(self, output: str) -> None:
        self._output = output

    def run(self, prompt: str) -> str:
        return self._output


def _make_harness_repo(tmp_path: Path) -> str:
    repo = tmp_path / "harness"
    (repo / "agents").mkdir(parents=True)
    (repo / "agents" / "main.md").write_text(_BASE_CONTENT, encoding="utf-8")

    def run(*a: str) -> None:
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    run("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed")
    run("branch", "release")
    return str(repo)


def _branches(repo: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "branch", "--format=%(refname:short)"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return out.split()


def test_bug_issue_creates_fix_branch_and_commit(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="崩了", body="详情", labels=["bug"]))
    dev = DeveloperAgent(tracker, repo, _FakeAgent("修复后的内容\n"))
    result = dev.work_one()
    assert result.changed is True
    assert result.branch == "fix/issue-1"
    assert result.commit is not None
    assert "fix/issue-1" in _branches(repo)
    assert (Path(repo) / "agents" / "main.md").read_text(encoding="utf-8") == "修复后的内容\n"
    assert any("fix/issue-1" in c for c in tracker.issue(1)["comments"])


def test_feature_issue_creates_feat_branch(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="加个功能", body="x", labels=["feature"]))
    result = DeveloperAgent(tracker, repo, _FakeAgent("增强后的内容\n")).work_one()
    assert result.branch == "feat/issue-1" and result.changed is True
    assert "feat/issue-1" in _branches(repo)


def test_no_open_issue_returns_empty(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    result = DeveloperAgent(FakeTracker(), repo, _FakeAgent("x")).work_one()
    assert result == result.__class__()  # 全空 DevResult
    assert not any(b.startswith(("fix/", "feat/")) for b in _branches(repo))


def test_on_status_emits_claim_and_commit(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="崩了", body="详情", labels=["bug"]))
    events: list = []

    def on_status(*, running, status, issue_number=None, branch=None, detail=None):
        events.append((running, status, branch))

    DeveloperAgent(tracker, repo, _FakeAgent("修复后的内容\n"), on_status=on_status).work_one()
    # 至少有「领取」和「已提交」两个状态，且收尾 running=False
    assert any("领取 issue #1" in s for _, s, _ in events)
    assert any(not r and "已提交 fix/issue-1" in s for r, s, _ in events)


def test_skip_picks_next_issue(tmp_path) -> None:
    # 同轮多 dev：传入 skip 跳过已认领 issue，领下一条。
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="第一条", body="a", labels=["bug"]))
    tracker.create_issue(IssueDraft(title="第二条", body="b", labels=["bug"]))
    result = DeveloperAgent(tracker, repo, _FakeAgent("改了\n")).work_one(skip={1})
    assert result.issue_number == 2 and result.branch == "fix/issue-2"


def test_no_change_no_commit(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    result = DeveloperAgent(tracker, repo, _FakeAgent(_BASE_CONTENT)).work_one()  # 原样返回
    assert result.changed is False
    assert result.commit is None
    assert any("未产出改动" in c for c in tracker.issue(1)["comments"])


def test_default_routing_when_no_label(tmp_path) -> None:
    repo = _make_harness_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="无标签", body="b"))
    result = DeveloperAgent(tracker, repo, _FakeAgent("改了\n")).work_one()
    assert result.branch == "fix/issue-1" and result.default_routed is True
    assert any("默认" in c for c in tracker.issue(1)["comments"])
