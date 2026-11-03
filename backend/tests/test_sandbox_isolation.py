"""Isolation layout assertion between dev/architect sandbox and trace directories.

Structural isolation: move the harness repo to an independent parent directory, so that traces (user experience/session data in sessions, harness runtime copies in harness_runs) are no longer a sibling `../` of the sandbox—relative paths `../sessions`/`../harness_runs` cannot reach it, blocking the overfitting leak of "dev/architect reviewing task trajectory → bringing task-specific artifacts into harness".
"""

from __future__ import annotations

from ahe_beta.experiment.controllers import runtime as run


def test_harness_repo_parent_isolated_from_data() -> None:
    # Sandbox's parent directory is not data/ itself—otherwise trace and repo are siblings, and `../sessions` is one step away.
    assert run.HARNESS_REPO.parent != run.DATA
    assert run.HARNESS_REPO.parent == run.DATA / "harness_sandbox"


def test_trace_dirs_not_siblings_of_sandbox() -> None:
    # Trace directories all under data/ (= sandbox's `../..`), do not appear at sandbox's `../` sibling level.
    sandbox_parent = run.HARNESS_REPO.parent
    for trace in ("sessions", "harness_runs"):
        assert not (sandbox_parent / trace).exists() or (sandbox_parent / trace) != (
            run.DATA / trace
        )
        # Key: banned relative target (relative to sandbox, ../<trace>) does not equal actual trace directory
        assert (sandbox_parent / trace) != (run.DATA / trace)
