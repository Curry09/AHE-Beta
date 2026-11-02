"""运行时行为聚合：从已落盘 Session 事后扫出任务无关指标，喂结构综合作机制层判别证据。

结构综合 prompt 宣称有「0 步轮占比 / 超时占比 / 单轮预算」等对照数字——此前代码未注入，
导致 reason 压成「又超时」时分不清「失忆」与「预算太紧」。本组只做观测聚合、不做归因。

原料全是既有落盘：`Turn.steps`（0013 观测旁路）+ `reply` 文本 + harness 仓预算常量。
不改协议、不改 Session schema、不碰用户侧模拟路径；只在 d 段 propose_once 扫一次。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from ahe_beta.models import Session
from ahe_beta.user.session_store import SessionStore

# 只看最近 N 局：够判别趋势，又把扫盘成本钉死（结构综合一轮 LLM 是分钟级，这里毫秒级）。
_RECENT_N = 50

# reply 归类：只做粗标签，不解析任务语义。
_RE_TIMEOUT = re.compile(r"timeout|timed\s*out|超时", re.IGNORECASE)
_RE_INTERRUPTED = re.compile(r"\[interrupted\]", re.IGNORECASE)
_RE_HARNESS_ERROR = re.compile(r"\[harness\s*error\]", re.IGNORECASE)

# 预算钮：仓内常量/配置，不 import harness（独立仓、可能无 nexau）。
_RE_CALL_TIMEOUT = re.compile(r"^_CALL_TIMEOUT\s*=\s*(\d+)\s*$", re.MULTILINE)
_RE_RUN_RETRIES = re.compile(r"^_RUN_RETRIES\s*=\s*(\d+)\s*$", re.MULTILINE)
_RE_MAX_ITER = re.compile(r"^max_iterations\s*:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RuntimeAgg:
    """跨局聚合出的纯观测数字；归因留给结构综合。"""

    n_sessions: int
    n_harness_turns: int
    n_zero_step: int
    n_timeout_reply: int
    n_interrupted_reply: int
    n_harness_error_reply: int
    n_tool_error_steps: int
    n_tool_steps: int
    median_steps: float | None
    call_timeout_s: int | None
    run_retries: int | None
    max_iterations: int | None


def aggregate_runtime(
    *,
    store: SessionStore,
    harness_repo: Path,
    recent_n: int = _RECENT_N,
) -> RuntimeAgg:
    """扫最近 recent_n 局 Session + 读 harness 仓预算钮 → RuntimeAgg。"""
    sessions = _load_recent(store=store, recent_n=recent_n)
    n_harness = 0
    n_zero = 0
    n_timeout = 0
    n_interrupted = 0
    n_h_err = 0
    n_tool_err = 0
    n_tool = 0
    step_counts: list[int] = []

    for session in sessions:
        for turn in session.transcript.turns:
            if turn.role != "harness":
                continue
            n_harness += 1
            n_steps = len(turn.steps)
            step_counts.append(n_steps)
            if n_steps == 0:
                n_zero += 1
            reply = turn.content or ""
            if _RE_TIMEOUT.search(reply):
                n_timeout += 1
            if _RE_INTERRUPTED.search(reply):
                n_interrupted += 1
            if _RE_HARNESS_ERROR.search(reply):
                n_h_err += 1
            for step in turn.steps:
                kind = str(step.get("kind", ""))
                if kind == "tool":
                    n_tool += 1
                elif kind == "tool_error":
                    n_tool_err += 1
                    n_tool += 1

    budget = _read_budget(harness_repo=harness_repo)
    return RuntimeAgg(
        n_sessions=len(sessions),
        n_harness_turns=n_harness,
        n_zero_step=n_zero,
        n_timeout_reply=n_timeout,
        n_interrupted_reply=n_interrupted,
        n_harness_error_reply=n_h_err,
        n_tool_error_steps=n_tool_err,
        n_tool_steps=n_tool,
        median_steps=(statistics.median(step_counts) if step_counts else None),
        call_timeout_s=budget[0],
        run_retries=budget[1],
        max_iterations=budget[2],
    )


def format_runtime_agg(agg: RuntimeAgg) -> str:
    """把 RuntimeAgg 收成结构综合可读的短文；空数据明示，不瞎编。"""
    if agg.n_sessions == 0:
        return "（暂无会话数据可聚合）"

    def _pct(n: int, den: int) -> str:
        if den <= 0:
            return "n/a"
        return f"{100.0 * n / den:.0f}%"

    lines = [
        f"- 窗口：最近 {agg.n_sessions} 局会话，共 {agg.n_harness_turns} 轮 harness 回复",
        (
            f"- 0 步轮：{agg.n_zero_step}/{agg.n_harness_turns}"
            f"（{_pct(agg.n_zero_step, agg.n_harness_turns)}）"
            "——内层无任何 tool/assistant 过程流"
        ),
        (f"- 内层步数中位数：{agg.median_steps if agg.median_steps is not None else 'n/a'}"),
        (
            f"- reply 标签：timeout={agg.n_timeout_reply}"
            f"（{_pct(agg.n_timeout_reply, agg.n_harness_turns)}），"
            f"interrupted={agg.n_interrupted_reply}，"
            f"harness_error={agg.n_harness_error_reply}"
        ),
        (
            f"- 工具步：tool+tool_error={agg.n_tool_steps}，"
            f"其中 tool_error={agg.n_tool_error_steps}"
            f"（{_pct(agg.n_tool_error_steps, agg.n_tool_steps)}）"
        ),
        f"- 当前单轮预算：{_format_budget(agg)}",
        "（只给数字，未做归因；机制类根因请拿这条对照体感 reason / backlog。）",
    ]
    return "\n".join(lines)


def _load_recent(*, store: SessionStore, recent_n: int) -> list[Session]:
    """按 created_at 升序取末尾 recent_n 局；缺全量文件则跳过（不拖垮 d 段）。"""
    rows = sorted(store.index(), key=lambda e: e["created_at"])
    if recent_n > 0:
        rows = rows[-recent_n:]
    out: list[Session] = []
    for row in rows:
        sid = row.get("session_id")
        if not isinstance(sid, str) or not sid:
            continue
        try:
            out.append(store.load(sid))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def _read_budget(*, harness_repo: Path) -> tuple[int | None, int | None, int | None]:
    """从 harness 仓读 `_CALL_TIMEOUT` / `_RUN_RETRIES` / `max_iterations`；缺文件→None。"""
    call_timeout: int | None = None
    run_retries: int | None = None
    max_iter: int | None = None
    entry = harness_repo / "entry.py"
    if entry.is_file():
        text = entry.read_text(encoding="utf-8")
        m = _RE_CALL_TIMEOUT.search(text)
        if m:
            call_timeout = int(m.group(1))
        m = _RE_RUN_RETRIES.search(text)
        if m:
            run_retries = int(m.group(1))
    yaml_path = harness_repo / "agent.yaml"
    if yaml_path.is_file():
        text = yaml_path.read_text(encoding="utf-8")
        m = _RE_MAX_ITER.search(text)
        if m:
            max_iter = int(m.group(1))
    return call_timeout, run_retries, max_iter


def _format_budget(agg: RuntimeAgg) -> str:
    parts: list[str] = []
    if agg.call_timeout_s is not None and agg.run_retries is not None:
        parts.append(
            f"_CALL_TIMEOUT={agg.call_timeout_s}s × _RUN_RETRIES={agg.run_retries}"
            f"（最坏约 {agg.call_timeout_s * agg.run_retries}s）"
        )
    elif agg.call_timeout_s is not None:
        parts.append(f"_CALL_TIMEOUT={agg.call_timeout_s}s")
    if agg.max_iterations is not None:
        parts.append(f"max_iterations={agg.max_iterations}")
    return "；".join(parts) if parts else "（仓内未读到预算常量）"
