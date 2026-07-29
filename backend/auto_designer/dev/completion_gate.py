"""CompletionGateMiddleware：收尾闸门——保证 dev 收尾时是一次"完整提交"。

痛点（实测）：dev 改了对外可观察行为（entry.py 冒出进度事件）却不同步用户帮助
（3 轮里 2 轮没更 HELP.md）；自验用的冒烟测试跑完即弃、0/3 落库；更糟的是只测 helper、
主路径 `main` 里「先用后赋」仍可绿测提交（WAIT 进化探针：evidence 接线 NameError）。

机制：拦在 stop tool（complete_task）上。当 dev 想收尾时，在 after_model 里检查 harness 仓
真实 git 状态；不达标就把 complete_task 调用从本次解析结果里剔掉 + force_continue + 注入
反馈，让它**在同一轮内继续**补齐再收尾——不新增 agent 调用。分档：

- 硬闸（必须满足才放行）：
  ① 工作区必须干净（无未提交/未推送改动）；
  ② 本轮若改了对外可观察行为（entry.py）却没在提交里同步 HELP.md → 拦，
     除非它在 complete_task 报告里显式声明"本次无对外可见变化"；
  ③ 本轮改了 entry.py 时，对 HEAD 上 `main` / `_run_supervised` 做 AST「局部先用后赋」扫描
     （挡住把 helper 测绿但主路径 NameError 的提交）。
- 软闸（预算紧就让路）：本轮改了逻辑却没落库任何回归测试 → 催落库；若有 heartbeat 类符号
  而测试未见短等/wait 断言 → 催补「等待中途有 progress」的契约测；remaining 不足则降级放行。

预算兜底：remaining<=1 时整体让路（宁可收尾也不空转到 MAX_ITERATIONS）。
"""

from __future__ import annotations

import ast
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

# 声明"本次无对外可见变化"的豁免语（命中任一即放行帮助硬闸）。
_NO_VISIBLE_MARKERS = (
    "无对外可见变化",
    "无对外可见的变化",
    "无用户可见变化",
    "no user-visible change",
    "no user visible change",
)

# 对这些函数做「局部先用后赋」扫描（主路径接线）。
_WIRING_FUNCS = frozenset({"main", "_run_supervised"})

# 内建/极常见名：不当作「本函数后赋」漏检的误报源（未赋也多半不是本轮引入）。
_SKIP_NAMES = frozenset(dir(__builtins__)) | {
    "self",
    "cls",
    "True",
    "False",
    "None",
}


