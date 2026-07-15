# 设计师运行时行为聚合单测：事后扫 Session.steps/reply + harness 预算钮。
"""验证 runtime_agg：

- 空库 → 明示无数据；
- 从 harness 轮 steps/reply 推出 0 步占比、timeout 标签、中位数；
- 从仓内 entry.py / agent.yaml 读出预算常量；
- 格式化文本含关键数字且不做归因散文。
"""

from __future__ import annotations

from pathlib import Path

from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.models import (
    FeelingScore,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    Turn,
)
from auto_designer.user.session_store import SessionStore


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _save_session(
    store: SessionStore,
    *,
    harness_turns: list[tuple[str, list[dict]]],
) -> None:
    turns: list[Turn] = [Turn(role="user", content="do it")]
    for reply, steps in harness_turns:
        turns.append(Turn(role="harness", content=reply, steps=steps))
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=turns),
            feeling=FeelingScore(score=2, reason="慢"),
        )
    )


def _write_budget(repo: Path, *, timeout: int, retries: int, max_iter: int) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "entry.py").write_text(
        f"_RUN_RETRIES = {retries}\n_CALL_TIMEOUT = {timeout}\n",
        encoding="utf-8",
    )
    (repo / "agent.yaml").write_text(
        f"type: agent\nmax_iterations: {max_iter}\n",
        encoding="utf-8",
    )


def test_empty_store_formats_as_no_data(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    repo = tmp_path / "harness"
    repo.mkdir()
    text = format_runtime_agg(aggregate_runtime(store=store, harness_repo=repo, recent_n=50))
    assert "暂无会话数据" in text


def test_aggregates_zero_step_timeout_and_budget(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    repo = tmp_path / "harness"
    _write_budget(repo, timeout=120, retries=1, max_iter=30)

    # 一局：一轮 0 步 timeout；一轮有 2 个 tool step。
    _save_session(
        store,
        harness_turns=[
            ("[harness error] call timeout after 120s", []),
            (
                "done",
                [
                    {"kind": "tool", "text": "🔧 run_shell: ls"},
                    {"kind": "tool_result", "text": "ok"},
                ],
            ),
        ],
    )
    # 另一局：纯 interrupted、0 步。
    _save_session(
        store,
        harness_turns=[("[interrupted] stopped by user", [])],
    )

    agg = aggregate_runtime(store=store, harness_repo=repo, recent_n=50)
    assert agg.n_sessions == 2
    assert agg.n_harness_turns == 3
    assert agg.n_zero_step == 2
    assert agg.n_timeout_reply == 1
    assert agg.n_interrupted_reply == 1
    assert agg.n_harness_error_reply == 1
    assert agg.n_tool_steps == 1  # 只有 kind=tool 计入；tool_result 不计
    assert agg.median_steps == 0  # steps lens: 0, 2, 0 → median 0
    assert agg.call_timeout_s == 120
    assert agg.run_retries == 1
    assert agg.max_iterations == 30

    text = format_runtime_agg(agg)
    assert "0 步轮：2/3" in text
    assert "timeout=1" in text
    assert "_CALL_TIMEOUT=120s × _RUN_RETRIES=1" in text
    assert "max_iterations=30" in text
    assert "未做归因" in text


def test_recent_n_window_keeps_only_tail(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    repo = tmp_path / "harness"
    repo.mkdir()
    for _ in range(3):
        _save_session(store, harness_turns=[("ok", [{"kind": "assistant", "text": "hi"}])])
    # recent_n=1 → 只扫最后一局（1 个 harness 轮）
    agg = aggregate_runtime(store=store, harness_repo=repo, recent_n=1)
    assert agg.n_sessions == 1
    assert agg.n_harness_turns == 1
    assert agg.n_zero_step == 0


def test_missing_budget_files_still_aggregate(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    repo = tmp_path / "harness"
    repo.mkdir()
    _save_session(store, harness_turns=[("ok", [])])
    agg = aggregate_runtime(store=store, harness_repo=repo, recent_n=10)
    assert agg.call_timeout_s is None
    assert agg.max_iterations is None
    assert "未读到预算常量" in format_runtime_agg(agg)
