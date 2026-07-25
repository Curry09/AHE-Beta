# Spec-0025/T5：AgenticDeveloper 简化——领 triaged/RFC、按容量积压、预算按 kind、去分池/retry/stuck。
"""验证开发者侧（配合 triage 漏斗）：

- 只领**可领集合**（triaged 或 RFC 标签；排除 needs-triage/superseded）；按票号升序取最老一条；
- 每 work_one 领一条，超容量的未领 issue 保持 open（carryover）；skip 防多 dev 撞同一条；
- 预算按 kind 分档（bug/feature/RFC，RFC 最高）；无重试升档；
- 推进 main（新 vK tag）后关票 + 回写报告；带 covers 行（RFC）连带关闭其覆盖的 triaged issue；
- 无分池/attempt/stuck 相关行为。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_designer.designer.issue_schema import NEEDS_TRIAGE, RFC_LABEL, SUPERSEDED, TRIAGED
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
    """种一个只有 main 的本地 harness 仓（symbolic-ref 设首分支名，新旧 git 通吃）。"""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "agents").mkdir()
    (repo / "agents" / "main.md").write_text("v0 prompt\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed: harness v0")
    return repo


class _DirectPushDev(AgenticDeveloper):
    """覆盖 _run_agent：用真 git 模拟 agent 的 checkout→改→commit→tag 直推；记录 budget 与领到的 issue。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.budgets: list[int] = []

    def _run_agent(self, *, issue_number: int, title: str, body: str, tag: str, budget: int) -> str:
        self.budgets.append(budget)
        _git(self._repo, "checkout", "main")
        (self._repo / "agents" / "main.md").write_text(
            f"v0 prompt\n# fix #{issue_number}: {title}\n", encoding="utf-8"
        )
        _git(self._repo, "add", "-A")
        _git(self._repo, "commit", "-m", f"fix: issue #{issue_number}")
        _git(self._repo, "tag", tag)
        return f"done {tag}"


class _NoTagDev(AgenticDeveloper):
    """覆盖 _run_agent：只改文件、不 commit 不 tag——模拟失败收场。"""

    def _run_agent(self, *, issue_number, title, body, tag, budget):
        (self._repo / "agents" / "main.md").write_text("touched\n", encoding="utf-8")
        return "改了但没提交没打 tag"


def _triaged(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(IssueDraft(title=title, body="x", labels=[kind, TRIAGED])).number


def _dev(tracker, repo, tmp_path, cls=_DirectPushDev, **kw):
    return cls(tracker, str(repo), str(tmp_path / "agent_def"), **kw)


# ---- 领取：只领 triaged/RFC、按票号升序、carryover ----


def test_direct_push_triaged_issue(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    tracker = FakeTracker()
    n = _triaged(tracker, "慢查询")

    outcome = _dev(tracker, repo, tmp_path).work_one()

    assert _git(repo, "rev-parse", "main") != head_before  # 直推 main、HEAD 前进
    assert _git(repo, "branch", "--format=%(refname:short)").split() == ["main"]  # 无新分支
    assert "v1" in _git(repo, "tag").split()
    assert outcome == DevOutcome(issue_number=n, tag="v1", committed=True)
    assert tracker.issue(n)["state"] == "closed"


def test_eligible_excludes_needs_triage_and_superseded(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="待分诊", body="x", labels=["bug", NEEDS_TRIAGE]))
    tracker.create_issue(IssueDraft(title="被取代", body="x", labels=["bug", TRIAGED, SUPERSEDED]))
    ok = _triaged(tracker, "可领")

    outcome = _dev(tracker, repo, tmp_path).work_one()
    assert outcome.issue_number == ok  # 只领 triaged 且非 superseded 那条


def test_no_eligible_returns_empty(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="raw", body="x", labels=["bug", NEEDS_TRIAGE]))
    calls: list = []

    class _NoAgent(AgenticDeveloper):
        def _run_agent(self, **kw):
            calls.append(kw)
            return ""

    out = _dev(tracker, repo, tmp_path, cls=_NoAgent).work_one()
    assert out == DevOutcome() and calls == []  # 无可领 → 不跑 agent


