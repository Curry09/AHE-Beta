# Spec-0021/T1: Orchestration repo integrity trip-wire—during run, the orchestration repo (ahe-beta checkout) must remain frozen; any touch by dev is exposed.
"""repo_guard: Orchestration repo integrity snapshot and verification.

In practice, dev agents use Python heredoc tunnels to bypass workspace-jail path scanning, `os.chdir` into the orchestration repo
(the ahe-beta checkout itself), modify files, and commit/push. Path-level jail cannot contain agents that can invoke interpreters. This module provides
an **independent channel** as a backstop: before run, take a snapshot of the orchestration repo (HEAD, porcelain), then after each round b segment (dev direct push) verify
no changes—if even one character is modified, HEAD or porcelain will change, immediately raise an error and stop, no longer relying on manual discovery from the remote.

The trip-wire is **detection + fail-closed stop**, not prevention (prevention is done by run.py's credential isolation to block pushes; the two are complementary layers).
"""

from __future__ import annotations

import subprocess

# Python imports in the frozen harness checkout may create bytecode caches while a
# role is running.  They are runtime by-products, not edits to the orchestration
# source.  Keep the guard fail-closed for every other untracked path.
_GENERATED_CACHE_SUFFIXES = ("/__pycache__", ".pyc", ".pyo")


def _meaningful_porcelain(value: str) -> str:
    """Remove interpreter-generated cache entries from a git status snapshot."""
    lines = []
    for line in value.splitlines():
        path = line[3:] if len(line) >= 4 else line
        if any(path.endswith(suffix) or suffix in path for suffix in _GENERATED_CACHE_SUFFIXES):
            continue
        lines.append(line)
    return "\n".join(lines)


class RepoIntegrityError(RuntimeError):
    """The orchestration repo was modified during a run (HEAD or working tree changed relative to the snapshot taken before start)."""


def _git(repo: str, *args: str) -> str:
    """Run a git subcommand, return stdout (stripped); any non-zero exit or exception raises RepoIntegrityError (err on the side of caution)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepoIntegrityError(
            f"Failed to read orchestration repository git state ({repo}): {exc}"
        ) from exc
    if result.returncode != 0:
        raise RepoIntegrityError(
            f"Orchestration repository git {args!r} exited nonzero ({repo}): {result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


def snapshot_repo(*, repo: str) -> tuple[str, str]:
    """Take a snapshot of the orchestration repo = (HEAD commit SHA, full text of `git status --porcelain`).

    dev commits → HEAD changes; dev modifies tracked file → porcelain shows ` M …`; dev creates new file → porcelain
    shows `?? …`. Pre-existing untracked files (local docs / .idea, etc.) appear in both before and after snapshots; if identical, they were not touched.
    """
    head = _git(repo, "rev-parse", "HEAD")
    porcelain = _meaningful_porcelain(_git(repo, "status", "--porcelain"))
    return (head, porcelain)


def verify_unchanged(*, repo: str, before: tuple[str, str]) -> None:
    """Verify the orchestration repo has not changed relative to the before snapshot; if changed, raise RepoIntegrityError with a diff summary."""
    after = snapshot_repo(repo=repo)
    if after == before:
        return
    head_before, porc_before = before
    head_after, porc_after = after
    parts: list[str] = []
    if head_after != head_before:
        parts.append(f"HEAD {head_before[:12]} → {head_after[:12]} (new commit)")
    if porc_after != porc_before:
        # Report only newly added porcelain lines (pre-existing untracked do not count), so the alert points directly to touched files.
        added = [ln for ln in porc_after.splitlines() if ln not in porc_before.splitlines()]
        detail = "；".join(added[:10]) if added else "Working tree status changed"
        parts.append(f"New working tree changes: {detail}")
    raise RepoIntegrityError(
        f"Orchestration repository {repo} changed during the run (possible developer agent sandbox escape): {'; '.join(parts)}"
    )
