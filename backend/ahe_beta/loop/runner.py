"""Resumable Harbor runner (Spec-0004/T2, Spec-0064/T2).

Driven per-round outside orchestrator; each round boundary write_run_state + save_checkpoint, output sandbox via harbor artifact channel;
new runs can resume to phase/work item via Orchestrator's recovery ledger; old runs still recover by complete round cursor.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ahe_beta.loop.checkpoint import load_checkpoint, save_checkpoint
from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.run_state import RunState, read_run_state, write_run_state

# checkpoint read/write injection point (default real implementation; tests can inject spy).
SaveFn = Callable[[Path, Path], Path]
LoadFn = Callable[[Path, Path], None]


class HarborRunner:
    """Resumable run entry point outside orchestrator."""

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
        """Run up to n_rounds rounds; emit incremental checkpoint at each round end, return latest artifact (return input if no rounds)."""
        if n_rounds <= 0:
            raise ValueError(f"n_rounds must be positive: {n_rounds}")

        if checkpoint_artifact is not None:
            self._load(Path(checkpoint_artifact), self._state_dir)  # restore STATE_DIR
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
