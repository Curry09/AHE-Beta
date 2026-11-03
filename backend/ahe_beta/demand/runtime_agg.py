"""Runtime behavior aggregation: retrospectively extract task-agnostic metrics from persisted Session,
    feeding structural synthesis mechanism layer with evidence for determination.

Structural synthesis prompt claims "0-step round ratio / timeout ratio / per-round budget" and similar
contrastive numbers—prior code did not inject them, causing reason to compress into "timed out again",
making it impossible to distinguish "memory loss" from "budget too tight". This module only does
observational aggregation, not causal analysis.

All inputs are pre-persisted: `Turn.steps` (0013 observational bypass) + `reply` text + harness repo
budget constants. Does not change protocol, does not change Session schema, does not touch user-side
simulation path; only scans once in stage d during propose_once.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from ahe_beta.models import Session
from ahe_beta.user.session_store import SessionStore

# Only examine the last N rounds: sufficient to detect trends, keeps scan cost fixed (structural synthesis one LLM round is minute-scale, this is millisecond-scale).
_RECENT_N = 50

# reply classification: only coarse labeling, no task semantics parsing.
_RE_TIMEOUT = re.compile(r"timeout|timed\s*out", re.IGNORECASE)
_RE_INTERRUPTED = re.compile(r"\[interrupted\]", re.IGNORECASE)
_RE_HARNESS_ERROR = re.compile(r"\[harness\s*error\]", re.IGNORECASE)

# Budget knobs: repo constants/config, do not import harness (separate repo, may not have nexau).
_RE_CALL_TIMEOUT = re.compile(r"^_CALL_TIMEOUT\s*=\s*(\d+)\s*$", re.MULTILINE)
_RE_RUN_RETRIES = re.compile(r"^_RUN_RETRIES\s*=\s*(\d+)\s*$", re.MULTILINE)
_RE_MAX_ITER = re.compile(r"^max_iterations\s*:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class RuntimeAgg:
    """Pure observational metrics aggregated across rounds; causal analysis left to structural synthesis."""

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
    """Scan the last recent_n Session rounds + read harness repo budget knobs → RuntimeAgg."""
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
    """Compress RuntimeAgg into short text readable by structural synthesis; explicitly denote empty data,
    do not fabricate."""
    if agg.n_sessions == 0:
        return "(No session data to aggregate yet)"

    def _pct(n: int, den: int) -> str:
        if den <= 0:
            return "n/a"
        return f"{100.0 * n / den:.0f}%"

    lines = [
        f"- Window: latest {agg.n_sessions} sessions, {agg.n_harness_turns} harness replies",
        (
            f"- Zero-step turns: {agg.n_zero_step}/{agg.n_harness_turns}"
            f" ({_pct(agg.n_zero_step, agg.n_harness_turns)})"
            " -- no inner tool/assistant activity stream"
        ),
        (f"- Median inner steps: {agg.median_steps if agg.median_steps is not None else 'n/a'}"),
        (
            f"- Reply tags: timeout={agg.n_timeout_reply}"
            f" ({_pct(agg.n_timeout_reply, agg.n_harness_turns)}), "
            f"interrupted={agg.n_interrupted_reply}, "
            f"harness_error={agg.n_harness_error_reply}"
        ),
        (
            f"- Tool steps: tool+tool_error={agg.n_tool_steps}, "
            f"including tool_error={agg.n_tool_error_steps}"
            f" ({_pct(agg.n_tool_error_steps, agg.n_tool_steps)})"
        ),
        f"- Current per-turn budget: {_format_budget(agg)}",
        "(Numbers only, without attribution; compare with experience reasons / backlog when investigating mechanism-level root causes.)",
    ]
    return "\n".join(lines)


def _load_recent(*, store: SessionStore, recent_n: int) -> list[Session]:
    """Take the last recent_n rounds sorted ascending by created_at; skip if full file missing (do not drag
    down stage d)."""
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
    """Read `_CALL_TIMEOUT` / `_RUN_RETRIES` / `max_iterations` from harness repo; return None if file missing."""
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
            f" (worst case approximately {agg.call_timeout_s * agg.run_retries}s)"
        )
    elif agg.call_timeout_s is not None:
        parts.append(f"_CALL_TIMEOUT={agg.call_timeout_s}s")
    if agg.max_iterations is not None:
        parts.append(f"max_iterations={agg.max_iterations}")
    return "; ".join(parts) if parts else "(No budget constants found in the repository)"
