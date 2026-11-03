"""git SeedSource (spec-0009/T4).

Coverage: local temporary git repo clone@commit snapshot recovery, directory isolation, missing repo/commit and clone/checkout failure diagnostic errors, additivity/dispatch (auto-discovery of git on import seed_source only), kind=git serialization round-trip.
All offline—use `git init` to create local repo as repo, no real network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ahe_beta.models import WorkspaceSpec


def _git(*, args: list[str], cwd: Path) -> None:
    env_args = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    subprocess.run(env_args, cwd=cwd, check=True, capture_output=True, text=True)


def _rev_parse(*, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _make_repo(*, root: Path) -> tuple[str, str]:
    """Create a local repo with two commits; return sha of (C1, C2)."""
    root.mkdir(parents=True, exist_ok=True)
    _git(args=["init"], cwd=root)
    (root / "a.txt").write_text("first\n")
    _git(args=["add", "a.txt"], cwd=root)
    _git(args=["commit", "-m", "c1"], cwd=root)
    c1 = _rev_parse(cwd=root)
    (root / "b.txt").write_text("second\n")
    _git(args=["add", "b.txt"], cwd=root)
    _git(args=["commit", "-m", "c2"], cwd=root)
    c2 = _rev_parse(cwd=root)
    return c1, c2


def test_git_auto_registered_without_importing_module() -> None:
    # hard evidence of additivity: this test does not import sources.git, only import seed_source, so git is in the registry.
    from ahe_beta.user.sim import seed_source

    assert "git" in seed_source.available_kinds()


def test_git_dispatch_to_git_source() -> None:
    from ahe_beta.user.sim import seed_source

    assert type(seed_source.get_source("git")).__name__ == "GitSource"


def test_git_provisions_snapshot_at_commit(tmp_path: Path) -> None:
    from ahe_beta.user.sim import seed_source

    repo = tmp_path / "origin"
    c1, c2 = _make_repo(root=repo)

    ws = seed_source.provision(WorkspaceSpec(kind="git", params={"repo": str(repo), "commit": c1}))
    ws_path = Path(ws)
    assert ws_path.is_dir()
    # working tree restored to C1: HEAD == C1, C1 files present, C2 new files absent.
    assert _rev_parse(cwd=ws_path) == c1
    assert (ws_path / "a.txt").is_file()
    assert not (ws_path / "b.txt").exists()

    # when checking out to C2 there are different files.
    ws2 = seed_source.provision(WorkspaceSpec(kind="git", params={"repo": str(repo), "commit": c2}))
    assert _rev_parse(cwd=Path(ws2)) == c2
    assert (Path(ws2) / "b.txt").is_file()


def test_git_dirs_isolated(tmp_path: Path) -> None:
    from ahe_beta.user.sim import seed_source

    repo = tmp_path / "origin"
    c1, _ = _make_repo(root=repo)

    spec = WorkspaceSpec(kind="git", params={"repo": str(repo), "commit": c1})
    a = seed_source.provision(spec)
    b = seed_source.provision(spec)
    assert a != b
    # modifying one copy does not affect the other.
    (Path(a) / "a.txt").write_text("clobbered\n")
    assert (Path(b) / "a.txt").read_text() == "first\n"


def test_git_missing_repo_or_commit_raises(tmp_path: Path) -> None:
    from ahe_beta.user.sim import seed_source

    repo = tmp_path / "origin"
    c1, _ = _make_repo(root=repo)

    with pytest.raises(ValueError) as ei_repo:
        seed_source.provision(WorkspaceSpec(kind="git", params={"commit": c1}))
    assert "repo" in str(ei_repo.value)

    with pytest.raises(ValueError) as ei_commit:
        seed_source.provision(WorkspaceSpec(kind="git", params={"repo": str(repo)}))
    assert "commit" in str(ei_commit.value)


def test_git_clone_failure_raises_with_diagnostics(tmp_path: Path) -> None:
    from ahe_beta.user.sim import seed_source

    bad = tmp_path / "does-not-exist"
    with pytest.raises(RuntimeError) as ei:
        seed_source.provision(
            WorkspaceSpec(kind="git", params={"repo": str(bad), "commit": "deadbeef"})
        )
    msg = str(ei.value)
    assert "git clone" in msg
    assert "returncode=" in msg
    assert "stderr" in msg


def test_git_checkout_failure_raises_with_diagnostics(tmp_path: Path) -> None:
    from ahe_beta.user.sim import seed_source

    repo = tmp_path / "origin"
    _make_repo(root=repo)
    with pytest.raises(RuntimeError) as ei:
        seed_source.provision(
            WorkspaceSpec(kind="git", params={"repo": str(repo), "commit": "0" * 40})
        )
    msg = str(ei.value)
    assert "git checkout" in msg
    assert "returncode=" in msg


def test_git_spec_roundtrip() -> None:
    g = WorkspaceSpec(kind="git", params={"repo": "https://x/y.git", "commit": "abc123"})
    assert g.to_dict()["kind"] == "git"
    assert WorkspaceSpec.from_dict(g.to_dict()) == g
