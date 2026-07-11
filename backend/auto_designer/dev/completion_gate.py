"""CompletionGateMiddleware：收尾闸门——保证 dev 收尾时是一次"完整提交"。

痛点（实测）：dev 改了对外可观察行为（entry.py 冒出进度事件）却不同步用户手册
（3 轮里 2 轮没更 MANUAL.md）；自验用的冒烟测试跑完即弃、0/3 落库。都是软纪律被间歇忽略。

机制：拦在 stop tool（complete_task）上。当 dev 想收尾时，在 after_model 里检查 harness 仓
真实 git 状态；不达标就把 complete_task 调用从本次解析结果里剔掉 + force_continue + 注入
反馈，让它**在同一轮内继续**补齐再收尾——不新增 agent 调用。分两档：

- 硬闸（必须满足才放行，保证"完整提交，含手册"）：
  ① 工作区必须干净（无未提交/未推送改动）；
  ② 本轮若改了对外可观察行为（entry.py）却没在提交里同步 MANUAL.md → 拦，
     除非它在 complete_task 报告里显式声明"本次无对外可见变化"（豁免，避免误伤纯内部重构）。
- 软闸（方案二：轻量 + 预算紧就让路）：本轮改了逻辑却没落库任何回归测试 → 提醒把自验冒烟
  落成一个小测试；临近预算上限（remaining<=3）自动降级为放行、记 follow-up，绝不为它把预算耗到超时。

预算兜底：remaining<=1 时整体让路（宁可收尾也不空转到 MAX_ITERATIONS）；配合前置提交，
代码增量早已落 main，最坏是手册/测试留 follow-up，不会回到"零提交超时"。
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from nexau.archs.main_sub.execution.hooks import (
    AfterModelHookInput,
    BeforeAgentHookInput,
    HookResult,
    Middleware,
)
from nexau.core.messages import Message, Role, TextBlock

logger = logging.getLogger(__name__)

# 声明"本次无对外可见变化"的豁免语（命中任一即放行手册硬闸）。
_NO_VISIBLE_MARKERS = (
    "无对外可见变化",
    "无对外可见的变化",
    "无用户可见变化",
    "no user-visible change",
    "no user visible change",
)


def _git(repo: str, *args: str) -> str | None:
    """跑一条 git 子命令，返回 stdout（strip）；非 git 仓/出错返回 None，绝不抛。"""
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


class CompletionGateMiddleware(Middleware):
    """在 complete_task 收尾处强制"完整提交（含手册）+ 尽量落库测试"。"""

    def __init__(
        self,
        *,
        stop_tool: str = "complete_task",
        observable_paths: tuple[str, ...] = ("entry.py",),
        manual_path: str = "MANUAL.md",
        max_blocks: int = 8,
        soft_gate_min_remaining: int = 6,
    ) -> None:
        """配置收尾闸门。

        Args:
            stop_tool: 收尾工具名（命中即触发检查）。
            observable_paths: 视为"对外可观察行为"的文件（改了它们就要同步手册）。
            manual_path: 用户手册文件名。
            max_blocks: 累计拦截次数上限，防病态死循环耗预算。
            soft_gate_min_remaining: 剩余预算不足此值时不再催"落地测试"软闸——避免在临界
                才逼它写测试却提交不完、反而留下脏工作区；此时测试留作 follow-up。
        """
        self.stop_tool = stop_tool
        self.observable_paths = observable_paths
        self.manual_path = manual_path
        self.max_blocks = max_blocks
        self.soft_gate_min_remaining = soft_gate_min_remaining
        self._repo: str | None = None
        self._start_sha: str | None = None
        self._blocks = 0

    def before_agent(self, hook_input: BeforeAgentHookInput) -> HookResult:  # type: ignore[override]
        """开工时锚定 harness 仓与起始 HEAD——据此判断"本轮"提交了什么。"""
        repo = os.environ.get("SANDBOX_WORK_DIR")
        if repo and (Path(repo) / ".git").exists():
            self._repo = repo
            self._start_sha = _git(repo, "rev-parse", "HEAD")
        return HookResult.no_changes()

    def after_model(self, hook_input: AfterModelHookInput) -> HookResult:  # type: ignore[override]
        """dev 想收尾时做完整性检查；不达标则剔除收尾调用、注入反馈、令其同轮继续。"""
        parsed = hook_input.parsed_response
        if parsed is None or not parsed.has_calls() or self._repo is None:
            return HookResult.no_changes()

        completing = [c for c in parsed.tool_calls if c.tool_name == self.stop_tool]
        if not completing:
            return HookResult.no_changes()

        remaining = hook_input.max_iterations - hook_input.current_iteration
        if remaining <= 1 or self._blocks >= self.max_blocks:
            return HookResult.no_changes()  # 预算兜底/防死循环：让它收尾

        report = self._report_text(completing)
        problems = self._check(report=report, drop_soft=remaining <= self.soft_gate_min_remaining)
        if not problems:
            return HookResult.no_changes()  # 达标，放行收尾

        self._blocks += 1
        kept = [c for c in parsed.tool_calls if c.tool_name != self.stop_tool]
        new_parsed = replace(parsed, tool_calls=kept)
        hint = self._render(problems, remaining=remaining)
        updated = self._inject(hook_input.messages, hint)
        logger.info("[CompletionGateMiddleware] blocked completion: %s", [p[:24] for p in problems])
        return HookResult.with_modifications(
            parsed_response=new_parsed, messages=updated, force_continue=True
        )

    @staticmethod
    def _report_text(calls) -> str:
        """把 complete_task 各参数里的字符串拼起来，供扫描豁免声明。"""
        out: list[str] = []
        for c in calls:
            for v in (c.parameters or {}).values():
                if isinstance(v, str):
                    out.append(v)
        return "\n".join(out)

    def _committed_names(self) -> set[str]:
        """本轮已提交改动涉及的文件名（start_sha..HEAD）。"""
        rng = f"{self._start_sha}..HEAD"
        out = _git(self._repo or "", "diff", "--name-only", rng)
        return set(out.splitlines()) if out else set()

    def _dirty(self) -> list[str]:
        """未提交（含未跟踪）改动的 porcelain 行；空=工作区干净。"""
        out = _git(self._repo or "", "status", "--porcelain")
        return [ln for ln in (out.splitlines() if out else []) if ln.strip()]

    def _check(self, *, report: str, drop_soft: bool) -> list[str]:
        problems: list[str] = []

        dirty = self._dirty()
        if dirty:
            preview = ", ".join(ln[3:] for ln in dirty[:6])
            problems.append(
                f"[完整提交] 工作区还有未提交/未跟踪改动（{preview}）——收尾前必须 "
                "git add -A && commit && push，确保工作区干净、改动全部落 main。"
            )

        committed = self._committed_names()
        observable_changed = any(p in committed for p in self.observable_paths)
        manual_synced = self.manual_path in committed
        declared_no_visible = any(m in report for m in _NO_VISIBLE_MARKERS)
        if observable_changed and not manual_synced and not declared_no_visible:
            problems.append(
                f"[手册同步] 本轮改了对外可观察行为（{', '.join(sorted(committed & set(self.observable_paths)))}）"
                f"却没更新并提交 {self.manual_path}——请把新增的可见行为写进手册并提交；"
                "若本次确无对外可见变化，在 complete_task 报告里显式写明「本次无对外可见变化」再收尾。"
            )

        if not drop_soft:
            logic_changed = any(p in committed for p in self.observable_paths)
            has_test = any(self._looks_like_test(n) for n in committed)
            if logic_changed and not has_test:
                problems.append(
                    "[落地测试] 本轮改了逻辑却没提交任何回归测试——把你自验用的冒烟脚本落库成一个"
                    "小测试放到 `tests/` 下（如 `tests/test_entry.py`，仓已有 `tests/test_smoke.py` 示范；"
                    "注意测试必须在 tests/ 内，顶层散落 test_*.py 会被边界钩子拒）并提交；"
                    "若预算实在紧张，可在报告里说明留作 follow-up。"
                )
        return problems

    @staticmethod
    def _looks_like_test(name: str) -> bool:
        base = name.rsplit("/", 1)[-1]
        return (
            base.startswith("test_")
            or base.endswith("_test.py")
            or name.startswith("tests/")
            or "/tests/" in name
        )

    @staticmethod
    def _render(problems: list[str], *, remaining: int) -> str:
        head = (
            "⛔ 收尾被拦下：这不是一次「完整提交」，先补齐下列项再调用 complete_task"
            f"（还剩约 {remaining} 轮预算，动作要小而准）：\n"
        )
        body = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(problems))
        return head + body

    @staticmethod
    def _inject(messages: list[Message], hint: str) -> list[Message]:
        """把闸门反馈并入最后一条 USER/FRAMEWORK 消息，否则追加一条 FRAMEWORK 消息。"""
        updated = list(messages)
        if updated and updated[-1].role in (Role.USER, Role.FRAMEWORK):
            last = updated[-1]
            blocks = list(last.content)
            for idx in range(len(blocks) - 1, -1, -1):
                if isinstance(blocks[idx], TextBlock):
                    blocks[idx] = TextBlock(text=f"{blocks[idx].text}\n\n{hint}")
                    break
            else:
                blocks.append(TextBlock(text=hint))
            updated[-1] = last.model_copy(update={"content": blocks})
        else:
            updated.append(Message(role=Role.FRAMEWORK, content=[TextBlock(text=hint)]))
        return updated
