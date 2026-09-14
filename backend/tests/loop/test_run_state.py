"""spec-0004/T1 + Spec-0007/T2：RunState 读写 round-trip 单测。

Spec-0007/T2：`current_release_ref` 字段名保留、语义改为「当前 main HEAD SHA」（观测游标）；
本测试用 SHA 形态的值断言读写往返一致。
"""

from __future__ import annotations

from auto_designer.loop.run_state import RunState, read_run_state, write_run_state


def test_round_trip_in_memory() -> None:
    rs = RunState(
        round=3,
        phase="b",
        current_release_ref="a1b2c3d4e5f6",  # Spec-0007/T2：当前 main HEAD SHA
        done_session_keys=["p1|s1", "p1|s2"],
        issue_assignments={"7": "dev-0"},
        pending=["issue:7"],
    )
    assert RunState.from_dict(rs.to_dict()) == rs


def test_write_then_read(tmp_path) -> None:
    rs = RunState(
        recovery_revision=7,
        round=2,
        current_release_ref="deadbeef1234",
        done_session_keys=["a"],
    )
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