def _git(repo: str, *args: str) -> str | None:
    """跑一条 git 子命令，返回 stdout（strip）；非 git 仓/出错返回 None，绝不抛。"""
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _local_used_before_assign(source: str, *, func_names: frozenset[str]) -> list[str]:
    """在指定函数体内找「先 Load、同函数稍后才 Store」的局部名（典型 NameError 接线）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"entry.py 无法解析（SyntaxError: {exc}）——先修语法再收尾"]

    hits: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in func_names:
            continue
        body_stmts = [
            s
            for s in node.body
            if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        later_stores = (
            set().union(*(_names_stored_excluding_nested(s) for s in body_stmts))
            if body_stmts
            else set()
        )
        assigned: set[str] = {a.arg for a in node.args.args}
        assigned.update(a.arg for a in node.args.kwonlyargs)
        if node.args.vararg:
            assigned.add(node.args.vararg.arg)
        if node.args.kwarg:
            assigned.add(node.args.kwarg.arg)
        for stmt in body_stmts:
            for name in _names_loaded_before_store_in_stmt(stmt):
                if name in _SKIP_NAMES or name in assigned:
                    continue
                if name in later_stores:
                    hits.append(f"{node.name}() 中 `{name}` 先使用、后赋值（会 NameError）")
            assigned.update(_names_stored_excluding_nested(stmt))
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _names_stored_excluding_nested(node: ast.AST) -> set[str]:
    """收集 Store 名；不进入嵌套 def/class（避免误把内层赋值算进外层）。"""
    names: set[str] = set()

    def visit(n: ast.AST) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(node)
    return names


def _names_loaded_before_store_in_stmt(stmt: ast.AST) -> list[str]:
    """单条语句内：出现在任何 Store 之前的 Load 名（同句 `a = a+1` 的右侧 Load 算先用）。"""
    loaded: list[str] = []
    stored_so_far: set[str] = set()

    def visit(n: ast.AST) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(n, ast.Assign):
            visit(n.value)
            for t in n.targets:
                stored_so_far.update(_names_stored_excluding_nested(t))
            return
        if isinstance(n, ast.AnnAssign):
            if n.value is not None:
                visit(n.value)
            stored_so_far.update(_names_stored_excluding_nested(n.target))
            return
        if isinstance(n, ast.AugAssign):
            # `x += 1`：目标名在增强赋值前必须已存在；右侧先访。
            visit(n.value)
            stored_so_far.update(_names_stored_excluding_nested(n.target))
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id not in stored_so_far:
                loaded.append(n.id)
            return
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(stmt)
    return loaded


def _has_heartbeat_symbol(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and "heartbeat" in n.name.lower():
            return True
        if isinstance(n, ast.Name) and "heartbeat" in n.id.lower():
            return True
    return False


def _tests_mention_timing(text: str) -> bool:
    lower = text.lower()
    return any(
        k in lower
        for k in (
            "sleep(",
            "wait(",
            "heartbeat",
            "_progress_heartbeat",
            "interval",
            "仍在运行",
            "still running",
        )
    )


class CompletionGateMiddleware(Middleware):
    """在 complete_task 收尾处强制"完整提交（含帮助）+ 接线健全 + 尽量落库测试"。"""

    def __init__(
        self,
        *,
        stop_tool: str = "complete_task",
        observable_paths: tuple[str, ...] = ("entry.py",),
        help_path: str = "HELP.md",
        max_blocks: int = 8,
        soft_gate_min_remaining: int = 6,
        wiring_funcs: frozenset[str] = _WIRING_FUNCS,
    ) -> None:
        """配置收尾闸门。

        Args:
            stop_tool: 收尾工具名（命中即触发检查）。
            observable_paths: 视为"对外可观察行为"的文件（改了它们就要同步帮助）。
            help_path: 用户帮助文件名（当前为 HELP.md）。
            max_blocks: 累计拦截次数上限，防病态死循环耗预算。
            soft_gate_min_remaining: 剩余预算不足此值时不再催软闸（落地测试 / heartbeat 契约）。
            wiring_funcs: 对本轮改动的 entry.py 做先用后赋扫描的函数名集合。
        """
        self.stop_tool = stop_tool
        self.observable_paths = observable_paths
        self.help_path = help_path
        self.max_blocks = max_blocks
        self.soft_gate_min_remaining = soft_gate_min_remaining
        self.wiring_funcs = wiring_funcs
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

    def _read_head_file(self, rel: str) -> str | None:
        """读 HEAD 上某文件内容；失败返回 None。"""
        return _git(self._repo or "", "show", f"HEAD:{rel}")

    def _committed_test_text(self, committed: set[str]) -> str:
        """拼接本轮提交的测试文件全文（HEAD），供软闸扫契约关键词。"""
        chunks: list[str] = []
        for name in sorted(committed):
            if not self._looks_like_test(name):
                continue
            body = self._read_head_file(name)
            if body:
                chunks.append(body)
        return "\n".join(chunks)

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
        help_synced = self.help_path in committed
        declared_no_visible = any(m in report for m in _NO_VISIBLE_MARKERS)
        if observable_changed and not help_synced and not declared_no_visible:
            problems.append(
                f"[帮助同步] 本轮改了对外可观察行为（{', '.join(sorted(committed & set(self.observable_paths)))}）"
                f"却没更新并提交 {self.help_path}——请把新增的可见行为写进帮助并提交；"
                "若本次确无对外可见变化，在 complete_task 报告里显式写明「本次无对外可见变化」再收尾。"
            )

        if "entry.py" in committed:
            src = self._read_head_file("entry.py")
            if src is not None:
                for hit in _local_used_before_assign(src, func_names=self.wiring_funcs):
                    problems.append(
                        f"[接线健全] {hit}——只测 helper 不够；请按 main 真实顺序修接线，"
                        "并补一条覆盖该调用点的冒烟后再 commit。"
                    )

        if not drop_soft:
            logic_changed = any(p in committed for p in self.observable_paths)
            has_test = any(self._looks_like_test(n) for n in committed)
            if logic_changed and not has_test:
                problems.append(
                    "[落地测试] 本轮改了逻辑却没提交任何回归测试——把你自验用的冒烟脚本落库成一个"
                    "小测试放到 `tests/` 下（如 `tests/test_entry.py`，仓已有 `tests/test_smoke.py` 示范；"
                    "注意测试必须在 tests/ 内，顶层散落 test_*.py 会被边界钩子拒）并提交；"
                    "冒烟须覆盖本轮对外契约/接线，禁止只测纯 helper；"
                    "若预算实在紧张，可在报告里说明留作 follow-up。"
                )
            elif logic_changed and has_test and "entry.py" in committed:
                src = self._read_head_file("entry.py") or ""
                test_text = self._committed_test_text(committed)
                if _has_heartbeat_symbol(src) and not _tests_mention_timing(test_text):
                    problems.append(
                        "[进度自验] entry.py 含 heartbeat/周期进度，但本轮测试未见 "
                        "sleep/wait/heartbeat/interval 等短等断言——请补一条：把间隔调到 ≤0.3s，"
                        "确认**等待中途**发出 status/progress（而非只在 deadline）。"
                        "预算紧可在报告里声明 follow-up。"
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
