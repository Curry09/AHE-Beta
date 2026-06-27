"""agentic_developer：开发者 = 带 git 工具的 nexau agent（取代确定性 DeveloperAgent）。

领一条 open issue，把确切的分支名 fix/issue-N 与下一个 tag vK 塞进任务消息，让 nexau agent 在
harness 仓（LocalSandbox work_dir）里自己 改 main.md → commit → merge release → tag → push Gitea。
跑完读仓状态（新 tag）判定是否发版。无门禁：dev 直接发版（体感退化为观测，benchmark held-out）。
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_designer.tracker.base import IssueTracker

_TAG_RE = re.compile(r"^v(\d+)$")
# 整个 dev agent.run 是多轮工具调用（改文件 + 多条 git），给足硬超时兜底防总挂死。
_DEV_TIMEOUT = 900

StatusFn = Callable[..., None]


@dataclass
class DevOutcome:
    """一次 work_one 的结果：拿到 tag 即本轮新发版（供编排回灌 ref）。"""

    issue_number: int | None = None
    branch: str | None = None
    tag: str | None = None
    released: bool = False


def _run_with_timeout(call: Callable[[], object], timeout: int) -> object:
    """daemon 线程跑 call，超时抛 TimeoutError（丢弃线程，不阻塞进程）。"""
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = call()
        except Exception as exc:  # noqa: BLE001  透传给调用方
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"dev agent 超时 >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


class AgenticDeveloper:
    """开发者 nexau agent 驱动器：一次处理一条 issue，自主改 harness + git 发版。"""

    def __init__(
        self,
        tracker: IssueTracker,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
    ) -> None:
        self._tracker = tracker
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status

    def work_one(self, skip: set[int] | None = None) -> DevOutcome:
        skip = skip or set()
        issues = [i for i in self._tracker.list_open_issues() if i.number not in skip]
        if not issues:
            self._emit(running=False, status="无可领 open issue")
            return DevOutcome()
        issue = issues[0]
        branch = f"fix/issue-{issue.number}"
        next_tag = f"v{self._next_version()}"
        self._emit(
            running=True,
            status=f"领取 issue #{issue.number}：{issue.title}",
            issue_number=issue.number,
            branch=branch,
        )

        tags_before = set(self._tags())
        self._emit(
            running=True,
            status=f"agent 改写+发版中…（{branch} → {next_tag}）",
            issue_number=issue.number,
            branch=branch,
        )
        result_text = self._run_agent(
            issue_number=issue.number,
            title=issue.title,
            body=issue.body,
            branch=branch,
            tag=next_tag,
        )

        new_tags = set(self._tags()) - tags_before  # 仓状态是 ground truth：新 tag 出现即发版
        released = bool(new_tags)
        tag = next_tag if next_tag in new_tags else (sorted(new_tags)[-1] if new_tags else None)
        if released and self._tracker is not None:
            try:
                self._tracker.set_state(issue.number, "closed", f"发版 {tag}")
            except Exception:  # noqa: BLE001  关 issue 失败不影响发版
                pass
        self._emit(
            running=False,
            status=(f"已发版 {tag}（{branch}）" if released else "本轮未发版"),
            issue_number=issue.number,
            branch=branch,
            detail=result_text[:800] if result_text else None,
        )
        return DevOutcome(issue_number=issue.number, branch=branch, tag=tag, released=released)

    def _run_agent(self, *, issue_number: int, title: str, body: str, branch: str, tag: str) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(
            self._repo
        )  # dev agent 的 sandbox 工作目录 = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        agent = Agent(config=cfg)
        msg = (
            "处理这条 issue，端到端落地成一次发版（必须做完 git 才 complete_task）。\n"
            f"issue #{issue_number}：{title}\n{body}\n\n"
            f"严格使用：分支名 `{branch}`、新 tag `{tag}`。\n"
            f"流程：`git checkout -B {branch} release` → 针对该 issue 改 `agents/main.md` → "
            f'`git add -A && git -c user.email=dev@auto-designer -c user.name=developer commit -m "fix: issue #{issue_number}"` → '
            f'`git checkout release && git merge --no-ff {branch} -m "release: merge {branch}"` → '
            f"`git tag {tag}` → `git push origin {branch}` `git push origin release` `git push origin {tag}` → "
            "验证 → complete_task 报告分支与 tag。"
        )
        out = _run_with_timeout(lambda: agent.run(message=msg), _DEV_TIMEOUT)
        return out if isinstance(out, str) else str(out)

    def _tags(self) -> list[str]:
        return subprocess.run(
            ["git", "-C", str(self._repo), "tag"], capture_output=True, text=True
        ).stdout.split()

    def _next_version(self) -> int:
        versions = [int(m.group(1)) for t in self._tags() if (m := _TAG_RE.match(t))]
        return (max(versions) + 1) if versions else 1

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)
