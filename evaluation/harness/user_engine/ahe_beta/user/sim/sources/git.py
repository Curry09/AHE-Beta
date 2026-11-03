"""git SeedSource (spec-0009/T4).

Spec-0009/T4: git source (repo@commit snapshot working tree)

provision returns a clean snapshot directory of "some repository stopped at some commit"—the starting point for real repo tasks (SWE-bench base_commit in unfixed state, funcy@some version, etc.). repo/commit (and optional ref/depth) all go into `WorkspaceSpec.params`, without schema expansion, kind="git".

Network policy (large repos + slow networks survival): cache shared per **repository** (backend/data/repo_cache/<slug>/repo), each target commit fetched from the network only once—`git fetch --depth 1 <repo> <sha>:refs/seeds/<sha>` directed shallow fetch by SHA (GitHub supports reachable SHA fetch; second and later commits in the same repo use incremental delta, only a few MB); when server does not support SHA-based fetch, fall back to full clone to rebuild cache (compatible with local bare repos). Then each provision session copytree that cache + checkout target commit in the copy, each session is still an isolated directory with no state leakage across sessions (isolation semantics equivalent to "fresh clone per session").

Pluggable proof: integrating it only adds this module—auto-discovered and registered via spec-0009/T1's sources/, seed_source / models / workspace and all consumer side (orchestrator / sim_user / Sandbox) remain unchanged."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.seed_source import register

# Repository cache root: backend/data/repo_cache (runtime artifacts, globally .gitignored under data/).
_CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "repo_cache"


@register("git")
class GitSource:
    kind = "git"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        """Provision an isolated working tree of repo@commit (pure local copy if cache hit).

        Spec-0009/T4: read repo (required), commit (required), optional ref/depth from spec.params; ensure commit object enters repo cache, then copytree to isolated directory and checkout, return absolute path of that directory.
        """
        # 1. Read and self-validate params (do not expand WorkspaceSpec; field completeness guaranteed by source).
        repo = spec.params.get("repo")
        commit = spec.params.get("commit")
        if not repo:
            raise ValueError("git source requires a nonempty params.repo (clone URL or local path)")
        if not commit:
            raise ValueError(
                "git source requires a nonempty params.commit (snapshot SHA/ref to restore)"
            )
        ref = spec.params.get("ref")
        depth = spec.params.get("depth")

        cache = _ensure_commit_cached(repo=str(repo), commit=str(commit), ref=ref, depth=depth)

        # 2. Fresh per session: copy a separate directory from the cache, then checkout; sessions remain isolated and can be cleaned up.
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_git_")
        dest = Path(base) / "repo"
        shutil.copytree(cache, dest, symlinks=True)

        # 3. Checkout to target commit; shallow clones may not retrieve arbitrary historical commits,
        #    fall back to fetch --unshallow for full fetch and retry (shallow clone + arbitrary commit compatibility).
        try:
            _run_git(cmd=["git", "checkout", "-q", str(commit)], cwd=str(dest))
        except RuntimeError:
            if not depth:
                raise
            _run_git(cmd=["git", "fetch", "--unshallow"], cwd=str(dest))
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(dest))

        return str(dest.resolve())


def _ensure_commit_cached(*, repo: str, commit: str, ref: str | None, depth: int | None) -> Path:
    """Ensure commit object is in repo's shared cache and return cache path; network touched only on miss.

    Fetch priority: ① `fetch --depth 1 <repo> <sha>:refs/seeds/<sha>` directed shallow fetch by SHA and anchor with ref (prevent gc), incremental object reuse for multiple commits in same repo; ② first commit and server rejects SHA-based fetch (local bare repo/old server), fall back to full clone to rebuild cache. After each commit succeeds, mark with shas/<sha>, cache hit skips network; cache repo itself not checked out (copytree only moves .git, working tree generated in provision copy).
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo).strip("-")[-60:] or "repo"
    entry = _CACHE_ROOT / slug
    cache = entry / "repo"
    markers = entry / "shas"
    marker = markers / commit
    if marker.is_file() and (cache / ".git").is_dir():
        return cache
    markers.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").is_dir():  # First creation or remnants of last build
        shutil.rmtree(cache, ignore_errors=True)
        _run_git(cmd=["git", "init", "-q", str(cache)], cwd=None)

    # Existing commit (e.g., from a full-clone fallback) → no network
    if _has_commit(cache=cache, commit=commit):
        marker.touch()
        return cache

    try:
        _run_git(
            cmd=["git", "fetch", "--depth", "1", repo, f"{commit}:refs/seeds/{commit[:12]}"],
            cwd=str(cache),
        )
    except RuntimeError:
        if any(markers.iterdir()):
            # Cache has prior content, SHA-based fetch for new commit fails → full fetch update;
            # Reachability ultimately diagnosed by checkout in the provision copy.
            _run_git(
                cmd=["git", "fetch", repo, "+refs/heads/*:refs/seeds/heads/*"],
                cwd=str(cache),
            )
        else:
            # Fallback: full clone (legacy path), optionally accelerate with depth/ref (compatible with local bare repos/old servers).
            shutil.rmtree(cache)
            clone_cmd = ["git", "clone"]
            if depth:
                clone_cmd += ["--depth", str(depth)]
            if ref:
                clone_cmd += ["--branch", str(ref)]
            clone_cmd += [repo, str(cache)]
            _run_git(cmd=clone_cmd, cwd=None)

    marker.touch()
    return cache


def _has_commit(*, cache: Path, commit: str) -> bool:
    """Whether cache repo already has this commit object (cat-file -e; any failure treated as absent)."""
    try:
        _run_git(cmd=["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=str(cache))
        return True
    except RuntimeError:
        return False


def _run_git(*, cmd: list[str], cwd: str | None) -> subprocess.CompletedProcess[str]:
    """Run a git subprocess, raising with diagnostics on failure.

    Spec-0009/T4: on clone/checkout failure, raise RuntimeError with diagnostics carrying failed command + returncode + truncated stderr (aligned with T3 deps.py error style).
    """
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if len(stderr) > 2000:
            stderr = stderr[:2000] + "…(stderr truncated)"
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)} (returncode={proc.returncode})\nstderr: {stderr}"
        )
    return proc
