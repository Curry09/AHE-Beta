# Spec-0029/T7：AgenticDeveloper——ready 白名单领取、priority→票龄排序、只关自己（无级联）。
"""验证开发者侧（三平面模型）：

- 可领集合 = **白名单** is_ready（proposal/report 不可领；旧 triaged/RFC 数据经映射仍可领）；
- 排序 priority（P0 插队）→ 票号（同级 FIFO）；每 work_one 领一条、carryover；skip 防撞；
- 预算按档（from-synthesize/旧 RFC 最高档）；
- 推进 main（新 vK tag）后关票 + 回写报告；**不再级联关闭 covers**（级联已前移至 Owner 准入）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_designer.designer import issue_schema as sc
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
    """覆盖 _run_agent：用真 git 模拟 agent 的 checkout→改→commit→tag 直推；记录 budget。"""

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


def _ready(tracker: FakeTracker, title: str, *, kind: str = "bug", prio: str | None = None) -> int:
    labels = [kind, sc.READY]
    if prio:
        labels.append(prio)
    return tracker.create_issue(IssueDraft(title=title, body="x", labels=labels)).number


def _dev(tracker, repo, tmp_path, cls=_DirectPushDev, **kw):
    return cls(tracker, str(repo), str(tmp_path / "agent_def"), **kw)


# ---- 领取：白名单 ready、priority→票号、carryover ----


def test_direct_push_ready_issue(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    head_before = _git(repo, "rev-parse", "main")
    tracker = FakeTracker()
    n = _ready(tracker, "慢查询")

    outcome = _dev(tracker, repo, tmp_path).work_one()

    assert _git(repo, "rev-parse", "main") != head_before  # 直推 main、HEAD 前进
    assert "v1" in _git(repo, "tag").split()
    assert outcome == DevOutcome(issue_number=n, tag="v1", committed=True)
    assert tracker.issue(n)["state"] == "closed"


def test_whitelist_excludes_report_and_proposal(tmp_path) -> None:
    """白名单：report/proposal（含结构/产品提案）都不可领——只有 ready。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="raw report", body="x", labels=["bug", sc.REPORT]))
    tracker.create_issue(
        IssueDraft(title="待准入提案", body="x", labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE])
    )
    tracker.create_issue(
        IssueDraft(title="结构提案", body="x", labels=[sc.PROPOSAL, sc.FROM_SYNTHESIZE])
    )
    ok = _ready(tracker, "可领")

    outcome = _dev(tracker, repo, tmp_path).work_one()
    assert outcome.issue_number == ok


def test_whitelist_accepts_old_triaged_and_rfc_labels(tmp_path) -> None:
    """旧数据（triaged / RFC 标签）经 plane 映射仍可领（读侧兼容）。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    old = tracker.create_issue(
        IssueDraft(title="旧 triaged", body="x", labels=["bug", sc.TRIAGED])
    ).number
    outcome = _dev(tracker, repo, tmp_path).work_one()
    assert outcome.issue_number == old


def test_no_eligible_returns_empty(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="raw", body="x", labels=["bug", sc.REPORT]))
    calls: list = []

    class _NoAgent(AgenticDeveloper):
        def _run_agent(self, **kw):
            calls.append(kw)
            return ""

    out = _dev(tracker, repo, tmp_path, cls=_NoAgent).work_one()
    assert out == DevOutcome() and calls == []  # 无可领 → 不跑 agent


def test_priority_jumps_queue_then_fifo(tmp_path) -> None:
    """排序：P0 插队（哪怕票号更大）；同优先级按票号 FIFO。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _ready(tracker, "无优先级老票")
    p2 = _ready(tracker, "P2 票", prio="P2")
    p0 = _ready(tracker, "P0 急修", prio="P0")

    dev = _dev(tracker, repo, tmp_path)
    assert dev.work_one().issue_number == p0  # P0 插队
    assert _dev(tracker, repo, tmp_path).work_one().issue_number == p2  # 次之 P2


def test_same_priority_fifo_and_carryover(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    first = _ready(tracker, "老")
    second = _ready(tracker, "新")

    dev = _dev(tracker, repo, tmp_path)
    assert dev.work_one().issue_number == first  # 同级 FIFO
    assert tracker.issue(second)["state"] == "open"  # carryover
    assert _dev(tracker, repo, tmp_path).work_one().issue_number == second


def test_skip_prevents_collision(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    a = _ready(tracker, "a")
    b = _ready(tracker, "b")
    dev = _dev(tracker, repo, tmp_path)
    out = dev.work_one(skip={a})  # 模拟 dev#1 已领 a
    assert out.issue_number == b


# ---- 预算按档（结构提案最高），无重试升档 ----


def test_budget_by_kind_and_provenance(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _ready(tracker, "bug票", kind="bug")
    dev = _dev(tracker, repo, tmp_path, budgets={"bug": 60, "feature": 70, "rfc": 100})
    dev.work_one()
    assert dev.budgets == [60]

    tracker2 = FakeTracker()
    tracker2.create_issue(
        IssueDraft(title="结构提案已准入", body="s", labels=[sc.READY, sc.FROM_SYNTHESIZE])
    )
    dev2 = _dev(tracker2, repo, tmp_path, budgets={"bug": 60, "rfc": 100})
    dev2.work_one()
    assert dev2.budgets == [100]  # from-synthesize 最高档

    tracker3 = FakeTracker()
    tracker3.create_issue(IssueDraft(title="旧RFC票", body="s", labels=[sc.RFC_LABEL]))
    dev3 = _dev(tracker3, repo, tmp_path, budgets={"bug": 60, "rfc": 100})
    dev3.work_one()
    assert dev3.budgets == [100]  # 旧 RFC 标签同档


def test_default_budgets_when_not_given(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _ready(tracker, "feature票", kind="feature")
    dev = _dev(tracker, repo, tmp_path)  # 用 DEFAULT_BUDGETS
    dev.work_one()
    assert dev.budgets == [120]  # feature 默认 120


# ---- 收尾：回写 + 只关自己 ----


def test_success_writes_report_comment(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _ready(tracker, "会成功")
    _dev(tracker, repo, tmp_path).work_one()
    assert "done v1" in tracker.issue(n)["comments"]


def test_no_tag_not_committed_and_stays_open(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _ready(tracker, "会失败")
    out = _dev(tracker, repo, tmp_path, cls=_NoTagDev).work_one()
    assert out.committed is False and out.tag is None
    assert tracker.issue(n)["state"] == "open"  # 未推进 → 仍 open（下轮再领）
    assert any(c.startswith("[dev] 本轮未推进") for c in tracker.issue(n)["comments"])


def test_done_does_not_cascade_covers(tmp_path) -> None:
    """Spec-0029/T7：dev 只关自己的票——covers 级联已前移至 Owner 准入，dev 侧零级联。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    other = _ready(tracker, "另一条独立 ready")
    s = tracker.create_issue(
        IssueDraft(
            title="结构提案已准入",
            body=f"### 问题\n\nx\n\ncovers: #{other}",
            labels=[sc.READY, sc.FROM_SYNTHESIZE, "P0"],
        )
    ).number
    out = _dev(tracker, repo, tmp_path).work_one()
    assert out.issue_number == s and out.committed is True  # P0 先领
    assert tracker.issue(s)["state"] == "closed"  # 关自己
    assert tracker.issue(other)["state"] == "open"  # covers 的票不动（级联不在 dev）
