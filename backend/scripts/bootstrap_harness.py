# Spec-0007/T4: pure trunk——bootstrap no longer creates release branches, only seeds main and ensures default branch is main.
"""harness repo initialization (spec-0002/T3): push backend/harness_template/ as v0 to Gitea, create independent harness repo.

Read {GITEA_URL, OWNER, TOKEN} from backend/deploy/gitea/.env → create repo (create if missing, idempotent) → git push seed to main.
Pure trunk (Spec-0007): create only single main branch (no release branches), default branch is main. Idempotent and preserves evolution history: if repo exists, do not force-push overwrite. Core logic bootstrap_harness uses dependency injection (session / run_git) for easy mocking of Gitea + temporary git unit tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import requests

# harness repo name, independent from T1's issue tracking repo, avoiding mixing issue flow with code evolution.
HARNESS_REPO = "harness"
_SEED_COMMIT_MSG = "seed: harness_template v0"

# Injected git executor: (args, cwd) -> None; raises CalledProcessError on failure.
GitRun = Callable[[list[str], str], None]


def _read_env(env_path: Path) -> dict[str, str]:
    """Parse a .env of KEY=VALUE lines."""
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def _remote_url(gitea_url: str, token: str, owner: str, repo: str) -> str:
    """Inject the token into the remote URL (never lands in repo content)."""
    host = urlparse(gitea_url).netloc
    scheme = urlparse(gitea_url).scheme or "http"
    return f"{scheme}://{token}@{host}/{owner}/{repo}.git"


def _push_seed(template_dir: Path, remote: str, run_git: GitRun) -> None:
    """Initialize git in a temp workdir, copy the seed, make a single initial commit, and push to main."""
    with tempfile.TemporaryDirectory() as tmp:
        run_git(["init", "-b", "main"], tmp)
        for item in template_dir.iterdir():
            dest = Path(tmp) / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        run_git(["add", "."], tmp)
        run_git(
            [
                "-c",
                "user.email=bot@ahe-beta",
                "-c",
                "user.name=ahe-beta",
                "commit",
                "-m",
                _SEED_COMMIT_MSG,
            ],
            tmp,
        )
        run_git(["remote", "add", "origin", remote], tmp)
        run_git(["push", "-u", "origin", "HEAD:main"], tmp)


def bootstrap_harness(
    *,
    session: requests.Session,
    run_git: GitRun,
    repo_root: Path,
    gitea_url: str,
    owner: str,
    token: str,
    harness_repo: str,
) -> int:
    """Initialize the harness repo and return the exit code (success/idempotent rerun=0, missing prerequisite=2, connection/auth failure=1)."""
    template_dir = repo_root / "harness_template"
    if not template_dir.is_dir() or not any(template_dir.iterdir()):
        print(
            f"[bootstrap-harness] Missing prerequisite: {template_dir} does not exist or is empty",
            file=sys.stderr,
        )
        return 2

    api = f"{gitea_url.rstrip('/')}/api/v1"
    try:
        created = session.post(
            f"{api}/user/repos",
            json={"name": harness_repo, "auto_init": False, "private": True},
        )
        if created.status_code == 201:
            # New empty repo → push seed to main.
            _push_seed(template_dir, _remote_url(gitea_url, token, owner, harness_repo), run_git)
        elif created.status_code == 409:
            # Repo already exists → do not force-push over it; protect the evolution history already produced by the developer agent.
            print(
                "[bootstrap-harness] Harness repository already exists; skipping the seed push to preserve its evolution history"
            )
        else:
            print(
                f"[bootstrap-harness] Repository creation failed: HTTP {created.status_code}",
                file=sys.stderr,
            )
            return 1

        # Spec-0007/T4: pure trunk — no more release branches; ensure the Gitea default branch is main.
        default = session.patch(
            f"{api}/repos/{owner}/{harness_repo}",
            json={"default_branch": "main"},
        )
        if default.status_code not in (200, 201):
            print(
                f"[bootstrap-harness] Failed to set main as the default branch: HTTP {default.status_code}",
                file=sys.stderr,
            )
            return 1
    except requests.RequestException as exc:
        print(f"[bootstrap-harness] Gitea is unreachable: {exc}", file=sys.stderr)
        return 1

    print(f"[bootstrap-harness] Complete: {owner}/{harness_repo} (single main trunk)")
    return 0


def _real_git_run(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = _read_env(repo_root / "deploy" / "gitea" / ".env")
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"token {env['TOKEN']}", "Content-Type": "application/json"}
    )
    return bootstrap_harness(
        session=session,
        run_git=_real_git_run,
        repo_root=repo_root,
        gitea_url=env["GITEA_URL"],
        owner=env["OWNER"],
        token=env["TOKEN"],
        harness_repo=HARNESS_REPO,
    )


if __name__ == "__main__":
    raise SystemExit(main())
