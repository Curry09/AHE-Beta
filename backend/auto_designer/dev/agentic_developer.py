# Spec-0007/T1：开发者侧改纯 trunk（单 main）——去掉 fix/issue-N 分支、--no-ff merge 与 release，
# dev 直推 main：checkout main → 改 main.md → commit → tag vK → push origin main vK。
"""agentic_developer：开发者 = 带 git 工具的 nexau agent（取代确定性 DeveloperAgent）。

领一条 open issue，把下一个 tag vK 塞进任务消息，让 nexau agent 在 harness 仓（LocalSandbox
work_dir）里自己 checkout main → 改 agents/main.md → commit → tag vK → push origin main vK。
跑完读仓状态（新 tag）判定是否已推进 main。无 branch/merge/门禁：dev 直推 main，每次成功打轻量 vK
tag 仅作观测锚点（体感退化为观测，benchmark held-out，坏 commit 靠后续多轮迭代回正——梯度下降式）。
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
    """一次 work_one 的结果。

    Spec-0007/T1：去掉 branch 字段（不再建分支）；`released`→`committed`，语义从「已发版」改为
    「已 commit 并推到 main」。判定仍以仓状态为 ground truth（新 vK tag 出现）。tag 仅作观测锚点。
    """

    issue_number: int | None = None
    tag: str | None = None
    committed: bool = False


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
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = (
            on_event  # 过程流回调 (kind, text)：assistant 发言/工具调用/结果，看板时间线用
        )

    def work_one(self, skip: set[int] | None = None) -> DevOutcome:
        skip = skip or set()
        issues = [i for i in self._tracker.list_open_issues() if i.number not in skip]
        if not issues:
            self._emit(running=False, status="无可领 open issue")
            return DevOutcome()
        issue = issues[0]
        next_tag = f"v{self._next_version()}"
        self._emit(
            running=True,
            status=f"领取 issue #{issue.number}：{issue.title}",
            issue_number=issue.number,
        )

        tags_before = set(self._tags())
        self._emit(
            running=True,
            status=f"agent 改 main + 直推中…（→ {next_tag}）",
            issue_number=issue.number,
        )
        result_text = self._run_agent(
            issue_number=issue.number,
            title=issue.title,
            body=issue.body,
            tag=next_tag,
        )

        # Spec-0007/T1：仓状态是 ground truth——新 vK tag 出现 = dev 已 commit 并推进 main。
        new_tags = set(self._tags()) - tags_before
        committed = bool(new_tags)
        tag = next_tag if next_tag in new_tags else (sorted(new_tags)[-1] if new_tags else None)
        if committed and self._tracker is not None:
            try:
                self._tracker.set_state(issue.number, "closed", f"已推进 main {tag}")
            except Exception:  # noqa: BLE001  关 issue 失败不影响已推进的 main
                pass
        self._emit(
            running=False,
            status=(f"已推进 main {tag}" if committed else "本轮未推进 main"),
            issue_number=issue.number,
            tag=tag,
            committed=committed,
            detail=result_text or None,  # 最终报告全文（详情面板展示，不截断）
        )
        return DevOutcome(issue_number=issue.number, tag=tag, committed=committed)

    def _run_agent(self, *, issue_number: int, title: str, body: str, tag: str) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(
            self._repo
        )  # dev agent 的 sandbox 工作目录 = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        if self._on_event is not None:
            # 过程流（assistant 发言 + 逐工具调用/结果）流到看板时间线（黑盒 run 变逐步可观测），
            # 见 loop/live_tracer。
            from auto_designer.loop.live_tracer import (
                StepTracer,  # noqa: PLC0415  依赖 nexau，懒加载
            )

            cfg.resolved_tracer = StepTracer(self._on_event)
        agent = Agent(config=cfg)
        # Spec-0007/T1：直推 main——无 branch/merge/release，commit 落 main、打 vK tag、push main+tag。
        msg = (
            "领这条 issue，按你系统提示里的工程原则处理，端到端落地成一次对 main 的推进"
            "（必须做完 git 才 complete_task）。\n"
            f"issue #{issue_number}：{title}\n{body}\n\n"
            "边界（硬约束）：你改的是**通用编码助手 harness 本体**"
            "（entry.py / agents/ / tools/ / MANUAL.md / params.yaml），不是某个具体任务。issue 若在"
            "抱怨「某任务没做成」（装不上某个包、跑不动某项目），那是 harness 的**能力缺口**——只改进"
            "通用能力（如让它更会搭脚手架、读报错、装依赖、控超时），**绝不把被测项目代码写进 harness 仓**"
            "（新建包、pyproject.toml、任务 tests/ 等；仓已装 pre-commit 边界钩子，越界提交会被拒、白费迭代）。\n"
            f"严格使用新 tag `{tag}`。\n"
            "流程：读懂现状、诊断/判类（缺陷 or 能力缺口） → **切出这轮能收敛完的最小可提交步**"
            "（任务大就按增量方法论，这轮只落第一步、别想一次做完） → `git checkout main` → 落地这一步 → "
            "自验（廉价冒烟、别重放难任务、带 timeout 防卡；确认不崩、回一行合法 JSON reply，"
            "崩了/超时就继续改别 commit） → "
            f'`git add -A && git -c user.email=dev@auto-designer -c user.name=developer commit -m "fix: issue #{issue_number}"` → '
            f"`git tag {tag}` → `git push origin main` `git push origin {tag}` → "
            "确认落地 → complete_task 报告根因/类型、改了哪些文件及为什么改在这层、自验命令与输出、新 tag，"
            "以及（若按增量拆了）这轮落了哪一步、下一步该做什么留作 follow-up。"
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