def test_picks_oldest_by_number_and_carryover(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    first = _triaged(tracker, "老")
    second = _triaged(tracker, "新")

    dev = _dev(tracker, repo, tmp_path)
    assert dev.work_one().issue_number == first  # 升序取最老
    # 超容量：一次只领一条，第二条仍 open（carryover 到下轮）
    assert tracker.issue(second)["state"] == "open"
    # 下一轮（新 dev）领到积压的第二条
    assert _dev(tracker, repo, tmp_path).work_one().issue_number == second


def test_skip_prevents_collision(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    a = _triaged(tracker, "a")
    b = _triaged(tracker, "b")
    dev = _dev(tracker, repo, tmp_path)
    out = dev.work_one(skip={a})  # 模拟 dev#1 已领 a
    assert out.issue_number == b


# ---- 预算按 kind 分档（RFC 最高），无重试升档 ----


def test_budget_by_kind(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _triaged(tracker, "bug票", kind="bug")
    dev = _dev(tracker, repo, tmp_path, budgets={"bug": 60, "feature": 70, "rfc": 100})
    dev.work_one()
    assert dev.budgets == [60]

    tracker2 = FakeTracker()
    tracker2.create_issue(IssueDraft(title="RFC票", body="s", labels=[RFC_LABEL]))
    dev2 = _dev(tracker2, repo, tmp_path, budgets={"bug": 60, "rfc": 100})
    dev2.work_one()
    assert dev2.budgets == [100]  # RFC 最高档


def test_default_budgets_when_not_given(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _triaged(tracker, "feature票", kind="feature")
    dev = _dev(tracker, repo, tmp_path)  # 用 DEFAULT_BUDGETS
    dev.work_one()
    assert dev.budgets == [120]  # feature 默认 120


# ---- 收尾：回写 + 连带关闭 ----


def test_success_writes_report_comment(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _triaged(tracker, "会成功")
    _dev(tracker, repo, tmp_path).work_one()
    assert "done v1" in tracker.issue(n)["comments"]


def test_no_tag_not_committed_and_stays_open(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _triaged(tracker, "会失败")
    out = _dev(tracker, repo, tmp_path, cls=_NoTagDev).work_one()
    assert out.committed is False and out.tag is None
    assert tracker.issue(n)["state"] == "open"  # 未推进 → 仍 open（下轮再领，无 stuck）
    assert any(c.startswith("[dev] 本轮未推进") for c in tracker.issue(n)["comments"])


def test_rfc_covers_closes_triaged(tmp_path) -> None:
    """RFC 推进 main → 连带关闭它 covers 的 triaged issue（一级）。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    t1 = _triaged(tracker, "被综合甲")
    t2 = _triaged(tracker, "被综合乙")
    closed_early = _triaged(tracker, "早已关")
    tracker.set_state(closed_early, "closed", "手动")
    # RFC 号最小 → 会被先领；它 covers t1/t2/closed_early/999
    rfc = tracker.create_issue(
        IssueDraft(
            title="RFC",
            body=f"综合\n\ncovers: #{t1} #{t2} #{closed_early} #999",
            labels=[RFC_LABEL],
        )
    ).number
    # 让 RFC 先被领（票号升序，RFC 是最后建的 → 手动 skip 掉前面的 triaged，只留 RFC 可领）
    dev = _dev(tracker, repo, tmp_path)
    out = dev.work_one(skip={t1, t2})
    assert out.issue_number == rfc and out.committed is True
    for n in (t1, t2):
        assert tracker.issue(n)["state"] == "closed"
        assert f"covered by #{rfc}" in tracker.issue(n)["reason"]
    assert tracker.issue(closed_early)["reason"] == "手动"  # 已关的不重复动
