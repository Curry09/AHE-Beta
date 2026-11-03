# Spec-0007/T3: one-off migration unit tests for migrate_trunk_main (using a real temporary Git repository; does not touch the remote).
"""Verify main←release convergence:

- main points to the old release tip (all content and history are preserved; `git log` shows the release history), and all release/orphan/merged branches are deleted,
  leaving only main locally;
- repeated runs are idempotent, with no side effects or errors;
- if release does not exist / main is not an ancestor of release → safely skip, print the reason, do not execute -f or delete anything, and leave the repository state unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from migrate_trunk_main import migrate_trunk_main


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _branches(repo: Path) -> list[str]:
    return sorted(b for b in _git(repo, "branch", "--format=%(refname:short)").split("\n") if b)


def _seed_main_plus_release(tmp_path: Path) -> Path:
    """Seed main (with an empty seed commit) + release (several commits ahead) + an orphan fix/issue-* branch + one merged branch."""
    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "main.md").write_text("v0 seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed: harness v0")  # Empty main seed
    # release branched from main, ahead by multiple evolution commits
    _git(repo, "branch", "release")
    _git(repo, "checkout", "release")
    for i in (1, 2, 3):
        (repo / "main.md").write_text(f"v0 seed\n# evo {i}\n", encoding="utf-8")
        _git(repo, "commit", "-am", f"release: evo {i}")
    # Orphan fix/issue-* branches (branched from release, left behind)
    for n in (7, 8):
        _git(repo, "branch", f"fix/issue-{n}")
    # A branch already merged into release
    _git(repo, "branch", "merged-feat")
    _git(repo, "checkout", "main")
    return repo


def test_migrates_main_to_release_tip_and_prunes(tmp_path) -> None:
    repo = _seed_main_plus_release(tmp_path)
    release_tip = _git(repo, "rev-parse", "release")
    release_log = _git(repo, "log", "release", "--oneline")

    rc = migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None)
    assert rc == 0
    # main points to the old release tip; all content and release history are preserved
    assert _git(repo, "rev-parse", "main") == release_tip
    assert (repo / "main.md").read_text(encoding="utf-8") == "v0 seed\n# evo 3\n"
    assert _git(repo, "log", "main", "--oneline") == release_log
    assert "release: evo 3" in release_log
    # Only main remains locally (release/orphan/merged branches all deleted)
    assert _branches(repo) == ["main"]


def test_idempotent_second_run_noop(tmp_path) -> None:
    repo = _seed_main_plus_release(tmp_path)
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    head_after_first = _git(repo, "rev-parse", "main")
    # Second run: no release → no-op; no error and no changes
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    assert _git(repo, "rev-parse", "main") == head_after_first
    assert _branches(repo) == ["main"]


def test_no_release_safe_skip(tmp_path) -> None:
    """No release branch exists to begin with (pure trunk) → treat as already migrated; return 0 as a no-op, leaving branches unchanged."""
    repo = tmp_path / "h"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    assert migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None) == 0
    assert _branches(repo) == ["main"]


def test_main_not_ancestor_of_release_safe_exit(tmp_path) -> None:
    """main has diverged (is not an ancestor of release) → exit safely with rc=1, without executing -f or deletion; leave branches and HEAD unchanged."""
    repo = _seed_main_plus_release(tmp_path)
    # Give main a commit that is absent from release → main is no longer an ancestor of release
    (repo / "main.md").write_text("v0 seed\n# main-only divergence\n", encoding="utf-8")
    _git(repo, "commit", "-am", "main: diverge")
    main_before = _git(repo, "rev-parse", "main")
    branches_before = _branches(repo)

    rc = migrate_trunk_main(repo=repo, push_remote=False, set_default_branch=None)
    assert rc == 1
    assert _git(repo, "rev-parse", "main") == main_before  # Unchanged
    assert _branches(repo) == branches_before  # release/orphans still exist; not deleted
