"""spec-0004/T1：RunState 读写 round-trip 单测。"""

from __future__ import annotations

from auto_designer.loop.run_state import RunState, read_run_state, write_run_state


def test_round_trip_in_memory() -> None:
    rs = RunState(
        round=3,
        phase="b",
        current_release_ref="v3",
        done_session_keys=["p1|s1", "p1|s2"],
        issue_assignments={"7": "fix/issue-7"},
        pending=["merge:fix/issue-7"],
    )
    assert RunState.from_dict(rs.to_dict()) == rs


def test_write_then_read(tmp_path) -> None:
    rs = RunState(round=2, current_release_ref="v2", done_session_keys=["a"])
    write_run_state(tmp_path, rs)
    assert read_run_state(tmp_path) == rs


def test_read_missing_returns_initial(tmp_path) -> None:
    rs = read_run_state(tmp_path)
    assert rs == RunState() and rs.round == 0


def test_write_is_atomic_replace(tmp_path) -> None:
    write_run_state(tmp_path, RunState(round=1))
    write_run_state(tmp_path, RunState(round=2))  # 覆盖
    assert read_run_state(tmp_path).round == 2
    assert not (tmp_path / "run_state.json.tmp").exists()  # 无残留 tmp
