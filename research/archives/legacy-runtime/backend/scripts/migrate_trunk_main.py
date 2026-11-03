# Spec-0007/T3: One-time migration script—converge the harness repository from main+release to trunk-only (single main).
"""Converge the evolution results from release to main without losing anything:

`git checkout main && git reset --hard release` (move main to the release tip, preserving all release history and contents) →
delete all local branches except main (release + orphaned fix/issue-* + merged branches) → optional: push main, delete remote release,
confirm that the Gitea default branch is main.

Idempotent: already migrated (no release branch) → no-op, no error. Safely exit and provide a notice for unexpected repository states (no release, main is not an ancestor of release);
never perform destructive `-f` operations or deletions.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# Optional callback: confirm/switch the remote (Gitea) default branch to the specified branch name; None skips this step (purely local migration).
SetDefaultBranch = Callable[[str], None]


def _git(repo: Path, *args: str) -> str:
    """Run git inside the repo (check=True; raises CalledProcessError on failure) and return stdout."""
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _branches(repo: Path) -> list[str]:
    """List local branch names."""
    out = _git(repo, "branch", "--format=%(refname:short)")
    return [b for b in out.split("\n") if b]


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """Whether ancestor is an ancestor of descendant (equality counts as true)."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
        ).returncode
        == 0
    )


def migrate_trunk_main(
    *,
    repo: Path,
    push_remote: bool,
    set_default_branch: SetDefaultBranch | None,
) -> int:
    """Execute the migration and return the exit code: 0 = migration succeeded / already migrated (no-op); 1 = unexpected repository state, safely skipped without changes."""
    repo = Path(repo)
    branches = _branches(repo)

    # Idempotent: no release branch (already migrated or originally trunk) → no-op; do not report an error or touch any branch.
    if "release" not in branches:
        print("[migrate-trunk] None release branch → Treat as migrated，Skip")
        return 0

    # Safety gate: main must be an ancestor of release (release ⊃ main) before main may be fast-forwarded to the release tip.
    # Otherwise (main is ahead or has diverged), this is an unexpected state; never force -f or delete anything—hand it over for manual handling.
    if "main" not in branches or not _is_ancestor(repo, "main", "release"):
        print(
            "[migrate-trunk] main Non release ancestor（Or missing main）→ Exit safely，Do not execute -f/deletion",
            file=sys.stderr,
        )
        return 1

    # Migration: move main to the release tip (reset --hard to release; because release ⊃ main, all history and content are preserved).
    _git(repo, "checkout", "main")
    _git(repo, "reset", "--hard", "release")

    # Delete all local branches except main (release + orphaned fix/issue-* + merged branches), leaving only the main line locally.
    for branch in _branches(repo):
        if branch != "main":
            _git(repo, "branch", "-D", branch)

    if push_remote:
        _git(repo, "push", "origin", "main")
        # Delete the remote release branch (ignore it if it no longer exists, preserving idempotence).
        subprocess.run(
            ["git", "-C", str(repo), "push", "origin", "--delete", "release"],
            capture_output=True,
        )

    # Confirm that the remote default branch is main (so the default view shows the version that is actually evolving).
    if set_default_branch is not None:
        set_default_branch("main")

    print("[migrate-trunk] Completed：Locally only main（release/orphan/Merged branches deleted）")
    return 0


def _gitea_default_branch_setter(*, session, api: str, owner: str, repo: str) -> SetDefaultBranch:
    """Construct a callback that sets the Gitea repository's default branch to the given branch (PATCH /repos/{owner}/{repo})."""

    def _set(branch: str) -> None:
        resp = session.patch(f"{api}/repos/{owner}/{repo}", json={"default_branch": branch})
        if resp.status_code not in (200, 201):
            print(
                f"[migrate-trunk] Set the default branch to {branch} Failed：HTTP {resp.status_code}",
                file=sys.stderr,
            )

    return _set


def main() -> int:
    import requests

    from bootstrap_harness import HARNESS_REPO, _read_env  # Reuse .env parsing and repository name

    repo_root = Path(__file__).resolve().parents[1]  # backend/
    harness_repo = repo_root / "data" / "harness_repo"
    if not (harness_repo / ".git").is_dir():
        print(f"[migrate-trunk] Missing prerequisite：{harness_repo} Is not git Repository", file=sys.stderr)
        return 2

    env = _read_env(repo_root / "deploy" / "gitea" / ".env")
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"token {env['TOKEN']}", "Content-Type": "application/json"}
    )
    api = f"{env['GITEA_URL'].rstrip('/')}/api/v1"
    setter = _gitea_default_branch_setter(
        session=session, api=api, owner=env["OWNER"], repo=HARNESS_REPO
    )
    return migrate_trunk_main(repo=harness_repo, push_remote=True, set_default_branch=setter)


if __name__ == "__main__":
    raise SystemExit(main())
