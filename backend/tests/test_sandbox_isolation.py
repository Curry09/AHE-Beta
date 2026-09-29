"""dev/synthesizer sandbox 与 trace 目录的隔离布局断言。

机制硬隔离：把 harness 仓下沉到独立父目录，使 trace（体感/会话 sessions、harness 运行副本
harness_runs）不再是 sandbox 的 `../` 同级——`../sessions`/`../harness_runs` 相对路径够不着，
堵住「dev/synthesizer 回看任务轨迹 → 把任务专属产物带进 harness」的过拟合泄漏。
"""

from __future__ import annotations

import run


def test_harness_repo_parent_isolated_from_data() -> None:
    # sandbox 的父目录不是 data/ 本身——否则 trace 与仓同级、`../sessions` 一步够到。
    assert run.HARNESS_REPO.parent != run.DATA
    assert run.HARNESS_REPO.parent == run.DATA / "harness_sandbox"


def test_trace_dirs_not_siblings_of_sandbox() -> None:
    # trace 目录都在 data/ 下（= sandbox 的 `../..`），不出现在 sandbox 的 `../` 同级层。
    sandbox_parent = run.HARNESS_REPO.parent
    for trace in ("sessions", "harness_runs"):
        assert not (sandbox_parent / trace).exists() or (sandbox_parent / trace) != (
            run.DATA / trace
        )
        # 关键：banned 相对目标（相对 sandbox 的 ../<trace>）不等于真 trace 目录
        assert (sandbox_parent / trace) != (run.DATA / trace)
