"""可恢复 Harbor runner（Spec-0004/T2, Spec-0064/T2）。

在 orchestrator 外层驱动逐轮跑；每轮边界 write_run_state + save_checkpoint，经 harbor artifact 通道吐出沙盒；
新运行可由 Orchestrator 的 recovery ledger 续到阶段/工作项；旧运行仍按完整轮次游标恢复。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ahe_beta.loop.checkpoint import load_checkpoint, save_checkpoint
from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.run_state import RunState, read_run_state, write_run_state

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
            if getattr(self._orch, "recovery_enabled", False):
                self._orch.refresh_recovery()
            rs = read_run_state(self._state_dir)
            start_round = rs.round
            ref = rs.current_release_ref or initial_release_ref
        else:
            start_round = 0
            ref = initial_release_ref
            write_run_state(self._state_dir, RunState(round=0, phase="a", current_release_ref=ref))

        latest: Path | None = Path(checkpoint_artifact) if checkpoint_artifact is not None else None
        for r in range(start_round, n_rounds):
            try:
                if getattr(self._orch, "recovery_enabled", False):
                    ref = self._orch.run_round(
                        ref,
                        deliver=r + 1 < n_rounds,
                        round_no=r + 1,
                    )
                else:
                    ref = self._orch.run_round(ref)
            except Exception:
                # Spec-0064/T2: preserve the latest stage cursor in the
                # portable archive in addition to the already durable ledger.
                write_run_state(
                    self._state_dir,
                    RunState(
                        recovery_revision=getattr(self._orch, "recovery_revision", 0),
                        round=r,
                        phase=(
                            self._orch.recovery_phase(round_no=r + 1)
                            if getattr(self._orch, "recovery_enabled", False)
                            else "a"
                        ),
                        current_release_ref=ref,
                    ),
                )
                self._save(
                    self._state_dir,
                    self._artifact_dir / f"checkpoint-round-{r + 1}-incomplete.tar.gz",
                )
                raise
            write_run_state(
                self._state_dir,
                RunState(
                    recovery_revision=getattr(self._orch, "recovery_revision", 0),
                    round=r + 1,
                    phase=("completed" if getattr(self._orch, "recovery_enabled", False) else "c"),
                    current_release_ref=ref,
                ),
            )
            latest = self._save(
                self._state_dir, self._artifact_dir / f"checkpoint-round-{r + 1}.tar.gz"
            )
        return latest
