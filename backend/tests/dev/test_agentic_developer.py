# Spec-0007/T1：AgenticDeveloper 直推 main 单测（mock nexau agent + 临时 git 仓 fixture）。
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
    """种一个只有 main 的本地 harness 仓（无 release，对齐 trunk 模型）。

    不用 `git init -b main`（git <2.28 无 -b），改 symbolic-ref 设首分支名，新旧 git 通吃。
    """
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
    """覆盖 _run_agent：用真 git 模拟 nexau agent 的「checkout main → 改 → commit → tag」直推流程。

    不创建任何分支、不 merge、不 push（临时仓无 origin），其余全走真实父类逻辑。
    记录每次收到的 budget，供票种预算/升档断言。
    """

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


class _NoTagDev(AgenticDeveloper):
    """覆盖 _run_agent：只改文件、不 commit 不 tag——模拟失败收场。"""

    def _run_agent(self, *, issue_number, title, body, tag, budget):
        (self._repo / "agents" / "main.md").write_text("touched\n", encoding="utf-8")
        return "改了但没提交没打 tag"


def test_no_new_tag_means_not_committed(tmp_path) -> None:
    """agent 没打出新 tag（改了文件但没走完 git）→ committed=False、issue 不 close。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    ref = tracker.create_issue(IssueDraft(title="x", body="", labels=[]))

    outcome = _NoTagDev(tracker, str(repo), str(tmp_path / "agent_def")).work_one()
    assert outcome.committed is False and outcome.tag is None
    assert tracker.issue(ref.number)["state"] == "open"  # 未推进 → 不 close


# ---- Spec-0020/T2：分池领取 / covered·stuck 沉底 / 票种预算与升档 / 回写与连带关闭 ----


def _bug(tracker: FakeTracker, title: str) -> int:
    return tracker.create_issue(IssueDraft(title=title, body="", labels=["bug"])).number


def _design(tracker: FakeTracker, title: str, body: str = "") -> int:
    return tracker.create_issue(IssueDraft(title=title, body=body, labels=["design"])).number


def test_design_first_picks_oldest_design_over_bugs(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    _bug(tracker, "bug先来")
    d1 = _design(tracker, "设计一")
    _design(tracker, "设计二")

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="design_first")
    assert dev.work_one().issue_number == d1  # bug 满池仍先领最老 design 票


def test_bug_first_picks_oldest_bug_and_falls_back_to_design(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    d = _design(tracker, "设计")
    b = _bug(tracker, "bug")

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="bug_first")
    assert dev.work_one().issue_number == b  # bug 优先
    dev2 = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="bug_first")
    assert dev2.work_one().issue_number == d  # bug 池空 → 回落 design 池


def test_design_first_falls_back_to_bug_when_no_design(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    b = _bug(tracker, "只有bug")
    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="design_first")
    assert dev.work_one().issue_number == b


def test_covered_bug_sinks_but_still_pickable_when_alone(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    covered = _bug(tracker, "被覆盖")
    fresh = _bug(tracker, "未覆盖")
    _design(tracker, "整合", body=f"根因整合\n\ncovers: #{covered}")

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="bug_first")
    assert dev.work_one().issue_number == fresh  # covered 沉底：新票号更大仍先被领

    # 池内只剩 covered bug（design 票被上一步…没关；这里单独构造只含 covered 的场景）
    tracker2 = FakeTracker()
    only = _bug(tracker2, "唯一且被覆盖")
    _design(tracker2, "整合", body=f"covers: #{only}")
    dev2 = _DirectPushDev(tracker2, str(repo), str(tmp_path / "a"), pick_policy="bug_first")
    assert dev2.work_one().issue_number == only  # 仍可领：覆盖是降权不是排除


def test_budget_by_label_and_escalation_once(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    b = _bug(tracker, "bug票")
    d = _design(tracker, "design票")

    dev = _DirectPushDev(
        tracker, str(repo), str(tmp_path / "a"),
        pick_policy="bug_first", budget_bug=38, budget_design=60,
    )
    dev.work_one()  # 领 bug
    dev.work_one()  # 领 design
    assert dev.budgets == [38, 60]

    # 带 1 条 attempt 记录 → 升档 ×1.5 取整（38→57）
    tracker2 = FakeTracker()
    retry = _bug(tracker2, "重试票")
    tracker2.add_comment(retry, "[dev-attempt] 本轮未推进 main：超时")
    dev2 = _DirectPushDev(
        tracker2, str(repo), str(tmp_path / "a"), pick_policy="bug_first", budget_bug=38
    )
    dev2.work_one()
    assert dev2.budgets == [57]
    assert b != d  # silence unused


def test_stuck_issue_sinks_globally_but_picked_when_pool_empty(tmp_path) -> None:
    """attempt ≥2 = stuck：有别的票就绝不领它（即使它是策略池唯一票）；全空才兜底领、预算=升档值。"""
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    stuck_design = _design(tracker, "修不动的设计票")
    for _ in range(2):
        tracker.add_comment(stuck_design, "[dev-attempt] 本轮未推进 main：撞满迭代")
    fresh_bug = _bug(tracker, "新bug")

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="design_first")
    assert dev.work_one().issue_number == fresh_bug  # design_first 也跳过 stuck design、回落 bug

    # 只剩 stuck 票：兜底可领，预算=升档值（60×1.5=90），不再复利
    tracker2 = FakeTracker()
    only_stuck = _design(tracker2, "唯一stuck")
    for _ in range(3):
        tracker2.add_comment(only_stuck, "[dev-attempt] 又失败")
    dev2 = _DirectPushDev(
        tracker2, str(repo), str(tmp_path / "a"), pick_policy="design_first", budget_design=60
    )
    assert dev2.work_one().issue_number == only_stuck
    assert dev2.budgets == [90]


def test_success_writes_report_comment(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _bug(tracker, "会成功")
    _DirectPushDev(tracker, str(repo), str(tmp_path / "a")).work_one()
    assert "done v1" in tracker.issue(n)["comments"]  # 报告全文回写


def test_failure_writes_attempt_marker(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    n = _bug(tracker, "会失败")
    _NoTagDev(tracker, str(repo), str(tmp_path / "a")).work_one()
    comments = tracker.issue(n)["comments"]
    assert len(comments) == 1 and comments[0].startswith("[dev-attempt]")
    assert tracker.issue(n)["state"] == "open"


def test_committed_design_closes_covered_open_bugs(tmp_path) -> None:
    repo = _seed_repo(tmp_path)
    tracker = FakeTracker()
    b1 = _bug(tracker, "被覆盖甲")
    b2 = _bug(tracker, "被覆盖乙")
    closed_early = _bug(tracker, "早已关闭")
    tracker.set_state(closed_early, "closed", "手动关")
    d = _design(tracker, "整合修复", body=f"根因\n\ncovers: #{b1} #{b2} #{closed_early} #999")

    dev = _DirectPushDev(tracker, str(repo), str(tmp_path / "a"), pick_policy="design_first")
    outcome = dev.work_one()

    assert outcome.issue_number == d and outcome.committed is True
    for n in (b1, b2):
        assert tracker.issue(n)["state"] == "closed"
        assert f"covered by #{d} → v1" in tracker.issue(n)["reason"]
    assert tracker.issue(closed_early)["reason"] == "手动关"  # 已关的不重复动


def test_tracker_without_list_comments_degrades_gracefully(tmp_path) -> None:
    """裸桩 tracker（无 list_comments 观测能力）：不升档、不沉底、不抛错。"""
    repo = _seed_repo(tmp_path)

    class _BareTracker:
        def __init__(self) -> None:
            self.inner = FakeTracker()

        def list_open_issues(self):
            return self.inner.list_open_issues()

        def create_issue(self, draft):
            return self.inner.create_issue(draft)

        def add_comment(self, number, body):
            self.inner.add_comment(number, body)

        def set_state(self, number, state, reason):
            self.inner.set_state(number, state, reason)

        def ensure_labels(self, names):
            self.inner.ensure_labels(names)

    bare = _BareTracker()
    n = bare.create_issue(IssueDraft(title="x", body="", labels=["bug"])).number
    bare.add_comment(n, "[dev-attempt] 假装失败过")  # 即便有标记，无读能力也不升档

    dev = _DirectPushDev(bare, str(repo), str(tmp_path / "a"), budget_bug=38)
    outcome = dev.work_one()
    assert outcome.committed is True
    assert dev.budgets == [38]  # 未升档


def test_invalid_pick_policy_rejected(tmp_path) -> None:
    tracker = FakeTracker()
    try:
        AgenticDeveloper(tracker, "r", "a", pick_policy="whatever")
        raise AssertionError("应当抛 ValueError")
    except ValueError:
        pass
