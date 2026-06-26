"""developer_agent（spec-0003/T3）：领一条 open issue，按 label 分流分支，用 nexau 改 harness 并提交。

bug → 从 release 切 fix/issue-<n> 快修；feature → feat/issue-<n> 孵化；两者皆无 → 默认按 bug。
MVP 单 agent、一次一条、串行。改动落在 harness 仓的 agents/main.md（v0 单 agent 的定义），无改动则不空提交。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from auto_designer.nexau_runtime import Agent
from auto_designer.tracker.base import IssueTracker

# 开发者 agent 修改的目标（v0 harness 的主 agent 定义）。
_TARGET = Path("agents") / "main.md"


@dataclass
class DevResult:
    """一次 work_one 的结果。无 issue 时各字段为空、changed=False。"""

    issue_number: int | None = None
    branch: str | None = None
    commit: str | None = None
    changed: bool = False
    default_routed: bool = False


class DeveloperAgent:
    """从 tracker 取一条 open issue 改 harness。一次处理一条；编排（几条/何时停）归 T6。"""

    def __init__(self, tracker: IssueTracker, harness_repo: str, nexau_agent: Agent) -> None:
        self._tracker = tracker
        self._repo = Path(harness_repo)
        self._agent = nexau_agent

    def work_one(self, skip: set[int] | None = None) -> DevResult:
        skip = skip or set()  # 同轮多 dev 时跳过已被别的 dev 认领的 issue
        issues = [i for i in self._tracker.list_open_issues() if i.number not in skip]
        if not issues:
            return DevResult()  # 无（可领）open issue → 不建分支、不报错
        issue = issues[0]

        prefix, default_routed = self._route(issue.labels)
        branch = f"{prefix}/issue-{issue.number}"
        self._run_git(["checkout", "-B", branch, "release"])  # 从 release 切出（基线单一）

        target = self._repo / _TARGET
        old = target.read_text(encoding="utf-8") if target.is_file() else ""
        new = self._agent.run(self._build_prompt(issue.number, issue.title, issue.body, old))

        if not new.strip() or new == old:  # 无改动 → 不空提交
            self._tracker.add_comment(issue.number, f"本轮未产出改动（#{issue.number}）")
            return DevResult(
                issue_number=issue.number,
                branch=branch,
                changed=False,
                default_routed=default_routed,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new, encoding="utf-8")
        self._run_git(["add", "-A"])
        self._commit(f"fix: issue #{issue.number} {issue.title}")
        commit = self._run_git(["rev-parse", "HEAD"]).strip()
        self._push(branch)
        note = "（label 无 bug/feature，默认按 bug 分流）" if default_routed else ""
        self._tracker.add_comment(
            issue.number, f"已在分支 {branch} 处理 issue #{issue.number}{note}"
        )
        return DevResult(
            issue_number=issue.number,
            branch=branch,
            commit=commit,
            changed=True,
            default_routed=default_routed,
        )

    def _route(self, labels: list[str]) -> tuple[str, bool]:
        if "bug" in labels:
            return "fix", False
        if "feature" in labels:
            return "feat", False
        return "fix", True  # 默认按 bug 路径（最快反馈）

    def _build_prompt(self, number: int, title: str, body: str, current: str) -> str:
        return (
            f"issue #{number}：{title}\n{body}\n\n"
            f"当前 harness 主 agent 定义 agents/main.md：\n---\n{current}\n---\n\n"
            "据此 issue 产出修改后的【完整】agents/main.md 内容；若无需改动则原样返回。"
        )

    def _commit(self, message: str) -> None:
        self._run_git(
            [
                "-c",
                "user.email=dev@auto-designer",
                "-c",
                "user.name=developer-agent",
                "commit",
                "-m",
                message,
            ]
        )

    def _push(self, branch: str) -> None:
        remotes = self._run_git(["remote"]).split()
        if "origin" in remotes:  # 本地仓（无 origin）跳过 push，便于离线单测
            self._run_git(["push", "-u", "origin", branch])

    def _run_git(self, args: list[str]) -> str:
        result = subprocess.run(
            ["git", "-C", str(self._repo), *args], check=True, capture_output=True, text=True
        )
        return result.stdout
