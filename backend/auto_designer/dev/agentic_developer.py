# Spec-0007/T1：开发者侧改纯 trunk（单 main）——去掉 fix/issue-N 分支、--no-ff merge 与 release，
# dev 直推 main：checkout main → 改 main.md → commit → tag vK → push origin main vK。
"""agentic_developer：开发者 = 带 git 工具的 nexau agent（取代确定性 DeveloperAgent）。

领一条 open issue，把下一个 tag vK 塞进任务消息，让 nexau agent 在 harness 仓（LocalSandbox
work_dir）里自己 checkout main → 改 agents/main.md → commit → tag vK → push origin main vK。
跑完读仓状态（新 tag）判定是否已推进 main。无 branch/merge/门禁：dev 直推 main，每次成功打轻量 vK
tag 仅作观测锚点（体感退化为观测，benchmark held-out，坏 commit 靠后续多轮迭代回正——梯度下降式）。

Spec-0025/T5：dev 侧简化（配合 triage 漏斗）。去掉 0020 的分池（pick_policy）/重试升档/stuck 沉底——
dev 只领**可领集合**（`triaged` 或 `RFC` 标签；排除 needs-triage/superseded，rejected/needs-info 已关闭
不在 open 集）→ 按票号升序取一条、`attempted` 防撞。每轮每 dev 领一条，**backlog 超容量则未领的自然积压
到下一轮**（open issue 无 attempt/stuck 机制，下轮再被领）。预算按 kind 分档（bug/feature/chore/document
各档 + RFC 最高档），无重试升档。issue 推进后：关它 + 回写报告 comment；若带 covers 行（RFC）则连带关闭
其覆盖的 triaged issue。dev 侧为**过渡实现**，后续换仓 agent 接入时再完善。
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_designer.designer.issue_schema import (
    FROM_SYNTHESIZE,
    PRIORITIES,
    RFC_LABEL,
    USER_KINDS,
    is_ready,
    priority_of,
)
from auto_designer.tracker.base import IssueTracker

_TAG_RE = re.compile(r"^v(\d+)$")
# 整个 dev agent.run 是多轮工具调用（改文件 + 多条 git），给足硬超时兜底防总挂死。
_DEV_TIMEOUT = 900

# 结果回写进 comment 的截断长度（未推进时的失败原因，报错串可读即可）。
_ATTEMPT_REASON_CAP = 400
# 各 kind 的默认迭代预算（结构提案改动最重、最高档）。env 覆盖见 run.py。
DEFAULT_BUDGETS: dict[str, int] = {
    "bug": 120,
    "feature": 120,
    "chore": 100,
    "document": 100,
    "rfc": 200,
}

StatusFn = Callable[..., None]


def _issue_kind(labels: list[str]) -> str:
    """从标签认 issue 的预算档：结构提案（from-synthesize，或旧 RFC 标签）最高档，
    否则取 type 标签，都没有兜底 bug。"""
    if FROM_SYNTHESIZE in labels or RFC_LABEL in labels:
        return "rfc"
    for k in USER_KINDS:
        if k in labels:
            return k
    return "bug"


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
        budgets: dict[str, int] | None = None,
    ) -> None:
        self._tracker = tracker
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = (
            on_event  # 过程流回调 (kind, text)：assistant 发言/工具调用/结果，看板时间线用
        )
        # Spec-0025/T5：预算按 kind 分档（RFC 最高）。env 覆盖在 run.py 拼好后注入；缺省用 DEFAULT_BUDGETS。
        self._budgets = {**DEFAULT_BUDGETS, **(budgets or {})}

    def _eligible(self, issues: list) -> list:
        """可领集合 = **白名单** is_ready（Spec-0029/T7：ready 平面唯一入口，旧 triaged/RFC 数据经
        plane 映射同样命中；任何新增流程标签默认不可领，fail-closed）。

        排序：priority（P0>P1>P2>P3>无）→ 票号（同优先级内 FIFO 老优先、防饿死）。carryover 自然
        发生——未被领的仍 open，下轮再领。
        """
        ok = [i for i in issues if is_ready(labels=i.labels, state="open")]

        def sort_key(i) -> tuple[int, int]:
            p = priority_of(i.labels)
            rank = PRIORITIES.index(p) if p in PRIORITIES else len(PRIORITIES)
            return (rank, i.number)

        return sorted(ok, key=sort_key)

    def work_one(self, skip: set[int] | None = None) -> DevOutcome:
        skip = skip or set()
        eligible = [
            i for i in self._eligible(self._tracker.list_open_issues()) if i.number not in skip
        ]
        if not eligible:
            self._emit(running=False, status="无可领 ready issue")
            return DevOutcome()
        issue = eligible[0]  # priority→票号 取最该做的一条；多 dev 靠 attempted 防撞、其余积压到下轮
        budget = self._budgets.get(_issue_kind(list(issue.labels)), self._budgets["bug"])
        next_tag = f"v{self._next_version()}"
        self._emit(
            running=True,
            status=f"领取 issue #{issue.number}：{issue.title}",
            issue_number=issue.number,
        )

        tags_before = set(self._tags())
        self._emit(
            running=True,
            status=f"agent 改 main + 直推中…（→ {next_tag}，预算 {budget} 迭代）",
            issue_number=issue.number,
        )
        result_text = self._run_agent(
            issue_number=issue.number,
            title=issue.title,
            body=issue.body,
            tag=next_tag,
            budget=budget,
        )

        # Spec-0007/T1：仓状态是 ground truth——新 vK tag 出现 = dev 已 commit 并推进 main。
        new_tags = set(self._tags()) - tags_before
        committed = bool(new_tags)
        tag = next_tag if next_tag in new_tags else (sorted(new_tags)[-1] if new_tags else None)
        if committed:
            try:
                self._tracker.set_state(issue.number, "closed", f"已推进 main {tag}")
            except Exception:  # noqa: BLE001  关 issue 失败不影响已推进的 main
                pass
            # 报告全文回写票上（含 dev 自述的 follow-up 段）——知识留在权威源，供 synthesize/下一任
            # dev/人工回看。
            if result_text:
                try:
                    self._tracker.add_comment(issue.number, result_text)
                except Exception:  # noqa: BLE001  回写失败不影响已推进的 main
                    pass
            # Spec-0029/T7：dev 只关自己的票——covers 级联已前移至 Owner 准入时 merge（被覆盖票在
            # admit 时即关闭并链回主票），dev 与 tracker 的耦合降到「领票 + 关自己」。
        else:
            # 未推进：留失败原因 comment（不做重试升档；下轮该票仍 open、会被再领）。
            reason = (result_text or "").strip() or "无报告（agent 异常或超时）"
            try:
                self._tracker.add_comment(
                    issue.number,
                    f"[dev] 本轮未推进 main：{reason[:_ATTEMPT_REASON_CAP]}",
                )
            except Exception:  # noqa: BLE001  回写失败不影响本轮结果
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

    def _run_agent(self, *, issue_number: int, title: str, body: str, tag: str, budget: int) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(
            self._repo
        )  # dev agent 的 sandbox 工作目录 = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        # Spec-0020/T2：按票种/重试运行时覆盖迭代预算（yaml 里的 max_iterations 仅作缺省文档值）。
        cfg.max_iterations = budget
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
