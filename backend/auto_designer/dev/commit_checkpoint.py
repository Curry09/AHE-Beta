"""CommitCheckpointMiddleware：用机制（而非软提示）保证 dev 尽早落一个已提交的增量。

痛点：dev 有时无视"切最小片"的方法论，一口气建全套（实测 entry.py 憋 +375 行未提交），
撞满迭代/墙钟后**零提交落 main**，整轮白跑。软性 prompt 约束它会时不时不听。

机制：挂到 dev agent 的执行管线，每次模型调用前查 harness 仓的真实 git 状态——
- 一旦本轮已经产生过 commit（HEAD 相对开工时前移），达标，闭嘴不再打扰；
- 否则，当**预算已过 first_commit_by_frac** 或**未提交改动已超 big_diff_lines**（= 正在贪大）时，
  注入一条升级的 FRAMEWORK 指令：停止扩张、缩到最小可用、自验后立刻 commit+tag+push，其余留 follow-up。

三档压力（越晚越硬）：
- 普通（过 first_commit_by_frac 或贪大）：提醒切最小片、先落地。
- 严重（frac>=0.66）：警告正走向零提交白跑。
- **硬落地（remaining<=hard_commit_by_remaining）**：最后窗口，给不可含糊的"下一步就提交最小片"
  指令——治"软提示被一路无视、空转到 max_iterations 零提交"（实测 round5 dev-0 即此：撞满 34 迭代、
  零提交落 main）。仍不替模型写/提交代码，但把末段的"希望它提交"变成"逼它把探索停下来先落地"。

只提供"在正确时机施加持续压力"，不替模型写/提交代码（未验证代码绝不该自动提交）；配合 systemprompt
的增量方法论，把"soft 希望"变成"state-triggered 的主动干预"。仓路径取运行时 SANDBOX_WORK_DIR。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from nexau.archs.main_sub.execution.hooks import (
    BeforeAgentHookInput,
    BeforeModelHookInput,
    HookResult,
    Middleware,
)
from nexau.core.messages import Message, Role, TextBlock

logger = logging.getLogger(__name__)


def _git(repo: str, *args: str) -> str | None:
    """跑一条 git 子命令，返回 stdout（strip）；非 git 仓/出错返回 None，绝不抛。"""
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


class CommitCheckpointMiddleware(Middleware):
    """预算早期强制 dev 先落一个已提交增量，避免"贪大→撞墙→零提交"。"""

    def __init__(
        self,
        *,
        first_commit_by_frac: float = 0.25,
        big_diff_lines: int = 150,
        hard_commit_by_remaining: int = 3,
    ) -> None:
        """配置检查点。

        Args:
            first_commit_by_frac: 预算用到这一比例仍未提交即开始施压（0..1）。
            big_diff_lines: 未提交改动累计行数超过此值即视为"正在贪大"，提前施压。
            hard_commit_by_remaining: 剩余迭代 <= 此值且仍零提交 → 升级为"硬落地"指令
                （最后窗口，逼它停止探索、下一步就提交最小片），治"软提示被无视、空转到上限零提交"。
        """
        self.first_commit_by_frac = first_commit_by_frac
        self.big_diff_lines = big_diff_lines
        self.hard_commit_by_remaining = hard_commit_by_remaining
        self._repo: str | None = None
        self._start_sha: str | None = None

    def before_agent(self, hook_input: BeforeAgentHookInput) -> HookResult:  # type: ignore[override]
        """开工时锚定 harness 仓与起始 HEAD——之后据此判断"本轮是否已提交"。"""
        import os  # noqa: PLC0415  运行时读 sandbox 工作目录

        repo = os.environ.get("SANDBOX_WORK_DIR")
        if repo and (Path(repo) / ".git").exists():
            self._repo = repo
            self._start_sha = _git(repo, "rev-parse", "HEAD")
        return HookResult.no_changes()

    def before_model(self, hook_input: BeforeModelHookInput) -> HookResult:  # type: ignore[override]
        """未提交且（预算过线 或 改动过大）时，注入升级的"先提交最小增量"指令。"""
        if not self._repo or self._start_sha is None:
            return HookResult.no_changes()

        head = _git(self._repo, "rev-parse", "HEAD")
        if head is None or head != self._start_sha:
            return HookResult.no_changes()  # 本轮已产生 commit → 达标，闭嘴

        max_iter = hook_input.max_iterations or 1
        frac = hook_input.current_iteration / max_iter
        remaining = max_iter - hook_input.current_iteration
        pending = self._pending_line_count()

        past_budget = frac >= self.first_commit_by_frac
        too_big = pending >= self.big_diff_lines
        final_stretch = remaining <= self.hard_commit_by_remaining
        if not (past_budget or too_big or final_stretch):
            return HookResult.no_changes()

        hint = self._build_hint(frac=frac, pending=pending, remaining=remaining)
        return self._inject(hook_input.messages, hint)

    def _pending_line_count(self) -> int:
        """未提交改动的累计行数（tracked，numstat 的 added+deleted 之和）。取不到算 0。"""
        out = _git(self._repo or "", "diff", "HEAD", "--numstat")
        if not out:
            return 0
        total = 0
        for line in out.splitlines():
            cols = line.split("\t")
            if len(cols) >= 2:
                for c in cols[:2]:
                    if c.isdigit():
                        total += int(c)
        return total

    def _build_hint(self, *, frac: float, pending: int, remaining: int) -> str:
        # 硬落地档：最后窗口，零提交=整轮白跑。给不可含糊的"下一步就提交"指令，逼它停止探索。
        if remaining <= self.hard_commit_by_remaining:
            head = (
                f"⛔⛔ 最后约 {remaining} 轮迭代预算 —— 本轮到此仍是「零提交落 main」，"
                "再不提交这一整轮就彻底白跑（这是最坏结果）。"
            )
            if pending:
                head += f"你手上已有约 {pending} 行未提交改动。"
            body = (
                "立即停止一切探索、读文件、铺新范围。就现在，按这个顺序做完、别再做别的："
                "①把手上改动缩到「一个已经能跑起来的最小切片」（多余的先 git stash 或删掉）；"
                "②跑一次廉价冒烟自验（带 timeout，别重放难任务）；"
                "③马上 git add -A && commit && tag && push。"
                "其余一切都写进 complete_task 当 follow-up。你下一次工具调用就应该是提交，而不是继续改。"
            )
            return f"{head}\n{body}"

        pct = int(frac * 100)
        head = f"⛔ COMMIT CHECKPOINT — 你已用掉约 {pct}% 的迭代预算，且本轮尚未产生任何 commit"
        if pending:
            head += f"（未提交改动已累计约 {pending} 行）"
        head += "。"
        if frac >= 0.66:  # 严重档：警告正走向零提交白跑
            body = (
                "你正走向「整轮白跑、零提交落 main」——这是最坏结果。立刻停止扩张任何新范围，"
                "把手上改动缩到「一个已经能跑起来的最小切片」（多余的先 git stash 或删掉），"
                "跑一次廉价自验冒烟，然后马上 git add -A && commit && tag && push。"
                "剩下的一律写进 complete_task 当 follow-up，这轮必须先落一个已提交的增量。"
            )
        else:  # 普通档：提醒切最小片、先落地
            body = (
                "别再往下铺摊子了。按增量方法论：现在就切出一个能独立跑起来的最小片，"
                "自验通过后先 commit+tag+push 落地它，再考虑要不要继续。"
                "一个小的已提交增量，胜过一个做不完的大改。"
            )
        return f"{head}\n{body}"

    @staticmethod
    def _inject(messages: list[Message], hint: str) -> HookResult:
        """把提示并入最后一条 USER/FRAMEWORK 消息，否则追加一条 FRAMEWORK 消息。"""
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
        logger.info("[CommitCheckpointMiddleware] injected commit-checkpoint hint")
        return HookResult.with_modifications(messages=updated)
