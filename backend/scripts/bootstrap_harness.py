# Spec-0007/T4：纯 trunk——bootstrap 不再建 release 分支，只种 main 并确保默认分支为 main。
"""harness 仓初始化（spec-0002/T3）：把 backend/harness_template/ 作为 v0 推到 Gitea，建独立 harness 仓。

读 backend/deploy/gitea/.env 的 {GITEA_URL, OWNER, TOKEN} → 建仓（缺则建，幂等）→ git push 种子到 main。
纯 trunk（Spec-0007）：只建单 main 分支（不再建 release），默认分支即 main。幂等且保护演化历史：仓已
存在则不强推覆盖。核心逻辑 bootstrap_harness 经依赖注入（session / run_git），便于 mock Gitea + 临时 git 单测。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import requests

# harness 仓名，独立于 T1 的 issue 工作仓，避免 issue 流与代码演化混用。
HARNESS_REPO = "harness"
_SEED_COMMIT_MSG = "seed: harness_template v0"

# 注入的 git 执行器：(args, cwd) -> None，失败抛 CalledProcessError。
GitRun = Callable[[list[str], str], None]


def _read_env(env_path: Path) -> dict[str, str]:
    """解析 KEY=VALUE 行的 .env。"""
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def _remote_url(gitea_url: str, token: str, owner: str, repo: str) -> str:
    """把 token 注入 remote URL（不落入仓内容）。"""
    host = urlparse(gitea_url).netloc
    scheme = urlparse(gitea_url).scheme or "http"
    return f"{scheme}://{token}@{host}/{owner}/{repo}.git"


def _push_seed(template_dir: Path, remote: str, run_git: GitRun) -> None:
    """在临时工作目录初始化 git、复制种子、单条初始提交并 push 到 main。"""
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
    """初始化 harness 仓，返回退出码（成功/幂等重跑=0，前置缺失=2，连接/鉴权失败=1）。"""
    template_dir = repo_root / "harness_template"
    if not template_dir.is_dir() or not any(template_dir.iterdir()):
        print(f"[bootstrap-harness] 前置缺失：{template_dir} 不存在或为空", file=sys.stderr)
        return 2

    api = f"{gitea_url.rstrip('/')}/api/v1"
    try:
        created = session.post(
            f"{api}/user/repos",
            json={"name": harness_repo, "auto_init": False, "private": True},
        )
        if created.status_code == 201:
            # 新建空仓 → 推种子到 main。
            _push_seed(template_dir, _remote_url(gitea_url, token, owner, harness_repo), run_git)
        elif created.status_code == 409:
            # 仓已存在 → 不强推覆盖，保护开发者 agent 已产生的演化历史。
            print("[bootstrap-harness] harness 仓已存在，跳过推种子（保护演化历史）")
        else:
            print(f"[bootstrap-harness] 建仓失败：HTTP {created.status_code}", file=sys.stderr)
            return 1

        # Spec-0007/T4：纯 trunk——不再建 release 分支，确保 Gitea 默认分支为 main。
        default = session.patch(
            f"{api}/repos/{owner}/{harness_repo}",
            json={"default_branch": "main"},
        )
        if default.status_code not in (200, 201):
            print(
                f"[bootstrap-harness] 设默认分支 main 失败：HTTP {default.status_code}",
                file=sys.stderr,
            )
            return 1
    except requests.RequestException as exc:
        print(f"[bootstrap-harness] Gitea 不可达：{exc}", file=sys.stderr)
        return 1

    print(f"[bootstrap-harness] 完成：{owner}/{harness_repo}（纯 trunk：单 main）")
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
