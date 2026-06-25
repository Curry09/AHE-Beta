"""可恢复 harbor runner（spec-0004/T2）：作为一个 harbor task（方案 A，整条 run = 1 task）。

在 orchestrator 外层驱动逐轮跑；每轮边界 write_run_state + save_checkpoint，经 harbor artifact 通道吐出沙盒；
新 task 喂最新 checkpoint 即从断点续跑（轮次粒度幂等：已完成的轮跳过，最坏丢当前轮在途）。
orchestrator.run_round 保持纯编排，恢复逻辑收在此外层；逐轮真人对话仍走 spec-0001 自立协议（非 harbor 批接口）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from auto_designer.loop.checkpoint import load_checkpoint, save_checkpoint
from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.run_state import RunState, read_run_state, write_run_state

# checkpoint 存取注入点（默认真实实现；测试可注入 spy）。
SaveFn = Callable[[Path, Path], Path]
LoadFn = Callable[[Path, Path], None]


class HarborRunner:
    """orchestrator 外层的可恢复运行入口。"""

    def __init__(
        self,
        orchestrator: Orchestrator,
        state_dir: str | Path,
        artifact_dir: str | Path,
        save_fn: SaveFn = save_checkpoint,
        load_fn: LoadFn = load_checkpoint,
    ) -> None:
        self._orch = orchestrator
        self._state_dir = Path(state_dir)
        self._artifact_dir = Path(artifact_dir)
        self._save = save_fn
        self._load = load_fn

    def run(
        self, initial_release_ref: str, n_rounds: int, checkpoint_artifact: str | Path | None = None
    ) -> Path | None:
        """跑至多 n_rounds 轮；每轮末吐增量 checkpoint，返回最新 artifact（无轮次则返回传入的）。"""
        if n_rounds <= 0:
            raise ValueError(f"n_rounds 须为正：{n_rounds}")

        if checkpoint_artifact is not None:
            self._load(Path(checkpoint_artifact), self._state_dir)  # 还原 STATE_DIR
            rs = read_run_state(self._state_dir)
            start_round = rs.round
            ref = rs.current_release_ref or initial_release_ref
        else:
            start_round = 0
            ref = initial_release_ref
            write_run_state(
                self._state_dir, RunState(round=0, phase="a", current_release_ref=ref)
            )

        latest: Path | None = Path(checkpoint_artifact) if checkpoint_artifact is not None else None
        for r in range(start_round, n_rounds):
            ref = self._orch.run_round(ref)  # 纯编排一轮 a→b→c
            write_run_state(
                self._state_dir, RunState(round=r + 1, phase="c", current_release_ref=ref)
            )
            latest = self._save(
                self._state_dir, self._artifact_dir / f"checkpoint-round-{r + 1}.tar.gz"
            )
        return latest
